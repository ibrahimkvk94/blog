"""Ana görünüm (satırlar: sınıf/öğretmen/derslik, sütunlar: gün × saat) için veri hazırlar."""

from collections import defaultdict

from .services import verify_timetable

KINDS = {"sinif": "classes", "ogretmen": "teachers", "derslik": "classrooms"}


def _join(items):
    return ", ".join(str(i) for i in items)


def card_payload(card, kind):
    lesson = card.lesson
    classes = list(lesson.classes.all())
    teachers = list(lesson.teachers.all())
    groups = sorted({g.name for g in lesson.groups.all()})
    if kind == "sinif":
        rows = [c.id for c in classes]
        line2 = " · ".join(filter(None, [_join(teachers), ", ".join(groups)]))
    elif kind == "ogretmen":
        rows = [t.id for t in teachers]
        line2 = " · ".join(filter(None, [_join(classes), ", ".join(groups)]))
    else:
        rows = [card.classroom_id] if card.classroom_id else []
        line2 = " · ".join(filter(None, [_join(classes), _join(teachers)]))
    room = str(card.classroom) if card.classroom else ""
    title = " · ".join(filter(None, [lesson.subject.name, _join(classes), ", ".join(groups), _join(teachers), room]))
    return {
        "id": card.id,
        "lesson_id": lesson.id,
        "rows": rows,
        "day": card.day,
        "period": card.period,
        "length": card.length,
        "locked": card.locked,
        "subject": lesson.subject.short or lesson.subject.name,
        "subject_name": lesson.subject.name,
        "color": lesson.subject.color,
        "classes": _join(classes),
        "groups": ", ".join(groups),
        "teachers": _join(teachers),
        "room": room,
        "line2": line2,
        "title": title,
    }


def grid_data(timetable, kind):
    if kind not in KINDS:
        kind = "sinif"
    school = timetable.school
    cards = list(
        timetable.cards.select_related("lesson__subject", "classroom").prefetch_related(
            "lesson__classes", "lesson__teachers", "lesson__groups"
        )
    )
    payloads = [card_payload(c, kind) for c in cards]
    placed = [p for p in payloads if p["day"] is not None]
    unplaced = [p for p in payloads if p["day"] is None]

    occupied = defaultdict(set)
    pending = defaultdict(int)
    for p in payloads:
        for row in p["rows"]:
            if p["day"] is None:
                pending[row] += p["length"]
            else:
                for i in range(p["length"]):
                    occupied[row].add((p["day"], p["period"] + i))
    if kind == "derslik":
        # Yerleşmemiş kartın dersliği yoktur; bekleyenleri olası dersliklerine göre gösterme.
        pending.clear()

    rows = []
    for obj in getattr(school, KINDS[kind]).all():
        hours = len(occupied[obj.id])
        sub = f"{hours} saat"
        if pending[obj.id]:
            sub += f" · {pending[obj.id]} bekliyor"
        rows.append({"id": obj.id, "label": str(obj) if kind != "ogretmen" else f"{obj.first_name} {obj.last_name}", "sub": sub})

    violations, stats = verify_timetable(timetable)
    return {
        "kind": kind,
        "days": school.day_names,
        "periods": [
            {"index": p.index, "name": p.name, "start": p.start_time.strftime("%H:%M") if p.start_time else ""}
            for p in school.periods.all()
        ],
        "rows": rows,
        "cards": placed,
        "unplaced": unplaced,
        "stats": stats,
        "violations": [v.as_dict() for v in violations],
    }
