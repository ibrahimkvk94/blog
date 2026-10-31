"""Program analizi: iki sürümün karşılaştırması (aSc 14.4) ve istatistikler (aSc 25.2)."""

from collections import defaultdict

from .solver.builder import build_problem


def _where(school, day, period, length):
    span = f"{period + 1}" if length == 1 else f"{period + 1}–{period + length}"
    return f"{school.day_names[day]} {span}. saat"


def compare(timetable, other):
    """timetable'ın other'a göre değişen kartları.

    Kartlar sürümler arasında farklı kimlik taşır; bu yüzden ders ve konuma göre eşleştirilir.
    Dönüş: {"changed": [kart kimliği], "rows": [{"lesson", "before", "after"}], "summary"}.
    """
    school = timetable.school
    rooms = {r.id: str(r) for r in school.classrooms.all()}

    def placements(tt):
        by_lesson = defaultdict(list)
        for card in tt.cards.select_related("lesson__subject").prefetch_related("lesson__classes", "lesson__teachers"):
            by_lesson[card.lesson_id].append(card)
        return by_lesson

    mine, theirs = placements(timetable), placements(other)
    changed, rows = [], []
    labels = {}
    for lesson_id in sorted(set(mine) | set(theirs)):
        a_cards = list(mine.get(lesson_id, []))
        b_cards = list(theirs.get(lesson_id, []))
        sample = (a_cards or b_cards)[0]
        if lesson_id not in labels:
            classes = ", ".join(c.name for c in sample.lesson.classes.all())
            labels[lesson_id] = f"{sample.lesson.subject.name} – {classes or ', '.join(t.full_name for t in sample.lesson.teachers.all())}"
        # 1) aynı konum ve derslik  2) aynı konum, farklı derslik  3) kalanlar sırayla eşleşir
        for same_room in (True, False):
            for a in list(a_cards):
                match = next(
                    (
                        b for b in b_cards
                        if (a.day, a.period, a.length) == (b.day, b.period, b.length)
                        and (not same_room or sorted(a.room_ids) == sorted(b.room_ids))
                    ),
                    None,
                )
                if match is None:
                    continue
                a_cards.remove(a)
                b_cards.remove(match)
                if not same_room and a.is_placed:
                    changed.append(a.id)
                    rows.append({
                        "lesson": labels[lesson_id],
                        "before": "derslik: " + (", ".join(rooms.get(r, "?") for r in match.room_ids) or "–"),
                        "after": "derslik: " + (", ".join(rooms.get(r, "?") for r in a.room_ids) or "–"),
                    })
        key = lambda c: (c.day is None, c.day or 0, c.period or 0)  # noqa: E731
        a_cards.sort(key=key)
        b_cards.sort(key=key)
        for i in range(max(len(a_cards), len(b_cards))):
            a = a_cards[i] if i < len(a_cards) else None
            b = b_cards[i] if i < len(b_cards) else None
            if a is not None:
                changed.append(a.id)
            rows.append({
                "lesson": labels[lesson_id],
                "before": _where(school, b.day, b.period, b.length) if b and b.is_placed else ("yerleşmemiş" if b else "yok"),
                "after": _where(school, a.day, a.period, a.length) if a and a.is_placed else ("yerleşmemiş" if a else "yok"),
            })
    total = timetable.cards.count()
    return {
        "changed": changed,
        "rows": rows,
        "summary": f"{len(changed)} / {total} kart farklı",
    }


def _gaps(cells):
    if not cells:
        return 0
    return max(cells) - min(cells) + 1 - len(cells)


def statistics(timetable):
    """Öğretmen, sınıf ve derslik bazında özet sayılar."""
    from .services import placements_of

    school = timetable.school
    problem = build_problem(school, timetable=timetable)
    placements = placements_of(problem, timetable)
    days, periods = problem.days, problem.periods
    last = periods - 1

    teacher_cells = defaultdict(lambda: defaultdict(set))
    class_cells = defaultdict(lambda: defaultdict(set))
    room_hours = defaultdict(int)
    for card in problem.cards:
        place = placements.get(card.key)
        if place is None:
            continue
        cells = card.cells(place.day, place.period)
        for t in card.teachers:
            for d, p in cells:
                teacher_cells[t][d].add(p)
        for class_id in {problem.atom_class(a) for a in card.atoms}:
            for d, p in cells:
                class_cells[class_id][d].add(p)
        for room in place.rooms:
            room_hours[room] += card.length

    def summary(by_day):
        hours = sum(len(v) for v in by_day.values())
        gaps = [_gaps(v) for v in by_day.values()]
        return {
            "hours": hours,
            "days": sum(1 for v in by_day.values() if v),
            "gaps": sum(gaps),
            "max_gaps": max(gaps, default=0),
            "first": sum(1 for v in by_day.values() if 0 in v),
            "last": sum(1 for v in by_day.values() if last in v),
            "late": sum(1 for v in by_day.values() if v and min(v) > 0),
            "per_day": [len(by_day.get(d, ())) for d in range(days)],
        }

    teachers = []
    for t in school.teachers.all():
        row = summary(teacher_cells.get(t.id, {}))
        row.update(obj=t, name=t.full_name, target=t.target_periods)
        row["target_diff"] = row["hours"] - t.target_periods if t.target_periods else None
        teachers.append(row)
    classes = []
    for c in school.classes.all():
        row = summary(class_cells.get(c.id, {}))
        row.update(obj=c, name=c.name)
        classes.append(row)
    capacity = days * periods
    rooms = []
    for r in school.classrooms.all():
        free = (capacity - len(problem.room_blocked.get(r.id, ()))) * r.max_lessons
        hours = room_hours.get(r.id, 0)
        rooms.append({"obj": r, "name": str(r), "hours": hours, "free": free, "pct": round(100 * hours / free) if free else 0})
    placed = sum(1 for c in problem.cards if c.key in placements)
    return {
        "teachers": teachers,
        "classes": classes,
        "rooms": rooms,
        "days": school.day_names,
        "totals": {
            "cards": len(problem.cards),
            "placed": placed,
            "unplaced": len(problem.cards) - placed,
            "teacher_gaps": sum(r["gaps"] for r in teachers),
            "class_gaps": sum(r["gaps"] for r in classes),
            "late_starts": sum(r["late"] for r in classes),
        },
    }
