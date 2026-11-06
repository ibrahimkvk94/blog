"""Etkinlik ve telafi: haftalık programın üstüne tek seferlik kayıtlar (Event).

- Derslik / etkinlik rezervasyonu: toplantı, seminer, sınav gibi işler için bir tarihte derslik ve kişiler ayrılır;
  o saatin dersleri ve diğer etkinliklerle çakışma denetlenir, boş derslikler listelenir.
- Telafi dersi: kaçan bir ders için öğretmenin, katılımcıların ve bir dersliğin boş olduğu saatler önerilir.
  Katılımcılar karma olabilir: birden çok dersin (ör. aynı dersin iki kısmı) sınıfları ve grupları, ek sınıflar ve
  numarasıyla tek tek eklenen öğrenciler aynı oturumda toplanır.

Bir tarihte "dolu" sayılanlar: yayındaki programın o hafta günündeki kartları (öğretmen, sınıf / grup, derslik ve
dersi alan öğrenciler), o günün vekâletleri (vekil), devamsızlıkları (izin dahil), kalıcı müsaitlik yasakları ve o
günün diğer etkinlikleri. Bölünmüş sınıfta aynı bölünmenin başka grubunun dersi bu grubu bağlamaz; başka bölünmenin
grubu (öğrencileri bilinmediği için) bağlar.
"""

import datetime
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import (
    DAY_NAMES,
    Absence,
    Availability,
    Classroom,
    Event,
    Group,
    Lesson,
    School,
    SchoolClass,
    Student,
    Substitution,
    Teacher,
)
from .teacher_calendar import timetable_for

SEARCH_DAYS = 14  # telafi aramasının varsayılan aralığı (gün)
PER_DAY = 3  # öneri listesinde bir günden en çok kaç seçenek
LIMIT = 15  # öneri listesinin uzunluğu


@dataclass
class Spec:
    """Bir oturumun katılımcıları ve derslik ihtiyacı."""

    teachers: set = field(default_factory=set)
    classes: set = field(default_factory=set)
    groups: set = field(default_factory=set)
    students: set = field(default_factory=set)
    rooms: list = field(default_factory=list)  # tercih edilen derslikler (sırayla)
    size: int | None = None  # öğrenci sayısı (derslik kapasitesi için); bilinmiyorsa None
    need_room: bool = True


