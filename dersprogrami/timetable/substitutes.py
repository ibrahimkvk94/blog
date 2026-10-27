"""Günlük vekâlet (ders doldurma) planı: devamsız öğretmenlerin derslerine vekil önerir.

Aday öğretmen o saatte dersi olmayan, o gün devamsız olmayan, o saate başka vekâlet almamış ve
müsaitliği "yasak" olmayan öğretmendir. Sıralama:
    aynı branş > o sınıfa derse giren > o saatte okulda boşta bekleyen > o gün okula gelen,
    eşitlikte günlük yükü az olan önce.
"""

from collections import defaultdict

from .models import Availability, Duty, Substitution

SCORE_SAME_SUBJECT = 100
SCORE_KNOWS_CLASS = 40
SCORE_ON_DUTY = 25
SCORE_IN_GAP = 30
SCORE_AT_SCHOOL = 10
SCORE_PER_LOAD = 5


def _day_cards(timetable, weekday):
    return list(
        timetable.cards.filter(day=weekday)
        .select_related("lesson__subject", "classroom")
        .prefetch_related("lesson__teachers", "lesson__classes", "lesson__groups")
        .order_by("period")
    )


def day_plan(school, timetable, date):
    weekday = date.weekday()
    cards = _day_cards(timetable, weekday)
    periods = {p.index: p for p in school.periods.all()}
    teachers = list(school.teachers.all())
    absences = list(
        school.absences.filter(date=date).select_related("teacher").prefetch_related("substitutions__substitute")
    )
    absent_ids = {a.teacher_id for a in absences}

    busy = defaultdict(set)
    for card in cards:
        for teacher in card.lesson.teachers.all():
            busy[teacher.id].update(range(card.period, card.period + card.length))

    substituting = defaultdict(set)
    for sub in Substitution.objects.filter(absence__school=school, absence__date=date, substitute__isnull=False):
        substituting[sub.substitute_id].add(sub.period)

    blocked = set(
        Availability.objects.filter(school=school, teacher__isnull=False, day=weekday, state=Availability.NO).values_list(
            "teacher_id", "period"
        )
    )

    on_duty = set(
        Duty.objects.filter(place__school=school, day=weekday).values_list("teacher_id", flat=True)
    )
    subject_teachers = defaultdict(set)
    class_teachers = defaultdict(set)
    for teacher in teachers:
        for subject_id in teacher.subjects.values_list("id", flat=True):
            subject_teachers[subject_id].add(teacher.id)
    for lesson in school.lessons.prefetch_related("teachers", "classes"):
        for teacher in lesson.teachers.all():
            subject_teachers[lesson.subject_id].add(teacher.id)
            for cls in lesson.classes.all():
                class_teachers[cls.id].add(teacher.id)

    plan = []
    for absence in absences:
        existing = {(s.card_id, s.period): s for s in absence.substitutions.all()}
        slots = []
        for card in cards:
            if absence.teacher_id not in {t.id for t in card.lesson.teachers.all()}:
                continue
            class_ids = {c.id for c in card.lesson.classes.all()}
            for period in range(card.period, card.period + card.length):
                current = existing.get((card.id, period))
                candidates = []
                for teacher in teachers:
                    if teacher.id in absent_ids or period in busy[teacher.id] or (teacher.id, period) in blocked:
                        continue
                    if period in substituting[teacher.id] and (current is None or current.substitute_id != teacher.id):
                        continue
                    own = busy[teacher.id]
                    reasons, score = [], 0
                    if teacher.id in subject_teachers[card.lesson.subject_id]:
                        score += SCORE_SAME_SUBJECT
                        reasons.append("aynı branş")
                    if any(teacher.id in class_teachers[c] for c in class_ids):
                        score += SCORE_KNOWS_CLASS
                        reasons.append("sınıfa giriyor")
                    if teacher.id in on_duty:
                        score += SCORE_ON_DUTY
                        reasons.append("bugün nöbetçi")
                    if own and min(own) < period < max(own):
                        score += SCORE_IN_GAP
                        reasons.append("boş saatinde")
                    elif own:
                        score += SCORE_AT_SCHOOL
                        reasons.append("bugün okulda")
                    load = len(own) + len(substituting[teacher.id])
                    score -= SCORE_PER_LOAD * load
                    reasons.append(f"günlük yük {load}")
                    candidates.append({"teacher": teacher, "score": score, "reasons": ", ".join(reasons)})
                candidates.sort(key=lambda c: (-c["score"], str(c["teacher"])))
                slots.append(
                    {
                        "key": f"{card.id}-{period}",
                        "card": card,
                        "period": period,
                        "period_obj": periods.get(period),
                        "classes": ", ".join(c.name for c in card.lesson.classes.all()),
                        "groups": ", ".join(sorted({g.name for g in card.lesson.groups.all()})),
                        "current": current,
                        "candidates": candidates,
                    }
                )
        slots.sort(key=lambda s: s["period"])
        plan.append(
            {
                "absence": absence,
                "slots": slots,
                "assigned": sum(1 for s in slots if s["current"] and s["current"].substitute_id),
            }
        )
    return plan


def save_assignments(absence, timetable, data):
    """Formdaki "slot-<kart>-<saat>" alanlarını kaydeder. Dönüş: vekil atanan saat sayısı."""
    weekday = absence.date.weekday()
    cards = {c.id: c for c in _day_cards(timetable, weekday)}
    valid_teachers = set(absence.school.teachers.values_list("id", flat=True)) - {absence.teacher_id}
    saved = 0
    for key, value in data.items():
        if not key.startswith("slot-"):
            continue
        try:
            card_id, period = (int(x) for x in key[5:].split("-"))
        except ValueError:
            continue
        card = cards.get(card_id)
        if card is None or not card.period <= period < card.period + card.length:
            continue
        if absence.teacher_id not in {t.id for t in card.lesson.teachers.all()}:
            continue
        substitute_id = int(value) if value.isdigit() and int(value) in valid_teachers else None
        Substitution.objects.update_or_create(
            absence=absence, card=card, period=period, defaults={"substitute_id": substitute_id}
        )
        saved += substitute_id is not None
    return saved
