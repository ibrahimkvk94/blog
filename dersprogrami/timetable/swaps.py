"""Kısım değişikliği: bir öğretmen belirli saatlerde gelemiyorsa ve o saatteki dersi kaydırılamıyorsa,
aynı dersi başka bir kısımda okutan öğretmenle kısımlar değiştirilir.

Ör. Matematik'e Mehmet 2. kısımda, Ahmet 3. kısımda giriyor; Mehmet perşembe gelemiyor. Ahmet 2. kısımın
perşembe dersine (o saatte boşsa) girer, Mehmet de 3. kısımın derslerini (onun saatlerinde boşsa) alır.
Kartların yeri değişmez; yalnızca iki dersin öğretmenleri yer değiştirir (ders verisi değişir, programın
tüm sürümlerinde geçerlidir).

Ön eleme hızlıdır (dolu saat ve müsaitlik); kalan adaylar değişiklik geçici olarak veritabanına yazılıp
problem yeniden kurularak doğrulanır, sonra geri alınır. Yeni kesin kural ihlali çıkaran öneri gösterilmez.
"""

from collections import defaultdict

from django.db import transaction

from .models import Availability, Lesson, Teacher
from .refs import DAY_SHORT

VERIFY_LIMIT = 8  # yeniden kurularak doğrulanan en fazla aday


class _Rollback(Exception):
    pass


def _cells(card):
    return {(card.day, card.period + i) for i in range(card.length)}


def _hours_text(cells):
    by_day = defaultdict(list)
    for d, p in sorted(cells):
        by_day[d].append(str(p + 1))
    return ", ".join(f"{DAY_SHORT[d]} {'-'.join(ps)}" for d, ps in sorted(by_day.items()))


def _gaps_days(cells):
    by_day = defaultdict(set)
    for d, p in cells:
        by_day[d].add(p)
    return sum(max(p) - min(p) + 1 - len(p) for p in by_day.values()), len(by_day)


def _hard(timetable, teacher_id, closed, swaps=()):
    """Kapanan saatler (ve değişimler) geçici yazılmışken programdaki kesin ihlaller; sonra geri alınır."""
    from .problem_cache import invalidate
    from .services import placements_of
    from .solver.builder import build_problem
    from .solver.validate import validate

    school = timetable.school
    result = set()
    try:
        with transaction.atomic():
            for d, p in closed:
                Availability.objects.filter(school=school, teacher_id=teacher_id, day=d, period=p).delete()
                Availability.objects.create(school=school, teacher_id=teacher_id, day=d, period=p, state=Availability.NO)
            for s in swaps:
                _swap(s)
            problem = build_problem(school, timetable=timetable)
            result = {v.message for v in validate(problem, placements_of(problem, timetable))[0] if v.level == "hard"}
            raise _Rollback
    except _Rollback:
        pass
    invalidate()
    return result


def _swap(s):
    l1, l2 = Lesson.objects.get(pk=s["l1"]), Lesson.objects.get(pk=s["l2"])
    l1.teachers.remove(s["m"])
    l1.teachers.add(s["a"])
    l2.teachers.remove(s["a"])
    l2.teachers.add(s["m"])