class Calendar:
    """Okulun haftalık doluluğu bir kez kurulur; tarihe özel olanlar (vekâlet, devamsızlık, etkinlik) gün gün eklenir."""

    def __init__(self, school, timetable=None):
        self.school = school
        self.timetable = timetable if timetable is not None else timetable_for(school)
        self.periods = list(school.periods.all())
        self.days = school.days_per_week
        self.teacher_names = {t.id: t.full_name for t in school.teachers.all()}
        self.classes = {c.id: c for c in school.classes.all()}
        self.groups = {g.id: g for g in Group.objects.filter(division__school_class__school=school).select_related("division")}
        self.rooms = {r.id: r for r in school.classrooms.all()}
        self.week_teacher = defaultdict(list)  # (öğretmen, gün, saat) -> [ders]
        self.week_room = defaultdict(list)
        self.week_class = defaultdict(list)  # (sınıf, gün, saat) -> [(ders, grup kümesi | None)]
        self.lesson_cells = defaultdict(list)  # ders -> [(gün, saat)]
        self.lesson_label = {}
        if self.timetable is not None:
            cards = (self.timetable.cards.filter(day__isnull=False).select_related("lesson__subject")
                     .prefetch_related("lesson__teachers", "lesson__classes", "lesson__groups__division"))
            for card in cards:
                lesson = card.lesson
                label = lesson.subject.short or lesson.subject.name
                self.lesson_label[lesson.id] = label
                groups_of = defaultdict(set)
                for g in lesson.groups.all():
                    groups_of[g.division.school_class_id].add(g.id)
                for i in range(card.length):
                    cell = (card.day, card.period + i)
                    self.lesson_cells[lesson.id].append(cell)
                    for t in lesson.teachers.all():
                        self.week_teacher[(t.id, *cell)].append(label)
                    for r in card.room_ids:
                        self.week_room[(r, *cell)].append(label)
                    for c in lesson.classes.all():
                        self.week_class[(c.id, *cell)].append((label, frozenset(groups_of[c.id]) or None))
        self.forbidden = set()  # (tür, kimlik, gün, saat); okul geneli: ("school", None, gün, saat)
        for a in Availability.objects.filter(school=self.school, state=Availability.NO, subject__isnull=True, lesson__isnull=True):
            if a.teacher_id:
                self.forbidden.add(("teacher", a.teacher_id, a.day, a.period))
            elif a.school_class_id:
                self.forbidden.add(("class", a.school_class_id, a.day, a.period))
            elif a.classroom_id:
                self.forbidden.add(("room", a.classroom_id, a.day, a.period))
            else:
                self.forbidden.add(("school", None, a.day, a.period))
        self._student_lessons = None
        self._student_info = {}
        self._days = {}

    # --- öğrenciler ----------------------------------------------------------------------------

    def student_lessons(self, ids):
        """{öğrenci: girdiği ders kimlikleri}; yalnızca istenen öğrenciler için hesaplanır."""
        from .students import attendance

        missing = [i for i in ids if self._student_lessons is None or i not in self._student_lessons]
        if missing:
            students = list(self.school.students.filter(pk__in=missing).prefetch_related("groups"))
            found = attendance(self.school, students)
            self._student_lessons = {**(self._student_lessons or {}), **found}
            for s in students:
                self._student_info[s.id] = (s.full_name, s.school_class_id, {g.id for g in s.groups.all()})
        return {i: self._student_lessons.get(i, set()) for i in ids}

    # --- tarihe özel doluluk -------------------------------------------------------------------

    def _day(self, date, exclude=None):
        key = (date, exclude)
        if key in self._days:
            return self._days[key]
        day = {"absent": {}, "teacher": defaultdict(list), "room": defaultdict(list), "class": defaultdict(list),
               "student": defaultdict(list)}
        for a in Absence.objects.filter(school=self.school, date=date):
            day["absent"][a.teacher_id] = a
        for sub in Substitution.objects.filter(absence__school=self.school, absence__date=date, substitute__isnull=False):
            day["teacher"][(sub.substitute_id, sub.period)].append("vekâlet")
        events = Event.objects.filter(school=self.school, date=date).prefetch_related("teachers", "classrooms", "classes",
                                                                                      "groups__division", "students")
        for ev in events:
            if ev.pk == exclude:
                continue
            label = ev.title
            for p in ev.periods:
                for t in ev.teachers.all():
                    day["teacher"][(t.id, p)].append(label)
                for r in ev.classrooms.all():
                    day["room"][(r.id, p)].append(label)
                for c in ev.classes.all():
                    day["class"][(c.id, p)].append((label, None))
                for g in ev.groups.all():
                    day["class"][(g.division.school_class_id, p)].append((label, frozenset([g.id])))
                for s in ev.students.all():
                    day["student"][(s.id, p)].append(label)
        self._days[key] = day
        return day

    def _class_entries(self, class_id, weekday, period, day):
        return self.week_class.get((class_id, weekday, period), []) + day["class"].get((class_id, period), [])

    def _group_busy(self, group_id, entries):
        """Gruba dokunan ilk kayıt: tüm sınıfın dersi, bu grubun dersi ya da başka bölünmenin grubu."""
        division = self.groups[group_id].division_id
        for label, groups in entries:
            if groups is None or group_id in groups or any(self.groups[g].division_id != division for g in groups if g in self.groups):
                return label
        return None

    def conflicts(self, date, periods, spec, exclude=None, rooms=(), weekend=False):
        """Çakışma nedenleri (okunur metinler); boşsa oturum bu saatlerde yapılabilir. weekend: okulun ders günü
        olmayan gün (ör. cumartesi telafisi) de kabul edilir; o gün haftalık ders yoktur."""
        weekday = date.weekday()
        if weekday >= self.days and not weekend:
            return ["Bu tarih okulun ders günü değil."]
        if periods and periods[-1] >= len(self.periods):
            return ["Seçilen süre günün son ders saatini aşıyor."]
        day = self._day(date, exclude)
        out = []
        student_lessons = self.student_lessons(spec.students) if spec.students else {}
        for p in periods:
            name = f"{p + 1}. saat"
            if ("school", None, weekday, p) in self.forbidden:
                out.append(f"{name}: okul geneli ders yapılmayan saat")
            for t in spec.teachers:
                who = self.teacher_names.get(t, "öğretmen")
                absent = day["absent"].get(t)
                busy = self.week_teacher.get((t, weekday, p), []) + day["teacher"].get((t, p), [])
                if absent and absent.covers(p):
                    out.append(f"{name}: {who} o gün devamsız ({absent.reason or 'izin'})")
                elif busy:
                    out.append(f"{name}: {who} – {', '.join(busy)}")
                if ("teacher", t, weekday, p) in self.forbidden:
                    out.append(f"{name}: {who} bu saatte müsait değil")
            for c in spec.classes:
                cls = self.classes.get(c)
                entries = self._class_entries(c, weekday, p, day)
                if entries:
                    out.append(f"{name}: {cls.short or cls.name if cls else 'sınıf'} – {', '.join(e[0] for e in entries)}")
                if ("class", c, weekday, p) in self.forbidden:
                    out.append(f"{name}: {cls.short or cls.name if cls else 'sınıf'} bu saatte müsait değil")
            for g in spec.groups:
                group = self.groups.get(g)
                if group is None or group.division.school_class_id in spec.classes:
                    continue
                label = self._group_busy(g, self._class_entries(group.division.school_class_id, weekday, p, day))
                if label:
                    out.append(f"{name}: {group} – {label}")
            for s, lessons in student_lessons.items():
                full, class_id, groups = self._student_info.get(s, ("öğrenci", None, set()))
                if class_id in spec.classes or groups & spec.groups:
                    continue  # sınıfı / grubu zaten denetlendi
                busy = [self.lesson_label.get(lid, "ders") for lid in lessons if (weekday, p) in self.lesson_cells.get(lid, ())]
                busy += day["student"].get((s, p), [])
                if busy:
                    out.append(f"{name}: {full} – {', '.join(busy)}")
            for r in rooms:
                room = self.rooms.get(r)
                busy = self.week_room.get((r, weekday, p), []) + day["room"].get((r, p), [])
                if busy:
                    out.append(f"{name}: {room.name if room else 'derslik'} dolu – {', '.join(busy)}")
                if ("room", r, weekday, p) in self.forbidden:
                    out.append(f"{name}: {room.name if room else 'derslik'} bu saatte kullanılamaz")
        return list(dict.fromkeys(out))

    def free_rooms(self, date, periods, size=None, prefer=()):
        """Bu saatlerde boş derslikler: önce tercih edilenler, sonra kapasitesi ihtiyaca en yakın olanlar."""
        weekday = date.weekday()
        day = self._day(date)
        free = []
        for room in self.rooms.values():
            if any(self.week_room.get((room.id, weekday, p)) or day["room"].get((room.id, p))
                   or ("room", room.id, weekday, p) in self.forbidden for p in periods):
                continue
            if size and room.capacity is not None and room.capacity < size:
                continue
            free.append(room)
        order = {r: i for i, r in enumerate(prefer)}
        free.sort(key=lambda r: (order.get(r.id, len(order)), (r.capacity or 10_000) - (size or 0), r.name))
        return free

    def times(self, date, periods):
        if not periods or periods[-1] >= len(self.periods):
            return ""
        start, _ = self.periods[periods[0]].times(date.weekday())
        _, end = self.periods[periods[-1]].times(date.weekday())
        return f"{start:%H:%M}–{end:%H:%M}" if start and end else ""

    def suggest(self, spec, length, start, end, limit=LIMIT, per_day=PER_DAY, weekend=False, blockers=None):
        """[start, end] arasında oturumun yapılabileceği saatler; her biri {"date", "period", "rooms", "note", ...}.
        Aynı günde öğretmen zaten okuldaysa ve oturum öğretmenin / sınıfın dersine bitişikse (yeni boşluk açmıyorsa)
        önce gelir. weekend: ders günü olmayan günler de aranır (önce hafta içi). blockers (Counter) verilirse
        reddedilen saatlerin nedenleri sayılır ("kim: ne" → kaç saat)."""
        out = []
        date = start
        while date <= end and len(out) < limit:
            weekday = date.weekday()
            if weekday < self.days or weekend:
                day_options = []
                for first in range(0, len(self.periods) - length + 1):
                    periods = list(range(first, first + length))
                    problems = self.conflicts(date, periods, spec, weekend=weekend)
                    if problems:
                        if blockers is not None:
                            for text in problems:
                                who = text.split(": ", 1)[-1].split(" – ")[0]
                                blockers[who] += 1
                        continue
                    rooms = self.free_rooms(date, periods, spec.size, spec.rooms) if spec.need_room else []
                    if spec.need_room and not rooms:
                        if blockers is not None:
                            blockers[f"{spec.size or ''} kişilik boş derslik yok".strip()] += 1
                        continue
                    day = self._day(date)
                    present = any(self.week_teacher.get((t, weekday, p)) or day["teacher"].get((t, p))
                                  for t in spec.teachers for p in range(len(self.periods)))
                    edges = [first - 1, first + length]
                    touching = sum(1 for p in edges if 0 <= p < len(self.periods) and (
                        any(self.week_teacher.get((t, weekday, p)) for t in spec.teachers)
                        or any(self._class_entries(c, weekday, p, day) for c in spec.classes)))
                    notes = []
                    if spec.teachers:
                        notes.append("öğretmen o gün okulda" if present else "öğretmenin o gün başka dersi yok")
                    if touching:
                        notes.append("derse bitişik, boşluk açmaz")
                    day_options.append({
                        "date": date, "day_name": DAY_NAMES[weekday], "period": first, "periods": periods,
                        "label": f"{first + 1}. saat" if length == 1 else f"{first + 1}–{first + length}. saat",
                        "times": self.times(date, periods), "rooms": rooms[:8], "note": ", ".join(notes),
                        "score": (2 if present else 0) + touching - (10 if weekday >= self.days else 0),
                    })
                day_options.sort(key=lambda o: (-o["score"], o["period"]))
                out.extend(day_options[:per_day])
            date += datetime.timedelta(days=1)
        return out[:limit]


