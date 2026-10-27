"""Ana görünüm (satırlar: sınıf/öğretmen/derslik, sütunlar: gün × saat) için veri hazırlar."""

from collections import defaultdict

from .services import verify_timetable

KINDS = {"sinif": "classes", "ogretmen": "teachers", "derslik": "classrooms"}


def _join(items):
    return ", ".join(str(i) for i in items)


def room_names(school):
    return {r.id: str(r) for r in school.classrooms.all()}


def card_payload(card, kind, rooms_by_id=None):
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
        rows = card.room_ids
        line2 = " · ".join(filter(None, [_join(classes), _join(teachers)]))
    if rooms_by_id is not None:
        room = ", ".join(rooms_by_id.get(r, "?") for r in card.room_ids)
    else:
        room = str(card.classroom) if card.classroom else ""
    title = " · ".join(filter(None, [lesson.subject.name, _join(classes), ", ".join(groups), _join(teachers), room]))
    return {
        "id": card.id,
        "lesson_id": lesson.id,
        "subject_id": lesson.subject_id,
        "teacher_ids": [t.id for t in teachers],
        "class_ids": [c.id for c in classes],
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
    names = room_names(school)
    payloads = [card_payload(c, kind, names) for c in cards]
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
        if kind == "ogretmen":
            label = f"{obj.first_name} {obj.last_name}"
        elif kind == "sinif" and obj.short:
            label, sub = obj.short, f"{obj.name} · {sub}"
        else:
            label = str(obj)
        rows.append({"id": obj.id, "label": label, "sub": sub})

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
