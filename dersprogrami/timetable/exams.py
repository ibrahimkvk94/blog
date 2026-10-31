"""Sınav programı işlemleri: derslerden sınav üretme, birleştirme/bölme, öğrenci sayısı, gözetmen müsaitliği,
çözücüyü arka planda çalıştırma, sonuçların kaydı ve denetimi.

Gözetmen müsaitliği (basit ve öngörülebilir kural): "öğretmen müsaitliğini kullan" açıksa öğretmenin ders
programındaki "yasak" hücreleri sınav gününün hafta gününe ve oturum saatiyle çakışan ders saatlerine eşlenir
(oturum başlangıcı + oturum süresi, ders saatlerinin başlangıç–bitişiyle karşılaştırılır; ders saatlerinin saati
girilmemişse oturumlar günün ders saatlerine sırayla, orantılı dağıtılır). Ayrıca sınav dönemi için öğretmenin
gelemeyeceği gün/oturumlar "Gözetmenler" sayfasında işaretlenir; muaf öğretmenlere görev verilmez.
"""

import datetime
import threading
from collections import defaultdict

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from . import exams_solver
from .models import DAY_NAMES, Availability, Classroom, Exam, ExamPeriod, ExamPlacement, ExamRoom, Lesson, Teacher

STALE_GRACE = 180  # süre sınırından bu kadar saniye sonra hâlâ "çalışıyor" ise yarıda kalmış sayılır


# --- yardımcılar --------------------------------------------------------------------------------

def parse_time(text):
    try:
        return datetime.time.fromisoformat(str(text).strip())
    except ValueError:
        return None


def slot_label(date, session, period):
    times = period.session_times
    hour = times[session] if 0 <= session < len(times) else f"{session + 1}. oturum"
    return f"{date:%d.%m.%Y} {DAY_NAMES[date.weekday()]} {hour}"