# --- katılımcılar ----------------------------------------------------------------------------

def _ids(values):
    return [int(v) for v in values if str(v).isdigit()]


def makeup_spec(school, lessons, extra_classes=(), extra_groups=(), extra_students=(), teachers=None):
    """Telafinin katılımcıları: derslerin sınıfları / grupları / kayıtlı öğrencileri (seçmeli) + ekler.
    teachers verilmezse derslerin öğretmenleri."""
    spec = Spec()
    rooms = []
    for lesson in lessons:
        spec.teachers |= {t.id for t in lesson.teachers.all()} if teachers is None else set()
        grouped = defaultdict(set)
        for g in lesson.groups.all():
            grouped[g.division.school_class_id].add(g.id)
        for c in lesson.classes.all():
            if grouped.get(c.id):
                spec.groups |= grouped[c.id]
            else:
                spec.classes.add(c.id)
            if c.home_classroom_id:
                rooms.append(c.home_classroom_id)
        if lesson.elective:
            spec.students |= {s.id for s in lesson.students.all()}
        rooms = [r.id for r in lesson.classrooms.all()] + rooms
    if teachers is not None:
        spec.teachers = set(teachers)
    spec.classes |= set(extra_classes)
    spec.groups |= set(extra_groups)
    spec.students |= set(extra_students)
    spec.rooms = list(dict.fromkeys(rooms))
    spec.size = _size(school, spec)
    return spec


