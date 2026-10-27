"""OR-Tools CP-SAT ile ders programı modeli.

Değişkenler:
    x[k, d, p]  kart k, gün d, saat p'de başlar (yalnızca izinli başlangıçlar için yaratılır)
    y[k, r]     kart k, r dersliğinde (birden fazla derslik seçeneği varsa)

Sert kısıtlar: her kart bir kez; öğretmen / öğrenci atomu / derslik çakışmaz (ortak hafta-dönem
evreninde); aynı dersin kartları günde en fazla N; öğretmen günlük ders ve boşluk sınırları.
Yumuşak kısıtlar (amaç): sınıf boşlukları, sınıfın güne ilk saatten başlamaması, öğretmen
boşlukları, koşullu (?) hücre kullanımı.
"""

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

W_CLASS_GAP = 100
W_TEACHER_GAP = 10
W_MAYBE = 5
W_CLASS_LATE_START = 50

STATUS_NAMES = {
    cp_model.OPTIMAL: "optimal",
    cp_model.FEASIBLE: "feasible",
    cp_model.INFEASIBLE: "infeasible",
    cp_model.MODEL_INVALID: "invalid",
    cp_model.UNKNOWN: "unknown",
}


@dataclass
class Placement:
    day: int
    period: int
    room: int | None


@dataclass
class Solution:
    status: str
    placements: dict[int, Placement] = field(default_factory=dict)
    objective: int | None = None
    stats: dict = field(default_factory=dict)

    @property
    def ok(self):
        return self.status in ("optimal", "feasible")