def find(timetable, teacher_id, day, periods):
    """Öneriler: [{"swaps": [...], "resolved": çözülen ders, "total": kapanan saate düşen ders}], en iyisi önce."""
    school = timetable.school
    closed = {(day, p) for p in periods}
    cards = list(timetable.cards.filter(day__isnull=False).select_related("lesson__subject")
                 .prefetch_related("lesson__teachers", "lesson__classes"))
    busy = defaultdict(set)          # öğretmen → dolu hücreler
    lesson_cells = defaultdict(set)  # ders → hücreler
    lessons = {}
    for card in cards:
        cells = _cells(card)
        lesson_cells[card.lesson_id] |= cells
        lessons[card.lesson_id] = card.lesson
        for t in card.lesson.teachers.all():
            busy[t.id] |= cells
    blocked = defaultdict(set)
    school_closed = set()
    for t_id, d, p in Availability.objects.filter(school=school, state=Availability.NO).filter(
            school_class__isnull=True, classroom__isnull=True, subject__isnull=True, lesson__isnull=True).values_list("teacher_id", "day", "period"):
        (blocked[t_id] if t_id else school_closed).add((d, p))
    blocked[teacher_id] |= closed
    affected = [l for l_id, l in lessons.items() if lesson_cells[l_id] & closed and teacher_id in {t.id for t in l.teachers.all()}]
    if not affected:
        return []
    teachers = {t.id: t for t in school.teachers.prefetch_related("subjects")}
    by_subject = defaultdict(list)
    for l_id, lesson in lessons.items():
        by_subject[lesson.subject_id].append(lesson)

    def classes(lesson):
        return ", ".join(c.short or c.name for c in lesson.classes.all())

    candidates = []
    for l1 in affected:
        c1 = lesson_cells[l1.id]
        for l2 in by_subject[l1.subject_id]:
            t2 = {t.id for t in l2.teachers.all()}
            if l2.id == l1.id or teacher_id in t2:
                continue
            c2 = lesson_cells[l2.id]
            if c2 & (blocked[teacher_id] | closed) or (busy[teacher_id] - c1) & c2:
                continue  # öğretmen yeni kısmın saatlerinde dolu ya da gelemiyor
            for a in t2:
                if (busy[a] - c2) & c1 or c1 & blocked[a]:
                    continue  # diğer öğretmen bu kısmın saatlerinde dolu ya da gelemiyor
                m_before, a_before = busy[teacher_id], busy[a]
                m_after, a_after = (m_before - c1) | c2, (a_before - c2) | c1
                other = teachers.get(a)
                gm, ga = (_gaps_days(m_before), _gaps_days(m_after)), (_gaps_days(a_before), _gaps_days(a_after))
                candidates.append({
                    "l1": l1.id, "l2": l2.id, "m": teacher_id, "a": a,
                    "subject": l1.subject.short or l1.subject.name, "subject_name": l1.subject.name,
                    "class1": classes(l1), "class2": classes(l2),
                    "teacher": teachers[teacher_id].full_name, "other": other.full_name if other else "?",
                    "hours1": _hours_text(c1), "hours2": _hours_text(c2),
                    "load": [len(c1), len(c2)],
                    # None: öğretmenin branş listesi boş (bilinmiyor); False: liste var ama bu ders yok
                    "branch": None if not (other and other.subjects.all()) else l1.subject in other.subjects.all(),
                    "gaps": {"m": [gm[0][0], gm[1][0]], "a": [ga[0][0], ga[1][0]]},
                    "days": {"m": [gm[0][1], gm[1][1]], "a": [ga[0][1], ga[1][1]]},
                })
    # Yük farkı az, branşı uyan, boşluğu artırmayan önce
    candidates.sort(key=lambda s: (abs(s["load"][0] - s["load"][1]), s["branch"] is False,
                                   s["gaps"]["m"][1] + s["gaps"]["a"][1] - s["gaps"]["m"][0] - s["gaps"]["a"][0]))
    proposals = []
    baseline = _hard(timetable, teacher_id, closed) if candidates else set()  # yalnızca kapanan saatlerle
    for s in candidates[:VERIFY_LIMIT]:
        if not _hard(timetable, teacher_id, closed, [s]) - baseline:
            proposals.append({"swaps": [s], "resolved": 1, "total": len(affected)})
    # Birden çok ders kapanan saatlere düşüyorsa: her ders için birer değişim birlikte
    if len(affected) > 1 and proposals:
        chosen, used = [], set()
        for l1 in affected:
            pick = next((p["swaps"][0] for p in proposals if p["swaps"][0]["l1"] == l1.id
                         and not {p["swaps"][0]["l2"], p["swaps"][0]["a"]} & used), None)
            if pick:
                chosen.append(pick)
                used |= {pick["l2"], pick["a"]}
        if len(chosen) > 1 and not _hard(timetable, teacher_id, closed, chosen) - baseline:
            proposals.insert(0, {"swaps": chosen, "resolved": len(chosen), "total": len(affected)})
    return proposals


def apply(timetable, proposal, save_availability=None):
    """Değişimleri uygular. Dersler o arada değiştiyse ValueError."""
    from .problem_cache import bump

    with transaction.atomic():
        for s in proposal["swaps"]:
            t1 = set(Lesson.objects.get(pk=s["l1"]).teachers.values_list("id", flat=True))
            t2 = set(Lesson.objects.get(pk=s["l2"]).teachers.values_list("id", flat=True))
            if s["m"] not in t1 or s["a"] not in t2 or s["m"] in t2 or s["a"] in t1:
                raise ValueError("Derslerin öğretmenleri öneri hesaplandıktan sonra değişmiş; yeniden hesaplayın.")
            _swap(s)
        if save_availability:
            teacher_id, day, periods = save_availability
            teacher = Teacher.objects.get(pk=teacher_id)
            for p in periods:
                Availability.objects.update_or_create(school=timetable.school, teacher=teacher, day=day, period=p,
                                                      defaults={"state": Availability.NO})
    bump(timetable.school_id)