def _size(school, spec):
    """Katılımcı öğrenci sayısı (bilinmeyen sınıf / grup varsa None)."""
    total = 0
    classes = {c.id: c for c in school.classes.filter(pk__in=spec.classes)}
    for c in classes.values():
        count = c.student_count or c.students.count()
        if not count:
            return None
        total += count
    groups = Group.objects.filter(pk__in=spec.groups).select_related("division")
    for g in groups:
        if g.division.school_class_id in spec.classes:
            continue
        count = g.student_count or g.students.count()
        if not count:
            return None
        total += count
    covered_groups = set(spec.groups)
    for s in Student.objects.filter(pk__in=spec.students).prefetch_related("groups"):
        if s.school_class_id in spec.classes or {g.id for g in s.groups.all()} & covered_groups:
            continue
        total += 1
    return total or None


def parse_students(school, text):
    """Numara listesinden öğrenciler (satır, virgül ya da boşlukla ayrılmış). Dönüş: (kimlikler, bulunamayanlar)."""
    numbers = [n for n in re.split(r"[\s,;]+", text or "") if n]
    found = dict(school.students.filter(number__in=numbers).values_list("number", "id"))
    return [found[n] for n in numbers if n in found], [n for n in numbers if n not in found]


def describe(event):
    """Etkinliğin katılımcıları tek satırda."""
    parts = [c.short or c.name for c in event.classes.all()]
    parts += [str(g) for g in event.groups.all()]
    students = list(event.students.all())
    if students:
        parts.append(f"{len(students)} öğrenci" if len(students) > 3 else ", ".join(s.full_name for s in students))
    return ", ".join(parts)