class _Builder:
    def __init__(self, problem):
        self.problem = problem
        self.m = cp_model.CpModel()
        self.x = {}  # key -> {(d, p): var}
        self.occ = {}  # key -> {(d, s): [var, ...]}
        self.y = {}  # key -> {room: var}
        self.penalties = []  # (weight, expr)

    # --- yardımcılar -------------------------------------------------------------------------

    def _busy(self, keys, day, slot, name):
        """Kaynağın (d, s) hücresinde dolu olup olmadığını gösteren bool; hiç aday yoksa 0."""
        terms = [v for k in keys for v in self.occ[k].get((day, slot), ())]
        if not terms:
            return 0
        busy = self.m.NewBoolVar(name)
        for term in terms:
            self.m.AddImplication(term, busy)
        self.m.Add(busy <= sum(terms))
        return busy

    def _gaps(self, busy, name):
        """Günlük doluluk dizisindeki boşluk göstergeleri ve "güne geç başlama" göstergesi.

        Göstergeler yalnızca alttan sınırlanır; bu yüzden yalnızca ceza ya da üst sınır olarak
        kullanılmalıdır (çözücü onları zaten küçültmek ister).
        """
        periods = len(busy)
        if all(isinstance(b, int) for b in busy):
            return [], None
        before = [0] * periods
        after = [0] * periods
        for s in range(1, periods):
            before[s] = self.m.NewBoolVar(f"{name}_b{s}")
            self.m.Add(before[s] >= busy[s - 1])
            self.m.Add(before[s] >= before[s - 1])
        for s in range(periods - 2, -1, -1):
            after[s] = self.m.NewBoolVar(f"{name}_a{s}")
            self.m.Add(after[s] >= busy[s + 1])
            self.m.Add(after[s] >= after[s + 1])
        gaps = []
        for s in range(1, periods - 1):
            gap = self.m.NewBoolVar(f"{name}_g{s}")
            self.m.Add(gap >= before[s] + after[s] - 1 - busy[s])
            gaps.append(gap)
        late = None
        if periods > 1:
            late = self.m.NewBoolVar(f"{name}_late")
            self.m.Add(late >= after[0] - busy[0])
        return gaps, late

    def _at_most(self, terms, limit):
        if any(not isinstance(t, int) for t in terms):
            self.m.Add(sum(terms) <= limit)

    def _universe_subsets(self, keys):
        """Aynı evrende birlikte aktif olan kart kümeleri (tekrarlar ayıklanmış)."""
        subsets = set()
        for universe in self.problem.universes:
            subset = frozenset(k for k in keys if universe in self.problem.cards[k].universes)
            if len(subset) > 1:
                subsets.add(subset)
        return subsets

    # --- model -------------------------------------------------------------------------------

    def placement_vars(self):
        for card in self.problem.cards:
            starts = [card.fixed] if card.fixed is not None else card.starts
            xs = {(d, p): self.m.NewBoolVar(f"x{card.key}_{d}_{p}") for d, p in starts}
            self.m.AddExactlyOne(xs.values())
            self.x[card.key] = xs
            occ = {}
            for (d, p), var in xs.items():
                for cell in card.cells(d, p):
                    occ.setdefault(cell, []).append(var)
            self.occ[card.key] = occ
            if card.hint is not None:
                for (d, p), var in xs.items():
                    self.m.AddHint(var, int((d, p) == card.hint[:2]))

    def resource_conflicts(self):
        for attr in ("teachers", "atoms"):
            for keys in self.problem.cards_by(attr).values():
                for subset in self._universe_subsets(keys):
                    cells = {cell for k in subset for cell in self.occ[k]}
                    for cell in cells:
                        terms = [v for k in subset for v in self.occ[k].get(cell, ())]
                        if len(terms) > 1:
                            self.m.Add(sum(terms) <= 1)

    def rooms(self):
        for card in self.problem.cards:
            options = card.room_options
            if card.fixed_room is not None and card.fixed_room in options:
                options = (card.fixed_room,)
            if len(options) > 1:
                ys = {r: self.m.NewBoolVar(f"y{card.key}_{r}") for r in options}
                self.m.AddExactlyOne(ys.values())
                self.y[card.key] = ys
                if card.hint is not None and card.hint[2] in ys:
                    for r, var in ys.items():
                        self.m.AddHint(var, int(r == card.hint[2]))
            elif options:
                self.y[card.key] = {options[0]: 1}

        by_room = {}
        for key, ys in self.y.items():
            for room in ys:
                by_room.setdefault(room, []).append(key)

        for room, keys in by_room.items():
            blocked = self.problem.room_blocked.get(room, frozenset())
            usage = {}  # (key, cell) -> 0/1 ifadesi: kart bu hücrede bu derslikte mi?
            for key in keys:
                y = self.y[key][room]
                for cell, terms in self.occ[key].items():
                    occupied = sum(terms)
                    if isinstance(y, int):
                        usage[(key, cell)] = occupied
                        continue
                    if cell in blocked:
                        self.m.Add(occupied + y <= 1)
                        continue
                    w = self.m.NewBoolVar(f"w{key}_{room}_{cell[0]}_{cell[1]}")
                    self.m.Add(w >= occupied + y - 1)
                    usage[(key, cell)] = w
            for subset in self._universe_subsets(keys):
                cells = {cell for (k, cell) in usage if k in subset}
                for cell in cells:
                    terms = [usage[(k, cell)] for k in subset if (k, cell) in usage]
                    if len(terms) > 1:
                        self.m.Add(sum(terms) <= 1)

    def lesson_spread(self):
        by_lesson = {}
        for card in self.problem.cards:
            by_lesson.setdefault(card.lesson_id, []).append(card)
        P = self.problem.periods
        for lesson_id, cards in by_lesson.items():
            limit = self.problem.lesson_max_per_day.get(lesson_id, len(cards))
            for d in range(self.problem.days):
                terms = [v for c in cards for (day, _), v in self.x[c.key].items() if day == d]
                if len(terms) > limit:
                    self.m.Add(sum(terms) <= limit)
            # Simetri kırma: birbirinin aynısı olan serbest kartları sıraya diz.
            free = [c for c in cards if c.fixed is None and c.hint is None]
            for a, b in zip(free, free[1:]):
                if (a.length, a.room_options, a.universes) == (b.length, b.room_options, b.universes):
                    start_a = sum((d * P + p) * v for (d, p), v in self.x[a.key].items())
                    start_b = sum((d * P + p) * v for (d, p), v in self.x[b.key].items())
                    self.m.Add(start_a < start_b)

    def teacher_rules(self):
        for teacher_id, keys in self.problem.cards_by("teachers").items():
            limits = self.problem.teacher_limits.get(teacher_id)
            week_gaps = []
            for d in range(self.problem.days):
                busy = [self._busy(keys, d, s, f"tb{teacher_id}_{d}_{s}") for s in range(self.problem.periods)]
                gaps, _ = self._gaps(busy, f"tg{teacher_id}_{d}")
                week_gaps += gaps
                if limits and limits.max_periods_per_day is not None:
                    self._at_most(busy, limits.max_periods_per_day)
                if limits and limits.max_gaps_per_day is not None and gaps:
                    self.m.Add(sum(gaps) <= limits.max_gaps_per_day)
            if limits and limits.max_gaps_per_week is not None and week_gaps:
                self.m.Add(sum(week_gaps) <= limits.max_gaps_per_week)
            if week_gaps:
                self.penalties.append((W_TEACHER_GAP, sum(week_gaps)))

    def class_rules(self):
        for atom_id, keys in self.problem.cards_by("atoms").items():
            for d in range(self.problem.days):
                busy = [self._busy(keys, d, s, f"ab{atom_id}_{d}_{s}") for s in range(self.problem.periods)]
                gaps, late = self._gaps(busy, f"ag{atom_id}_{d}")
                if gaps:
                    self.penalties.append((W_CLASS_GAP, sum(gaps)))
                if late is not None:
                    self.penalties.append((W_CLASS_LATE_START, late))

    def maybe_cells(self):
        for card in self.problem.cards:
            terms = [v for cell, vs in self.occ[card.key].items() if cell in card.maybe_slots for v in vs]
            if terms:
                self.penalties.append((W_MAYBE, sum(terms)))

    def build(self):
        self.placement_vars()
        self.resource_conflicts()
        self.rooms()
        self.lesson_spread()
        self.teacher_rules()
        self.class_rules()
        self.maybe_cells()
        if self.penalties:
            self.m.Minimize(sum(w * expr for w, expr in self.penalties))
        return self.m


def solve(problem, time_limit=60, workers=8, seed=0, log=False):
    builder = _Builder(problem)
    model = builder.build()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    solver.parameters.log_search_progress = log
    status = solver.Solve(model)
    solution = Solution(
        status=STATUS_NAMES.get(status, "unknown"),
        stats={
            "wall_time": round(solver.WallTime(), 2),
            "conflicts": solver.NumConflicts(),
            "branches": solver.NumBranches(),
            "cards": len(problem.cards),
        },
    )
    if not solution.ok:
        return solution
    if builder.penalties:
        solution.objective = int(solver.ObjectiveValue())
    for card in problem.cards:
        day, period = next(slot for slot, var in builder.x[card.key].items() if solver.Value(var))
        room = None
        for r, var in builder.y.get(card.key, {}).items():
            if isinstance(var, int) or solver.Value(var):
                room = r
                break
        solution.placements[card.key] = Placement(day, period, room)
    return solution