def exam_capacity(classroom, period):
    """Salonun sınavda alacağı öğrenci: kapasite × oran; kapasitesi yoksa dönemin varsayılanı (yoksa 0)."""
    if not classroom.capacity:
        return period.default_seats or 0
    return max(1, classroom.capacity * period.capacity_percent // 100)


def exam_rooms(period):
    """Sınav salonları: seçilenler, yoksa sınav kapasitesi olan tüm derslikler."""
    rooms = list(period.rooms.all()) or list(Classroom.objects.filter(school=period.school_id).order_by("name"))
    return [r for r in rooms if exam_capacity(r, period) > 0]


# --- öğrenci sayıları ---------------------------------------------------------------------------

def class_sizes(school):
    """Sınıf → öğrenci sayısı: kayıtlı öğrenci varsa onların sayısı, yoksa sınıfın öğrenci sayısı alanı."""
    from django.db.models import Count

    sizes = {c.pk: c.student_count or 0 for c in school.classes.all()}
    for row in school.students.filter(school_class__isnull=False).values("school_class").annotate(n=Count("id")):
        sizes[row["school_class"]] = row["n"]
    return sizes


def lessons_student_count(lessons, sizes, only_class=None):
    """Derslerin toplam öğrencisi. Kayıtlı öğrencili seçmeli: öğrenci sayısı; gruplu ders: grupların sayısı
    (girilmemişse sınıfın grup başına payı); diğerleri: sınıfların tamamı. Aynı sınıf iki kez sayılmaz.
    only_class verilirse yalnızca o sınıfın payı sayılır."""
    students, whole, groups = set(), set(), defaultdict(dict)
    for lesson in lessons:
        regs = {s.pk for s in lesson.students.all() if only_class is None or s.school_class_id == only_class}
        if lesson.elective and regs:
            students |= regs
            continue
        by_class = defaultdict(list)
        for g in lesson.groups.all():
            by_class[g.division.school_class_id].append(g)
        for c in lesson.classes.all():
            if only_class is not None and c.pk != only_class:
                continue
            if c.pk in by_class:
                for g in by_class[c.pk]:
                    groups[c.pk][g.pk] = g
            else:
                whole.add(c.pk)
    total = sum(sizes.get(c, 0) for c in whole) + len(students)
    for c, gs in groups.items():
        if c in whole:
            continue
        for g in gs.values():
            share = len(g.division.groups.all()) or 1
            total += g.student_count if g.student_count is not None else sizes.get(c, 0) // share
    return total


def _lesson_qs(school):
    return (Lesson.objects.filter(school=school).select_related("subject")
            .prefetch_related("classes", "teachers", "students", "groups__division__groups"))


def refresh_counts(period, exams=None):
    """Elle girilmemiş öğrenci sayılarını kaynak derslerden yeniden hesaplar."""
    sizes = class_sizes(period.school)
    qs = exams if exams is not None else period.exams.filter(count_manual=False)
    qs = qs.prefetch_related(_prefetch_lessons(period.school), "classes")
    changed = 0
    for exam in qs:
        lessons = list(exam.lessons.all())
        n = lessons_student_count(lessons, sizes) if lessons else sum(sizes.get(c.pk, 0) for c in exam.classes.all())
        if n != exam.student_count:
            exam.student_count = n
            exam.save(update_fields=["student_count"])
            changed += 1
    return changed


def _prefetch_lessons(school):
    from django.db.models import Prefetch

    return Prefetch("lessons", queryset=_lesson_qs(school))


# --- derslerden sınav üretme --------------------------------------------------------------------

def subject_groups(school):
    """Ders adı → kısımları (sınıfı olan dersler); "ortak sınav" seçimi için."""
    groups = defaultdict(list)
    for lesson in _lesson_qs(school):
        if lesson.classes.all():
            groups[lesson.subject].append(lesson)
    return sorted(groups.items(), key=lambda kv: kv[0].name.casefold())


def generate_from_lessons(period, separate=(), replace=True):
    """Her ders adı için bir ortak sınav (tüm kısımları) üretir; separate'teki ders adlarında her kısım (ders)
    ayrı sınav olur. replace=False ise yalnızca henüz sınavı olmayan ders adları eklenir. Dönüş: eklenen sayı."""
    school = period.school
    sizes = class_sizes(school)
    separate = {int(s) for s in separate}
    with transaction.atomic():
        if replace:
            period.exams.all().delete()
            existing = set()
        else:
            existing = set(period.exams.values_list("subject_id", flat=True))
        created = 0
        for subject, lessons in subject_groups(school):
            if subject.pk in existing:
                continue
            parts = [[lesson] for lesson in lessons] if subject.pk in separate else [lessons]
            for part in parts:
                _create_exam(period, subject, part, sizes)
                created += 1
    return created


def _create_exam(period, subject, lessons, sizes, name=""):
    exam = Exam.objects.create(period=period, subject=subject, name=name,
                               student_count=lessons_student_count(lessons, sizes))
    exam.lessons.set(lessons)
    exam.classes.set({c.pk for lesson in lessons for c in lesson.classes.all()})
    exam.teachers.set({t.pk for lesson in lessons for t in lesson.teachers.all()})
    return exam


def merge(period, exam_ids):
    """Seçilen sınavları tek ortak sınavda birleştirir (ilk sınav kalır). Dönüş: kalan sınav ya da None."""
    exams = list(period.exams.filter(pk__in=exam_ids).order_by("id").prefetch_related("lessons", "classes", "teachers"))
    if len(exams) < 2:
        return None
    keep, rest = exams[0], exams[1:]
    with transaction.atomic():
        keep.lessons.add(*[lesson for e in rest for lesson in e.lessons.all()])
        keep.classes.add(*[c for e in rest for c in e.classes.all()])
        keep.teachers.add(*[t for e in rest for t in e.teachers.all()])
        keep.duration = max(e.duration for e in exams)
        if any(e.count_manual for e in exams):
            keep.student_count = sum(e.student_count for e in exams)
            keep.count_manual = True
        keep.save()
        ExamPlacement.objects.filter(exam=keep).delete()
        Exam.objects.filter(pk__in=[e.pk for e in rest]).delete()
    if not keep.count_manual:
        refresh_counts(period, Exam.objects.filter(pk=keep.pk))
    return keep


def split(period, exam_id):
    """Ortak sınavı sınıf başına ayrı sınavlara böler. Dönüş: oluşan sınav sayısı (bölünemezse 0)."""
    exam = period.exams.filter(pk=exam_id).prefetch_related(_prefetch_lessons(period.school), "classes").first()
    if exam is None:
        return 0
    classes = list(exam.classes.all())
    if len(classes) < 2:
        return 0
    sizes = class_sizes(period.school)
    lessons = list(exam.lessons.all())
    with transaction.atomic():
        for c in classes:
            own = [lesson for lesson in lessons if c in lesson.classes.all()]
            # birden çok sınıflı dersin yalnızca bu sınıfın payı sayılır
            count = lessons_student_count(own, sizes, only_class=c.pk) if own else sizes.get(c.pk, 0)
            new = Exam.objects.create(period=period, subject=exam.subject, name=exam.name, duration=exam.duration,
                                      note=exam.note, student_count=count)
            new.classes.set([c])
            new.lessons.set(own)
            new.teachers.set({t.pk for lesson in own for t in lesson.teachers.all()} or set(exam.teachers.values_list("pk", flat=True)))
        exam.delete()
    return len(classes)


# --- gözetmen müsaitliği ------------------------------------------------------------------------

def session_periods(period, school_periods, weekday):
    """Oturum sırası → bu hafta gününde çakıştığı ders saati sıraları."""
    times = period.session_times
    out = {}
    timed = [p for p in school_periods if all(p.times(weekday))]
    for s, text in enumerate(times):
        start = parse_time(text)
        if start is not None and timed:
            begin = datetime.datetime.combine(datetime.date(2000, 1, 1), start)
            end = begin + datetime.timedelta(minutes=period.exam_minutes or 60)
            hits = []
            for p in timed:
                ps, pe = p.times(weekday)
                pb = datetime.datetime.combine(datetime.date(2000, 1, 1), ps)
                pend = datetime.datetime.combine(datetime.date(2000, 1, 1), pe)
                if pb < end and begin < pend:
                    hits.append(p.index)
            out[s] = hits
        else:
            n, k = len(school_periods), len(times) or 1
            lo, hi = s * n // k, max(s * n // k + 1, (s + 1) * n // k)
            out[s] = [p.index for p in school_periods[lo:hi]]
    return out


def proctor_blocks(period):
    """{öğretmen: {(tarih, oturum), ...}}: müsaitlikten ve dönem işaretlerinden gelen kapalı oturumlar."""
    school = period.school
    slots = period.slots()
    blocked = defaultdict(set)
    if period.use_availability:
        school_periods = list(school.periods.order_by("index"))
        maps = {}
        rows = defaultdict(set)
        for tid, day, p in Availability.objects.filter(school=school, teacher__isnull=False, state=Availability.NO).values_list(
                "teacher_id", "day", "period"):
            rows[tid].add((day, p))
        for date, s in slots:
            wd = date.weekday()
            if wd >= school.days_per_week:
                continue
            if wd not in maps:
                maps[wd] = session_periods(period, school_periods, wd)
            hits = maps[wd].get(s, [])
            for tid, cells in rows.items():
                if any((wd, p) in cells for p in hits):
                    blocked[tid].add((date, s))
    n = len(period.session_times)
    for tid, items in (period.proctor_blocks or {}).items():
        for item in items:
            text, _, sess = str(item).partition("#")
            try:
                date = datetime.date.fromisoformat(text)
            except ValueError:
                continue
            sessions = [int(sess)] if sess.isdigit() else range(n)
            for s in sessions:
                blocked[int(tid)].add((date, s))
    return blocked


def proctor_pool(period):
    exempt = set(period.proctor_exempt.values_list("pk", flat=True))
    return [t for t in period.school.teachers.all() if t.pk not in exempt]


# --- problem kurma ve çözüm ---------------------------------------------------------------------

def build_problem(period, keep_locked=True):
    dates = period.dates()
    times = period.session_times
    n_s = len(times)
    index = {d: i for i, d in enumerate(dates)}

    def slot_of(date, session):
        if date not in index or session is None or not 0 <= session < n_s:
            return -1
        return index[date] * n_s + session

    rooms = exam_rooms(period)
    room_ids = {r.pk for r in rooms}
    exams = (period.exams.filter(excluded=False).select_related("subject", "placement")
             .prefetch_related("classes", "teachers", "allowed_rooms", "lessons__students", "placement__rooms__proctors"))
    p_exams = []
    for e in exams:
        fixed = slot_of(e.fixed_date, e.fixed_session) if e.fixed_date else None
        if e.fixed_date and e.fixed_session is None:
            fixed = -1 if e.fixed_date not in index else None
        locked_rooms, locked_proctors = (), {}
        placement = e.placement if hasattr(e, "placement") else None  # yerleşimi yoksa hasattr False döner
        if keep_locked and placement is not None and placement.locked:
            t = slot_of(placement.date, placement.session)
            if t >= 0:
                fixed = t
                locked_rooms = tuple(r.classroom_id for r in placement.rooms.all() if r.classroom_id in room_ids)
                locked_proctors = {r.classroom_id: tuple(t.pk for t in r.proctors.all()) for r in placement.rooms.all()}
        students = frozenset(s.pk for lesson in e.lessons.all() if lesson.elective for s in lesson.students.all())
        p_exams.append(exams_solver.PExam(
            id=e.pk, name=e.title + (f" ({', '.join(c.short or c.name for c in e.classes.all())})" if e.classes.all() else ""),
            classes=tuple(c.pk for c in e.classes.all()), students=e.student_count, duration=max(1, e.duration),
            teachers=tuple(t.pk for t in e.teachers.all()), fixed=fixed, rooms_needed=e.rooms_needed,
            allowed_rooms=tuple(r.pk for r in e.allowed_rooms.all()), locked_rooms=locked_rooms,
            locked_proctors=locked_proctors, student_ids=students,
        ))
    pool = proctor_pool(period)
    blocks = proctor_blocks(period)
    unavailable = {t.pk: {slot_of(d, s) for d, s in blocks.get(t.pk, ())} - {-1} for t in pool}
    return exams_solver.Problem(
        n_days=len(dates), n_sessions=n_s, exams=p_exams,
        rooms=[exams_solver.PRoom(r.pk, str(r), exam_capacity(r, period)) for r in rooms],
        proctors=[t.pk for t in pool], unavailable=unavailable, max_per_day=max(1, period.max_per_day),
        proctors_per_room=period.proctors_per_room, time_limit=max(5, period.time_limit),
        class_names={c.pk: c.short or c.name for c in period.school.classes.all()},
        slot_names=[slot_label(d, s, period) for d in dates for s in range(n_s)],
        capacity_percent=period.capacity_percent,
    ), dates


def save_result(period, result, dates):
    n_s = len(period.session_times)
    with transaction.atomic():
        ExamPlacement.objects.filter(exam__period=period).exclude(locked=True).delete()
        ExamPlacement.objects.filter(exam__period=period, exam__excluded=True).delete()
        locked = set(ExamPlacement.objects.filter(exam__period=period, locked=True).values_list("exam_id", flat=True))
        for eid, (t0, rows) in result.placements.items():
            if eid in locked:
                continue
            placement = ExamPlacement.objects.create(exam_id=eid, date=dates[t0 // n_s], session=t0 % n_s)
            for rid, seats, teachers in rows:
                room = ExamRoom.objects.create(placement=placement, classroom_id=rid, seats=seats)
                room.proctors.set(teachers)


def run(period_id):
    """Çözüm işi (arka planda): sonucu kaydeder, durumu yazar, başlatana bildirim gönderir."""
    period = ExamPeriod.objects.select_related("school").get(pk=period_id)
    report = {}
    try:
        problem, dates = build_problem(period)
        result = exams_solver.solve(problem)
        if result.status != "failed":
            save_result(period, result, dates)
        report = {"errors": result.errors, "warnings": result.warnings, "unplaced": result.unplaced, "stats": result.stats}
        status = {"ok": ExamPeriod.OK, "partial": ExamPeriod.PARTIAL}.get(result.status, ExamPeriod.FAILED)
    except Exception as exc:  # beklenmeyen hata: kullanıcıya iletilsin
        status, report = ExamPeriod.FAILED, {"errors": [f"Beklenmeyen hata: {exc}"]}
    ExamPeriod.objects.filter(pk=period_id).update(status=status, report=report, finished_at=timezone.now())
    _notify(ExamPeriod.objects.select_related("school").get(pk=period_id))


def _notify(period):
    if not period.requested_by_id:
        return
    try:
        from django.urls import reverse

        from . import notifications
        from .models import Notification

        url = reverse("timetable:exam_results", args=[period.school_id, period.pk])
        report = period.report or {}
        if period.status == ExamPeriod.FAILED:
            notifications.send([period.requested_by_id], f"Sınav programı oluşturulamadı: {period.name}",
                               " ".join(report.get("errors", []))[:500], url, Notification.ERROR)
        elif period.status == ExamPeriod.PARTIAL:
            notifications.send([period.requested_by_id], f"Sınav programı kısmen hazır: {period.name}",
                               f"{len(report.get('warnings', []))} uyarı var.", url, Notification.WARNING)
        else:
            notifications.send([period.requested_by_id], f"Sınav programı hazır: {period.name}", str(period.school), url,
                               Notification.SUCCESS)
    except Exception:  # bildirim işi bozmasın
        pass


def _thread(period_id):
    close_old_connections()
    try:
        run(period_id)
    finally:
        connection.close()


def start(period, user=None):
    """Çözümü başlatır. Yerel kurulumda ve sunucuda web sürecinde ayrı iş parçacığında çalışır (süre sınırı
    kısa olduğundan iş kuyruğu kullanılmaz); TIMETABLE_RUN_IN_BACKGROUND=False ise hemen çalışır."""
    refresh_stale(period)
    if period.is_running:
        return False
    updated = ExamPeriod.objects.filter(pk=period.pk).exclude(status=ExamPeriod.RUNNING).update(
        status=ExamPeriod.RUNNING, started_at=timezone.now(), finished_at=None, report={},
        requested_by=user if user is not None and user.is_authenticated else None)
    if not updated:
        return False
    if not getattr(settings, "TIMETABLE_RUN_IN_BACKGROUND", True):
        run(period.pk)
    else:
        threading.Thread(target=_thread, args=(period.pk,), daemon=True, name=f"exams-{period.pk}").start()
    period.refresh_from_db()
    return True


def refresh_stale(period):
    if period.status == ExamPeriod.RUNNING and period.started_at:
        limit = datetime.timedelta(seconds=(period.time_limit or 30) + STALE_GRACE)
        if timezone.now() - period.started_at > limit:
            ExamPeriod.objects.filter(pk=period.pk, status=ExamPeriod.RUNNING).update(
                status=ExamPeriod.FAILED, finished_at=timezone.now(),
                report={"errors": ["İş yarıda kesildi (sunucu yeniden başlatılmış olabilir). Yeniden oluşturun."]})
            period.refresh_from_db()
    return period


# --- sonuçlar: okuma ve denetim -----------------------------------------------------------------

def placements(period):
    """Kayıtlı yerleşimler, sınav ve salon bilgisiyle."""
    return list(ExamPlacement.objects.filter(exam__period=period)
                .select_related("exam__subject")
                .prefetch_related("exam__classes", "exam__teachers", "rooms__classroom", "rooms__proctors")
                .order_by("date", "session", "exam__subject__name"))


def validate(period, only=None):
    """Kayıtlı programdaki kural ihlalleri: [{"level": "error"|"warn", "text", "exam"}]. only: sınav kimliği."""
    issues = []
    rows = placements(period)
    dates = set(period.dates())
    n_s = len(period.session_times)
    blocks = proctor_blocks(period)
    exempt = set(period.proctor_exempt.values_list("pk", flat=True))

    def add(level, text, *exams):
        if only is None or only in {e.pk for e in exams}:
            issues.append({"level": level, "text": text, "exam": exams[0].pk if exams else None})

    by_slot_class, by_slot_room, by_slot_teacher = {}, {}, {}
    per_day = defaultdict(list)
    for pl in rows:
        e = pl.exam
        label = slot_label(pl.date, pl.session, period)
        if e.excluded:
            add("warn", f"«{e.title}» sınav yapılmaz olarak işaretli ama programda duruyor.", e)
        if pl.date not in dates or not 0 <= pl.session < n_s or pl.session + e.duration > n_s:
            add("error", f"«{e.title}»: {label} sınav döneminin oturumları içinde değil.", e)
        if e.fixed_date and (e.fixed_date != pl.date or (e.fixed_session is not None and e.fixed_session != pl.session)):
            add("warn", f"«{e.title}» sabit tarihinde değil.", e)
        for c in e.classes.all():
            per_day[(c, pl.date)].append(e)
        cap = sum(exam_capacity(r.classroom, period) for r in pl.rooms.all())
        if not pl.rooms.all():
            add("error", f"«{e.title}» ({label}): salon atanmamış.", e)
        elif cap < e.student_count:
            add("error", f"«{e.title}» ({label}): salonların sınav kapasitesi {cap}, öğrenci {e.student_count}.", e)
        for k in range(max(1, e.duration)):
            s = pl.session + k
            for c in e.classes.all():
                other = by_slot_class.get((pl.date, s, c.pk))
                if other is not None and other.pk != e.pk:
                    add("error", f"{c.short or c.name}: «{other.title}» ile «{e.title}» aynı oturumda ({label}).", e, other)
                by_slot_class[(pl.date, s, c.pk)] = e
            for r in pl.rooms.all():
                other = by_slot_room.get((pl.date, s, r.classroom_id))
                if other is not None and other.pk != e.pk:
                    add("error", f"{r.classroom}: «{other.title}» ile «{e.title}» aynı anda aynı salonda ({label}).", e, other)
                by_slot_room[(pl.date, s, r.classroom_id)] = e
                for t in r.proctors.all():
                    other = by_slot_teacher.get((pl.date, s, t.pk))
                    if other is not None and other != (e.pk, r.classroom_id):
                        add("error", f"{t.full_name} aynı anda iki salonda gözetmen ({label}).", e)
                    by_slot_teacher[(pl.date, s, t.pk)] = (e.pk, r.classroom_id)
                    if (pl.date, s) in blocks.get(t.pk, ()):
                        add("warn", f"{t.full_name} {label} oturumunda müsait değil ama «{e.title}» sınavında gözetmen.", e)
                    if t.pk in exempt:
                        add("warn", f"{t.full_name} gözetmenlikten muaf ama «{e.title}» sınavında görevli.", e)
        for r in pl.rooms.all():
            if len(r.proctors.all()) < period.proctors_per_room:
                add("warn", f"«{e.title}» – {r.classroom}: {period.proctors_per_room} gözetmen gerekli, {len(r.proctors.all())} var.", e)
    for (c, date), exams in per_day.items():
        if len(exams) > period.max_per_day:
            add("error", f"{c.short or c.name}: {date:%d.%m.%Y} günü {len(exams)} sınav (en fazla {period.max_per_day}).", *exams)
    placed = {pl.exam_id for pl in rows}
    if only is None:
        for e in period.exams.filter(excluded=False).exclude(pk__in=placed).select_related("subject"):
            add("warn", f"«{e.title}» henüz yerleşmedi.", e)
    return issues


def slot_status(period, exam):
    """Elle taşıma için her oturumun durumu: [(tarih, oturum, etiket, sorunlar)]; sorun = sınıf çakışması ya da
    günlük sınır."""
    classes = set(exam.classes.values_list("pk", flat=True))
    busy = defaultdict(list)
    day_count = defaultdict(int)
    for pl in placements(period):
        if pl.exam_id == exam.pk:
            continue
        shared = classes & {c.pk for c in pl.exam.classes.all()}
        if not shared:
            continue
        for k in range(max(1, pl.exam.duration)):
            busy[(pl.date, pl.session + k)].append(pl.exam.title)
        day_count[pl.date] += 1
    out = []
    n_s = len(period.session_times)
    for date, s in period.slots():
        problems = []
        if s + exam.duration > n_s:
            problems.append("süre sığmıyor")
        for k in range(max(1, exam.duration)):
            problems += [f"çakışma: {t}" for t in busy.get((date, s + k), [])]
        if day_count[date] >= period.max_per_day:
            problems.append("günlük sınır dolu")
        out.append((date, s, slot_label(date, s, period), list(dict.fromkeys(problems))))
    return out


def busy_at(period, date, session, duration, skip_exam=None):
    """Bu oturumlarda dolu salonlar ve gözetmenler: ({salon: sınav}, {öğretmen: sınav})."""
    rooms, teachers = {}, {}
    wanted = {(date, session + k) for k in range(max(1, duration))}
    for pl in placements(period):
        if pl.exam_id == skip_exam:
            continue
        span = {(pl.date, pl.session + k) for k in range(max(1, pl.exam.duration))}
        if not span & wanted:
            continue
        for r in pl.rooms.all():
            rooms[r.classroom_id] = pl.exam.title
            for t in r.proctors.all():
                teachers[t.pk] = pl.exam.title
    return rooms, teachers


def auto_proctors(period, placement):
    """Bu yerleşimin salonlarına eksik gözetmenleri açgözlü atar (müsait, o anda boş, yükü az olan; önce dersin
    öğretmeni). Dönüş: atanan sayı."""
    exam = placement.exam
    _rooms, busy = busy_at(period, placement.date, placement.session, exam.duration, skip_exam=exam.pk)
    blocks = proctor_blocks(period)
    load = defaultdict(int)
    for room in ExamRoom.objects.filter(placement__exam__period=period).prefetch_related("proctors"):
        for t in room.proctors.all():
            load[t.pk] += 1
    own = set(exam.teachers.values_list("pk", flat=True))
    span = {(placement.date, placement.session + k) for k in range(max(1, exam.duration))}
    pool = [t for t in proctor_pool(period) if t.pk not in busy and not span & blocks.get(t.pk, set())]
    added = 0
    taken = {t.pk for r in placement.rooms.all() for t in r.proctors.all()}
    for room in placement.rooms.all():
        need = period.proctors_per_room - room.proctors.count()
        for t in sorted(pool, key=lambda t: (t.pk not in own, load[t.pk], t.last_name)):
            if need <= 0:
                break
            if t.pk in taken:
                continue
            room.proctors.add(t)
            taken.add(t.pk)
            load[t.pk] += 1
            need -= 1
            added += 1
    return added


def set_rooms(period, placement, room_ids):
    """Yerleşimin salonlarını değiştirir; kalan salonların gözetmenleri korunur, öğrenciler yeniden dağıtılır."""
    rooms = {r.pk: r for r in Classroom.objects.filter(school=period.school_id, pk__in=room_ids)}
    placement.rooms.exclude(classroom_id__in=rooms).delete()
    existing = set(placement.rooms.values_list("classroom_id", flat=True))
    for rid in rooms:
        if rid not in existing:
            ExamRoom.objects.create(placement=placement, classroom=rooms[rid])
    ordered = sorted(placement.rooms.select_related("classroom"), key=lambda r: -exam_capacity(r.classroom, period))
    seats = exams_solver.seat_split(placement.exam.student_count, [exam_capacity(r.classroom, period) for r in ordered])
    for r, n in zip(ordered, seats):
        if r.seats != n:
            r.seats = n
            r.save(update_fields=["seats"])


# --- görünümler için tablolar -------------------------------------------------------------------

def calendar(period, rows=None):
    """Takvim: [{"date", "day", "cells": [[yerleşim, ...] her oturum için]}]."""
    rows = placements(period) if rows is None else rows
    n_s = len(period.session_times)
    by = defaultdict(list)
    for pl in rows:
        by[(pl.date, pl.session)].append(pl)
    dates = period.dates()
    extra = sorted({pl.date for pl in rows} - set(dates))
    return [{"date": d, "day": DAY_NAMES[d.weekday()], "cells": [by.get((d, s), []) for s in range(n_s)]}
            for d in sorted(dates + extra)]


def class_rooms(pl, sizes):
    """Ortak sınavda her sınıfın oturduğu salonlar: sınıflar sırayla, öğrenci sayısı kadar salonlara doldurulur.
    Dönüş: {sınıf kimliği: [ExamRoom, ...]}."""
    rooms = [r for r in pl.rooms.all()]
    if not rooms:
        return {}
    classes = sorted(pl.exam.classes.all(), key=lambda c: (c.grade or 0, c.sort_key, c.name))
    out, i, left = {}, 0, rooms[0].seats
    for c in classes:
        need, used = sizes.get(c.pk, 0), []
        while need > 0 and i < len(rooms):
            if left <= 0:
                i += 1
                left = rooms[i].seats if i < len(rooms) else 0
                continue
            take = min(need, left)
            used.append(rooms[i])
            need -= take
            left -= take
        out[c.pk] = list(dict.fromkeys(used)) or [rooms[min(i, len(rooms) - 1)]]
    return out


def by_class(period, rows=None):
    """[(sınıf, [(yerleşim, sınıfın salonları), ...])]."""
    rows = placements(period) if rows is None else rows
    sizes = class_sizes(period.school)
    out = defaultdict(list)
    for pl in rows:
        mapping = class_rooms(pl, sizes)
        for c in pl.exam.classes.all():
            out[c].append((pl, mapping.get(c.pk, [])))
    return sorted(out.items(), key=lambda kv: (kv[0].grade or 0, kv[0].sort_key, kv[0].name))


def by_teacher(period, rows=None):
    """Gözetmenlik listesi: [(öğretmen, [(yerleşim, salon), ...])] çoktan aza."""
    rows = placements(period) if rows is None else rows
    out = defaultdict(list)
    for pl in rows:
        for r in pl.rooms.all():
            for t in r.proctors.all():
                out[t].append((pl, r))
    return sorted(out.items(), key=lambda kv: (-len(kv[1]), kv[0].last_name, kv[0].first_name))


def by_room(period, rows=None):
    rows = placements(period) if rows is None else rows
    out = defaultdict(list)
    for pl in rows:
        for r in pl.rooms.all():
            out[r.classroom].append((pl, r))
    return sorted(out.items(), key=lambda kv: kv[0].name.casefold())


def teacher_loads(period):
    loads = defaultdict(int)
    for room in ExamRoom.objects.filter(placement__exam__period=period).prefetch_related("proctors"):
        for t in room.proctors.all():
            loads[t.pk] += 1
    return loads


def parse_dates(text):
    """"03.11.2026, 2026-11-04" → ["2026-11-03", "2026-11-04"] (geçersizler atlanır)."""
    out = []
    for part in str(text or "").replace(";", ",").replace("\n", ",").split(","):
        part = part.strip()
        if not part:
            continue
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y"):
            try:
                out.append(datetime.datetime.strptime(part, fmt).date().isoformat())
                break
            except ValueError:
                continue
    return sorted(set(out))


def parse_sessions(text):
    out = []
    for part in str(text or "").replace(";", ",").replace(" ", ",").split(","):
        t = parse_time(part) if part.strip() else None
        if t is not None:
            out.append(f"{t:%H:%M}")
    return sorted(set(out))


def teacher_of(period, pk):
    return Teacher.objects.filter(school=period.school_id, pk=pk).first()