def _notify_teachers(event, request):
    from . import notifications

    users = [t.user_id for t in event.teachers.all() if t.user_id]
    if users:
        notifications.send(users, f"{event.get_kind_display()}: {event.title}",
                           f"{event.date:%d.%m.%Y} {event.periods_label}"
                           + (f", {', '.join(r.name for r in event.classrooms.all())}" if event.classrooms.exists() else ""),
                           url=reverse("timetable:my_timetable"), sender=request.user)


def create(school, user, *, kind, title, date, period, length, spec, rooms, lessons=(), missed_date=None, note=""):
    with transaction.atomic():
        event = Event.objects.create(school=school, kind=kind, title=title[:200], date=date, period=period, length=length,
                                     missed_date=missed_date, note=note, created_by=user if user.is_authenticated else None)
        event.teachers.set(spec.teachers)
        event.classes.set(spec.classes)
        event.groups.set(spec.groups)
        event.students.set(spec.students)
        event.classrooms.set(rooms)
        event.lessons.set(lessons)
    return event


# --- sayfa -------------------------------------------------------------------------------------

def _date(value, default):
    try:
        return datetime.date.fromisoformat(value or "")
    except ValueError:
        return default


def _lesson_options(school):
    lessons = (school.lessons.select_related("subject").prefetch_related("classes", "groups", "teachers")
               .order_by("subject__name", "id"))
    out = []
    for lesson in lessons:
        who = ", ".join(c.short or c.name for c in lesson.classes.all()) or ("seçmeli" if lesson.elective else "")
        groups = ", ".join(g.name for g in lesson.groups.all())
        teachers = ", ".join(t.full_name for t in lesson.teachers.all())
        out.append((lesson.id, f"{lesson.subject.short or lesson.subject.name} – {who}{f' ({groups})' if groups else ''}"
                               f"{f' · {teachers}' if teachers else ''}"))
    return out


