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

    def as_dict(self):
        return {"code": self.code, "message": self.message}


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
