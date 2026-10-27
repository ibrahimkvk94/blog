"""Bir programın kısıtlara uygunluğunu çözücüden bağımsız olarak denetler.

Hem testlerde çözücünün doğruluğunu kanıtlamak, hem de elle düzenlenmiş programların
doğrulama raporu (aSc'deki "Verification") için kullanılır.
"""

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Violation:
    code: str
    message: str
    level: str = "hard"

    def as_dict(self):
        return {"code": self.code, "message": self.message, "level": self.level}


def _day_gaps(busy_periods):
    if not busy_periods:
        return 0
    return max(busy_periods) - min(busy_periods) + 1 - len(busy_periods)


def validate(problem, placements):
    """placements: {kart anahtarı: Placement}. Dönüş: (ihlaller, istatistikler)."""
    violations = []
    unplaced = [c for c in problem.cards if c.key not in placements]
    for card in unplaced:
        violations.append(Violation("unplaced", f"{problem.label('lesson', card.lesson_id)}: kart yerleşmedi."))

    occupancy = defaultdict(list)  # (tür, kaynak, evren, gün, saat) -> kart anahtarları
    for card in problem.cards:
        place = placements.get(card.key)
        if place is None:
            continue
        if card.fixed is None and (place.day, place.period) not in card.starts:
            violations.append(
                Violation("blocked_cell", f"{problem.label('lesson', card.lesson_id)}: yasak hücreye yerleşmiş.")
            )
        if card.room_options and place.room not in card.room_options:
            violations.append(
                Violation("bad_room", f"{problem.label('lesson', card.lesson_id)}: izin verilmeyen derslik.")
            )
        resources = [("teacher", t) for t in card.teachers] + [("atom", a) for a in card.atoms]
        if place.room is not None:
            resources.append(("room", place.room))
        for day, period in card.cells(place.day, place.period):
            if place.room is not None and (day, period) in problem.room_blocked.get(place.room, ()):
                violations.append(
                    Violation("room_blocked", f"{problem.label('room', place.room)}: yasak hücrede kullanılmış.")
                )
            for universe in card.universes:
                for kind, res in resources:
                    occupancy[(kind, res, universe, day, period)].append(card.key)

    reported = set()
    for (kind, res, _universe, day, period), keys in occupancy.items():
        if len(keys) > 1 and (kind, res, day, period) not in reported:
            reported.add((kind, res, day, period))
            lessons = ", ".join(problem.label("lesson", problem.cards[k].lesson_id) for k in keys)
            violations.append(
                Violation(
                    f"{kind}_clash",
                    f"{problem.label(kind, res)}: gün {day + 1}, saat {period + 1} çakışma ({lessons}).",
                )
            )

    per_lesson_day = defaultdict(int)
    for card in problem.cards:
        place = placements.get(card.key)
        if place is not None:
            per_lesson_day[(card.lesson_id, place.day)] += 1
    for (lesson_id, day), count in per_lesson_day.items():
        limit = problem.lesson_max_per_day.get(lesson_id)
        if limit is not None and count > limit:
            violations.append(
                Violation(
                    "lesson_spread",
                    f"{problem.label('lesson', lesson_id)}: gün {day + 1} içinde {count} kart (en fazla {limit}).",
                )
            )

    def busy_map(attr):
        busy = defaultdict(set)  # (kaynak, gün) -> saatler
        for card in problem.cards:
            place = placements.get(card.key)
            if place is None:
                continue
            for res in getattr(card, attr):
                for day, period in card.cells(place.day, place.period):
                    busy[(res, day)].add(period)
        return busy

    teacher_busy = busy_map("teachers")
    teacher_gaps_total = 0
    week_gaps = defaultdict(int)
    for (teacher_id, day), periods in teacher_busy.items():
        gaps = _day_gaps(periods)
        teacher_gaps_total += gaps
        week_gaps[teacher_id] += gaps
        limits = problem.teacher_limits.get(teacher_id)
        if not limits:
            continue
        if limits.max_periods_per_day is not None and len(periods) > limits.max_periods_per_day:
            violations.append(
                Violation(
                    "teacher_daily_max",
                    f"{problem.label('teacher', teacher_id)}: gün {day + 1} içinde {len(periods)} ders.",
                )
            )
        if limits.max_gaps_per_day is not None and gaps > limits.max_gaps_per_day:
            violations.append(
                Violation("teacher_day_gaps", f"{problem.label('teacher', teacher_id)}: gün {day + 1} içinde {gaps} boşluk.")
            )
    for teacher_id, gaps in week_gaps.items():
        limits = problem.teacher_limits.get(teacher_id)
        if limits and limits.max_gaps_per_week is not None and gaps > limits.max_gaps_per_week:
            violations.append(
                Violation("teacher_week_gaps", f"{problem.label('teacher', teacher_id)}: haftada {gaps} boşluk.")
            )
        days = sum(1 for (t, _), periods in teacher_busy.items() if t == teacher_id and periods)
        if limits and limits.max_days_per_week is not None and days > limits.max_days_per_week:
            violations.append(
                Violation(
                    "teacher_days",
                    f"{problem.label('teacher', teacher_id)}: haftada {days} gün ders "
                    f"(en fazla {limits.max_days_per_week}).",
                )
            )

    violations += _relationship_violations(problem, placements)

    atom_busy = busy_map("atoms")
    class_gaps_total = sum(_day_gaps(periods) for periods in atom_busy.values())
    class_late_starts = sum(1 for periods in atom_busy.values() if min(periods) > 0)

    stats = {
        "placed": len(problem.cards) - len(unplaced),
        "unplaced": len(unplaced),
        "teacher_gaps": teacher_gaps_total,
        "class_gaps": class_gaps_total,
        "class_late_starts": class_late_starts,
    }
    return violations, stats


def _longest_run(periods):
    best = run = 0
    previous = None
    for period in sorted(periods):
        run = run + 1 if previous is not None and period == previous + 1 else 1
        best = max(best, run)
        previous = period
    return best


def _relationship_violations(problem, placements):
    violations = []
    for rel in problem.relationships:
        level = "hard" if rel.weight is None else "soft"
        if rel.condition in ("max_per_day", "different_days"):
            limit = 1 if rel.condition == "different_days" else rel.param
            for keys in rel.groups:
                per_day = defaultdict(int)
                for key in keys:
                    if key in placements:
                        per_day[placements[key].day] += 1
                for day, count in per_day.items():
                    if count > limit:
                        violations.append(
                            Violation("relationship", f"{rel.name}: gün {day + 1} içinde {count} kart (en fazla {limit}).", level)
                        )
        elif rel.condition == "max_consecutive":
            for keys in rel.groups:
                busy = defaultdict(set)
                for key in keys:
                    place = placements.get(key)
                    if place is not None:
                        for day, period in problem.cards[key].cells(place.day, place.period):
                            busy[day].add(period)
                for day, periods in busy.items():
                    run = _longest_run(periods)
                    if run > rel.param:
                        violations.append(
                            Violation("relationship", f"{rel.name}: gün {day + 1} içinde art arda {run} saat.", level)
                        )
        elif rel.condition == "same_time" and len(rel.groups) > 1:
            first, *others = rel.groups
            for other in others:
                for a, b in zip(first, other):
                    pa, pb = placements.get(a), placements.get(b)
                    if pa is None or pb is None or (pa.day, pa.period) != (pb.day, pb.period):
                        violations.append(Violation("relationship", f"{rel.name}: kartlar aynı anda değil.", level))
    return violations