def events_page(request, pk):
    from .views import _nav

    school = get_object_or_404(School, pk=pk)
    today = timezone.localdate()
    data = request.POST if request.method == "POST" else request.GET
    action = data.get("action")
    calendar = Calendar(school)
    makeup = {"lessons": _ids(data.getlist("ders")), "classes": _ids(data.getlist("sinif")),
              "groups": _ids(data.getlist("grup")), "students_text": data.get("ogrenciler", ""),
              "teacher": data.get("ogretmen", ""), "length": data.get("sure", ""),
              "missed": data.get("telafi_tarihi", ""), "from": data.get("ilk", ""), "to": data.get("son", ""),
              "title": data.get("baslik", ""), "weekend": data.get("hafta_sonu") == "1"}
    reserve = {"title": data.get("r_baslik", ""), "date": data.get("r_tarih", ""), "period": data.get("r_saat", ""),
               "length": data.get("r_sure", "1"), "rooms": _ids(data.getlist("r_derslik")),
               "teachers": _ids(data.getlist("r_ogretmen")), "classes": _ids(data.getlist("r_sinif")),
               "note": data.get("r_not", "")}
    suggestions, free_rooms, reserve_conflicts, missing = None, None, [], []

    def build_makeup():
        lessons = list(school.lessons.filter(pk__in=makeup["lessons"]).prefetch_related(
            "teachers", "classes", "groups__division", "students", "classrooms").select_related("subject"))
        students, missing_numbers = parse_students(school, makeup["students_text"])
        teacher = int(makeup["teacher"]) if makeup["teacher"].isdigit() else None
        spec = makeup_spec(school, lessons, makeup["classes"], makeup["groups"], students,
                           teachers=[teacher] if teacher else None)
        length = int(makeup["length"]) if makeup["length"].isdigit() else max([l.card_length for l in lessons] or [1])
        return lessons, spec, max(1, length), missing_numbers

    if request.method == "POST" and action == "delete":
        Event.objects.filter(pk=data.get("etkinlik"), school=school).delete()
        messages.info(request, "Kayıt silindi.")
        return redirect(request.get_full_path())
    if action in ("suggest", "save_makeup"):
        lessons, spec, length, missing = build_makeup()
        if not (spec.teachers or spec.classes or spec.groups or spec.students):
            messages.error(request, "Telafi için en az bir ders, sınıf ya da öğrenci seçin.")
        elif action == "suggest":
            first = _date(makeup["from"], today + datetime.timedelta(days=1))
            last = _date(makeup["to"], first + datetime.timedelta(days=SEARCH_DAYS))
            blockers = Counter()
            suggestions = calendar.suggest(spec, length, first, min(last, first + datetime.timedelta(days=62)),
                                           weekend=makeup["weekend"], blockers=blockers)
            if not suggestions:
                reasons = ", ".join(f"{who} ({n} saat)" for who, n in blockers.most_common(4))
                messages.warning(request, "Bu aralıkta herkesin ve bir dersliğin boş olduğu saat bulunamadı"
                                 + (f". En sık engel: {reasons}" if reasons else "") + ". Aralığı genişletin, "
                                 + ("" if makeup["weekend"] else "hafta sonunu da arayın, ")
                                 + "süreyi kısaltın ya da katılımcıları bölün.")
        elif request.method == "POST":
            date = _date(data.get("tarih"), None)
            period = int(data.get("saat")) if (data.get("saat") or "").isdigit() else None
            room = _ids([data.get("derslik", "")])
            periods = list(range(period, period + length)) if period is not None else []
            problems = (calendar.conflicts(date, periods, spec, rooms=room, weekend=makeup["weekend"]) if date and periods
                        else ["Tarih ya da saat eksik."])
            if problems:
                messages.error(request, "Bu saat artık uygun değil: " + "; ".join(problems[:4]))
            else:
                names = ", ".join(dict.fromkeys(l.subject.short or l.subject.name for l in lessons))
                event = create(school, request.user, kind=Event.MAKEUP, title=makeup["title"] or f"Telafi: {names or 'ders'}",
                               date=date, period=period, length=length, spec=spec, rooms=room, lessons=lessons,
                               missed_date=_date(makeup["missed"], None), note=data.get("not", ""))
                _notify_teachers(event, request)
                messages.success(request, f"Telafi kaydedildi: {event.date:%d.%m.%Y} {event.periods_label}.")
                return redirect(reverse("timetable:events", args=[school.pk]) + f"?baslangic={date.isoformat()}")
    if action in ("free_rooms", "reserve"):
        date = _date(reserve["date"], None)
        period = int(reserve["period"]) if reserve["period"].isdigit() else None
        length = int(reserve["length"]) if reserve["length"].isdigit() and int(reserve["length"]) > 0 else 1
        periods = list(range(period, period + length)) if period is not None else []
        spec = Spec(teachers=set(reserve["teachers"]), classes=set(reserve["classes"]), need_room=False)
        if date is None or not periods:
            messages.error(request, "Tarih ve başlangıç saati seçin.")
        elif action == "free_rooms":
            free_rooms = calendar.free_rooms(date, periods)
        elif request.method == "POST":
            reserve_conflicts = calendar.conflicts(date, periods, spec, rooms=reserve["rooms"])
            if not reserve["title"].strip():
                messages.error(request, "Başlık yazın.")
            elif reserve_conflicts and data.get("zorla") != "1":
                messages.error(request, "Çakışma var; aşağıdaki listeye bakın. Yine de kaydetmek için kutuyu işaretleyin.")
            else:
                event = create(school, request.user, kind=Event.EVENT, title=reserve["title"].strip(), date=date,
                               period=period, length=length, spec=spec, rooms=reserve["rooms"], note=reserve["note"])
                _notify_teachers(event, request)
                messages.success(request, f"Kaydedildi: {event.title}, {event.date:%d.%m.%Y} {event.periods_label}.")
                return redirect(reverse("timetable:events", args=[school.pk]) + f"?baslangic={date.isoformat()}")

    start = _date(request.GET.get("baslangic"), today)
    end = _date(request.GET.get("bitis"), start + datetime.timedelta(days=30))
    events = list(school.events.filter(date__gte=start, date__lte=end)
                  .prefetch_related("teachers", "classes", "groups__division__school_class", "students", "classrooms",
                                    "lessons__subject"))
    rows = [{"event": e, "who": describe(e), "times": calendar.times(e.date, list(e.periods)),
             "day_name": DAY_NAMES[e.date.weekday()], "teachers": ", ".join(t.full_name for t in e.teachers.all()),
             "rooms": ", ".join(r.name for r in e.classrooms.all())} for e in events]
    return render(request, "timetable/events.html", _nav(
        school, "etkinlik", timetable=calendar.timetable, rows=rows, start=start, end=end, today=today,
        lesson_options=_lesson_options(school), classes=list(school.classes.all()),
        groups=list(Group.objects.filter(division__school_class__school=school).select_related("division__school_class")),
        teachers=sorted(school.teachers.all(), key=lambda t: t.full_name), rooms=list(school.classrooms.all()),
        periods=calendar.periods, makeup=makeup, reserve=reserve, suggestions=suggestions, free_rooms=free_rooms,
        reserve_conflicts=reserve_conflicts, missing_students=missing,
        default_from=today + datetime.timedelta(days=1), default_to=today + datetime.timedelta(days=1 + SEARCH_DAYS),
    ))
