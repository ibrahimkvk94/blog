"""Bir programın kısıtlara uygunluğunu çözücüden bağımsız olarak denetler.

Hem testlerde çözücünün doğruluğunu kanıtlamak, hem de elle düzenlenmiş programların
doğrulama raporu (aSc'deki "Verification") için kullanılır.
"""

from collections import defaultdict
from dataclasses import dataclass

from . import relations_extra


@dataclass
class Violation:
    code: str
    message: str
    level: str = "hard"
    ref: int | None = None  # kart ilişkisi ihlallerinde ilişkinin kimliği (denetim sayfası için)

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
        rooms = place.rooms
        if card.room_options and any(r not in card.room_options for r in rooms):
            violations.append(
                Violation("bad_room", f"{problem.label('lesson', card.lesson_id)}: izin verilmeyen derslik.")
            )
        if card.room_options and rooms and len(set(rooms)) < min(card.rooms_needed, len(card.room_options)):
            violations.append(
                Violation(
                    "missing_room",
                    f"{problem.label('lesson', card.lesson_id)}: {card.rooms_needed} derslik gerekiyor, {len(set(rooms))} atanmış.",
                    "soft",
                )
            )
        resources = [("teacher", t) for t in card.teachers] + [("atom", a) for a in card.atoms]
        resources += [("students", s) for s in card.students]
        resources += [("room", r) for r in dict.fromkeys(rooms)]
        for day, period in card.cells(place.day, place.period):
            for room in rooms:
                if (day, period) in problem.room_blocked.get(room, ()):
                    violations.append(
                        Violation("room_blocked", f"{problem.label('room', room)}: yasak hücrede kullanılmış.")
                    )
            for universe in card.universes:
                for kind, res in resources:
                    occupancy[(kind, res, universe, day, period)].append(card.key)

    reported = set()
    for (kind, res, _universe, day, period), keys in occupancy.items():
        limit = problem.room_slots.get(res, 1) if kind == "room" else 1
        if len(keys) > limit and (kind, res, day, period) not in reported:
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

    for (teacher_id, day), periods in teacher_busy.items():
        limits = problem.teacher_limits.get(teacher_id)
        if not limits or not periods:
            continue
        if limits.max_consecutive is not None and _longest_run(periods) > limits.max_consecutive:
            violations.append(
                Violation("teacher_consecutive", f"{problem.label('teacher', teacher_id)}: gün {day + 1} içinde art arda {_longest_run(periods)} ders.")
            )
        if limits.min_periods_per_day and len(periods) < limits.min_periods_per_day:
            violations.append(
                Violation("teacher_min", f"{problem.label('teacher', teacher_id)}: gün {day + 1} içinde yalnızca {len(periods)} ders.")
            )

    violations += _relationship_violations(problem, placements)

    atom_busy = busy_map("atoms")
    for atom_id in problem.cards_by("atoms"):
        class_id = problem.atom_class(atom_id)
        low, high = problem.class_limits.get(class_id, (None, None))
        for day in range(problem.days):
            count = len(atom_busy.get((atom_id, day), ()))
            if high is not None and count > high:
                violations.append(Violation("class_max", f"{problem.label('class', class_id)}: gün {day + 1} içinde {count} ders (en fazla {high})."))
            if low and count < low:
                violations.append(Violation("class_min", f"{problem.label('class', class_id)}: gün {day + 1} içinde {count} ders (en az {low})."))
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
    D, P = problem.days, problem.periods

    def add(rel, level, text, group=None):
        owner = rel.owners[group] if group is not None and group < len(rel.owners) else None
        if owner is not None:
            text = f"{problem.label(*owner)} – {text}"
        violations.append(Violation("relationship", f"{rel.name}: {text}", level, ref=rel.id))

    def cells_of(keys, cells=None, room_filter=None):
        """Kümenin dolu hücreleri: {(gün, saat): kart sayısı}; harita/derslik süzgeciyle."""
        seen = defaultdict(int)
        for key in keys:
            place = placements.get(key)
            if place is None or (room_filter is not None and not set(place.rooms) & room_filter):
                continue
            for cell in problem.cards[key].cells(place.day, place.period):
                if cells is None or cell in cells:
                    seen[cell] += 1
        return seen

    def by_day(seen):
        days = defaultdict(set)
        for d, p in seen:
            days[d].add(p)
        return days

    for rel in problem.relationships:
        level = "hard" if rel.weight is None else "soft"
        cond, n = rel.condition, rel.param
        if cond in relations_extra.ALL:
            for g, keys in enumerate(rel.groups):
                relations_extra.check(problem, placements, rel, keys, rel.groups_b[g] if rel.groups_b else [],
                                      lambda text, rel=rel: add(rel, level, text))
            continue
        for g, keys in enumerate(rel.groups):
            placed = [k for k in keys if k in placements]
            if cond in ("max_per_day", "different_days"):
                limit = 1 if cond == "different_days" else n
                per_day = defaultdict(int)
                for key in placed:
                    per_day[placements[key].day] += 1
                for day, count in per_day.items():
                    if count > limit:
                        add(rel, level, group=g, text=f"gün {day + 1} içinde {count} kart (en fazla {limit}).")
            elif cond == "min_gap_days":
                days = sorted(placements[k].day for k in placed)
                for a, b in zip(days, days[1:]):
                    if b - a <= n:
                        add(rel, level, group=g, text=f"gün {a + 1} ile gün {b + 1} arasında {max(0, b - a - 1)} boş gün (en az {n}).")
            elif cond in ("max_days", "range_max_days"):
                used = len(by_day(cells_of(keys, rel.cells)))
                if used > n:
                    add(rel, level, group=g, text=f"{used} güne yayılmış (en fazla {n}).")
            elif cond == "min_days":
                used = len({placements[k].day for k in placed})
                possible = len({d for k in keys for d, _ in problem.cards[k].starts}) or D
                if used < min(n, possible):
                    add(rel, level, group=g, text=f"yalnızca {used} güne yayılmış (en az {n}).")
            elif cond == "range_max_per_day":
                for day, periods in by_day(cells_of(keys, rel.cells)).items():
                    if len(periods) > n:
                        add(rel, level, group=g, text=f"gün {day + 1}, işaretli saatlerde {len(periods)} saat (en fazla {n}).")
            elif cond in ("map_max_week", "map_min_week"):
                total = len(cells_of(keys, rel.cells))
                if cond == "map_max_week" and total > n:
                    add(rel, level, group=g, text=f"işaretli saatlerde haftada {total} saat (en fazla {n}).")
                if cond == "map_min_week" and total < n:
                    add(rel, level, group=g, text=f"işaretli saatlerde haftada {total} saat (en az {n}).")
            elif cond == "map_min_if_any":
                for day, periods in by_day(cells_of(keys, rel.cells)).items():
                    if 0 < len(periods) < n:
                        add(rel, level, group=g, text=f"gün {day + 1}, işaretli saatlerde yalnızca {len(periods)} saat (en az {n}).")
            elif cond == "max_consecutive":
                for day, periods in by_day(cells_of(keys)).items():
                    run = _longest_run(periods)
                    if run > n:
                        add(rel, level, group=g, text=f"gün {day + 1} içinde art arda {run} saat.")
            elif cond in ("max_gaps_per_day", "max_gap_length"):
                for day, periods in by_day(cells_of(keys)).items():
                    ordered = sorted(periods)
                    holes = [b - a - 1 for a, b in zip(ordered, ordered[1:]) if b - a > 1]
                    if cond == "max_gaps_per_day" and sum(holes) > n:
                        add(rel, level, group=g, text=f"gün {day + 1} içinde {sum(holes)} boş saat (en fazla {n}).")
                    if cond == "max_gap_length" and holes and max(holes) > n:
                        add(rel, level, group=g, text=f"gün {day + 1} içinde {max(holes)} saatlik boşluk (en fazla {n}).")
            elif cond == "max_distinct_periods":
                distinct = len({placements[k].period for k in placed})
                if distinct > n:
                    add(rel, level, group=g, text=f"{distinct} farklı saatte başlıyor (en fazla {n}).")
            elif cond == "max_same_period_days":
                per_period = defaultdict(set)
                for d, p in cells_of(keys):
                    per_period[p].add(d)
                for p, days in per_period.items():
                    if len(days) > n:
                        add(rel, level, group=g, text=f"{p + 1}. saate {len(days)} gün düşüyor (en fazla {n}).")
            elif cond in ("not_simultaneous", "max_per_position"):
                limit = 1 if cond == "not_simultaneous" else n
                for (d, p), count in cells_of(keys, None if cond == "not_simultaneous" else rel.cells).items():
                    if count > limit:
                        add(rel, level, group=g, text=f"gün {d + 1}, saat {p + 1} içinde {count} kart aynı anda (en fazla {limit}).")
            elif cond == "min_per_position":
                seen = cells_of(keys)
                for cell in sorted(rel.cells or {(d, p) for d in range(D) for p in range(P)}):
                    if seen.get(cell, 0) < n:
                        add(rel, level, group=g, text=f"gün {cell[0] + 1}, saat {cell[1] + 1} içinde {seen.get(cell, 0)} kart (en az {n}).")
            elif cond in ("room_max_week", "room_min_week"):
                total = sum(cells_of(keys, rel.cells, set(rel.rooms)).values())
                if cond == "room_max_week" and total > n:
                    add(rel, level, group=g, text=f"seçili dersliklerde haftada {total} saat (en fazla {n}).")
                if cond == "room_min_week" and total < n:
                    add(rel, level, group=g, text=f"seçili dersliklerde haftada {total} saat (en az {n}).")
            elif cond == "max_rooms_week":
                rooms = {r for k in placed for r in placements[k].rooms}
                if len(rooms) > n:
                    add(rel, level, group=g, text=f"{len(rooms)} farklı derslik kullanılıyor (en fazla {n}).")
            elif cond == "max_buildings_day":
                per_day = defaultdict(set)
                for k in placed:
                    for room in placements[k].rooms:
                        building = problem.room_building.get(room)
                        if building is not None:
                            per_day[placements[k].day].add(building)
                for day, buildings in per_day.items():
                    if len(buildings) > n:
                        add(rel, level, group=g, text=f"gün {day + 1} içinde {len(buildings)} farklı bina (en fazla {n}).")
            elif cond in ("ab_not_same_day", "ab_not_day_after", "ab_not_consecutive"):
                keys_b = rel.groups_b[g]
                if cond == "ab_not_consecutive":
                    a_cells, b_cells = cells_of(keys), cells_of(keys_b)
                    if any((d, p + 1) in b_cells or (d, p - 1) in b_cells for d, p in a_cells):
                        add(rel, level, "A ve B kartları art arda.")
                    continue
                days_a = set(by_day(cells_of(keys, rel.cells)))
                days_b = set(by_day(cells_of(keys_b, rel.cells_b)))
                if cond == "ab_not_same_day" and days_a & days_b:
                    add(rel, level, group=g, text=f"A ve B aynı günde: gün {min(days_a & days_b) + 1}.")
                if cond == "ab_not_day_after" and any(d + 1 in days_b for d in days_a):
                    add(rel, level, "B, A'dan sonraki günde.")

        if cond in ("same_time", "same_day", "consecutive", "consecutive_ordered") and len(rel.groups) > 1:
            first, *others = rel.groups
            for other in others:
                for a, b in zip(first, other):
                    pa, pb = placements.get(a), placements.get(b)
                    if pa is None or pb is None:
                        continue
                    la, lb = problem.cards[a].length, problem.cards[b].length
                    if cond == "same_time" and (pa.day, pa.period) != (pb.day, pb.period):
                        add(rel, level, "kartlar aynı anda değil.")
                    elif cond == "same_day" and pa.day != pb.day:
                        add(rel, level, "kartlar aynı günde değil.")
                    elif cond == "consecutive" and (pa.day != pb.day or (pa.period + la != pb.period and pb.period + lb != pa.period)):
                        add(rel, level, "kartlar art arda değil.")
                    elif cond == "consecutive_ordered" and (pa.day != pb.day or pa.period + la != pb.period):
                        add(rel, level, "kartlar sıralı art arda değil.")
    return violations
