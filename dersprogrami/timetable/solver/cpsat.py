"""OR-Tools CP-SAT ile ders programı modeli.

Değişkenler:
    x[k, d, p]  kart k, gün d, saat p'de başlar (yalnızca izinli başlangıçlar için yaratılır)
    y[k, r]     kart k, r dersliğinde (birden fazla derslik seçeneği varsa)

Katı mod (strict): her kart yerleşir; öğretmen / öğrenci atomu / derslik çakışmaz (ortak
hafta-dönem evreninde); aynı dersin kartları günde en fazla N; öğretmen günlük ders, boşluk ve gün
sınırları ile "kesin" önemdeki kart ilişkileri sert kısıttır.

Gevşek mod (relaxed): kaynak çakışmaları ve kilitli kartlar yine serttir; ancak kartlar
yerleşmeden kalabilir (büyük ceza) ve diğer sert kurallar ağır cezalı yumuşak kurala dönüşür.
Böylece çözülemeyen veride bile en yakın taslak program ve kırılan kuralların listesi elde edilir.

Yumuşak kısıtlar (amaç): sınıf boşlukları, sınıfın güne ilk saatten başlamaması, öğretmen
boşlukları, koşullu (?) hücre kullanımı, önemi "kesin" olmayan kart ilişkileri.
"""

import threading
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

W_UNPLACED = 10000
W_RELAXED = 1000
W_CLASS_GAP = 100
W_CLASS_LATE_START = 50
W_TEACHER_GAP = 10
W_MAYBE = 5

STRICT = "strict"
RELAXED = "relaxed"

PENALTY_LABELS = {
    "unplaced": "Yerleşmeyen kart",
    "relaxed": "Gevşetilen kural",
    "relationship": "Kart ilişkisi",
    "class_gap": "Sınıf boşluğu",
    "class_late": "Güne geç başlama",
    "teacher_gap": "Öğretmen boşluğu",
    "maybe": "Koşullu hücre",
}

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
    unplaced: list[int] = field(default_factory=list)
    objective: int | None = None
    penalties: dict[str, int] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self):
        return self.status in ("optimal", "feasible")


class _Builder:
    def __init__(self, problem, mode=STRICT):
        self.problem = problem
        self.relaxed = mode == RELAXED
        self.m = cp_model.CpModel()
        self.x = {}  # key -> {(d, p): var}
        self.occ = {}  # key -> {(d, s): [var, ...]}
        self.y = {}  # key -> {room: var | 1}
        self.penalties = []  # (kategori, ağırlık, ifade)
        self._busy_cache = {}

    # --- yardımcılar -------------------------------------------------------------------------

    def _penalize(self, category, weight, expr):
        self.penalties.append((category, weight, expr))

    def _limit(self, terms, limit, hard, weight, name, category):
        """sum(terms) <= limit. Yumuşaksa ya da gevşek moddaysa aşım cezalandırılır."""
        variables = [t for t in terms if not isinstance(t, int)]
        constant = sum(t for t in terms if isinstance(t, int))
        if not variables:
            return
        if hard and not self.relaxed:
            self.m.Add(sum(variables) + constant <= limit)
            return
        slack = self.m.NewIntVar(0, len(variables), f"slack_{name}")
        self.m.Add(sum(variables) + constant <= limit + slack)
        if hard:
            self._penalize("relaxed", W_RELAXED, slack)
        else:
            self._penalize(category, weight, slack)

    def _busy(self, keys, day, slot, name):
        """Kaynağın (d, s) hücresinde dolu olup olmadığını gösteren bool; hiç aday yoksa 0."""
        cache_key = (tuple(keys), day, slot)
        if cache_key in self._busy_cache:
            return self._busy_cache[cache_key]
        terms = [v for k in keys for v in self.occ[k].get((day, slot), ())]
        busy = 0
        if terms:
            busy = self.m.NewBoolVar(name)
            for term in terms:
                self.m.AddImplication(term, busy)
            self.m.Add(busy <= sum(terms))
        self._busy_cache[cache_key] = busy
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

    def _universe_subsets(self, keys):
        """Aynı evrende birlikte aktif olan kart kümeleri (tekrarlar ayıklanmış)."""
        subsets = set()
        for universe in self.problem.universes:
            subset = frozenset(k for k in keys if universe in self.problem.cards[k].universes)
            if len(subset) > 1:
                subsets.add(subset)
        return subsets

    def _day_terms(self, keys, day):
        return [v for k in keys for (d, _), v in self.x[k].items() if d == day]

    # --- model -------------------------------------------------------------------------------

    def placement_vars(self):
        for card in self.problem.cards:
            starts = [card.fixed] if card.fixed is not None else card.starts
            xs = {(d, p): self.m.NewBoolVar(f"x{card.key}_{d}_{p}") for d, p in starts}
            if self.relaxed and card.fixed is None:
                self.m.AddAtMostOne(xs.values())
                self._penalize("unplaced", W_UNPLACED, 1 - sum(xs.values()))
            else:
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
            keys = [c.key for c in cards]
            for d in range(self.problem.days):
                terms = self._day_terms(keys, d)
                if len(terms) > limit:
                    self._limit(terms, limit, True, None, f"spread{lesson_id}_{d}", "relaxed")
            # Simetri kırma: birbirinin aynısı olan serbest kartları sıraya diz. Gevşek modda kart
            # yerleşmeyebileceği için bu sıralama geçerli olmaz.
            if self.relaxed:
                continue
            free = [c for c in cards if c.fixed is None and c.hint is None]
            for a, b in zip(free, free[1:]):
                if (a.length, a.room_options, a.universes) == (b.length, b.room_options, b.universes):
                    start_a = sum((d * P + p) * v for (d, p), v in self.x[a.key].items())
                    start_b = sum((d * P + p) * v for (d, p), v in self.x[b.key].items())
                    self.m.Add(start_a < start_b)

    def teacher_rules(self):
        for teacher_id, keys in self.problem.cards_by("teachers").items():
            limits = self.problem.teacher_limits.get(teacher_id)
            week_gaps, days_used = [], []
            for d in range(self.problem.days):
                busy = [self._busy(keys, d, s, f"tb{teacher_id}_{d}_{s}") for s in range(self.problem.periods)]
                gaps, _ = self._gaps(busy, f"tg{teacher_id}_{d}")
                week_gaps += gaps
                if limits and limits.max_periods_per_day is not None:
                    self._limit(busy, limits.max_periods_per_day, True, None, f"tmax{teacher_id}_{d}", "relaxed")
                if limits and limits.max_gaps_per_day is not None:
                    self._limit(gaps, limits.max_gaps_per_day, True, None, f"tgd{teacher_id}_{d}", "relaxed")
                if limits and limits.max_days_per_week is not None:
                    variables = [b for b in busy if not isinstance(b, int)]
                    if variables:
                        used = self.m.NewBoolVar(f"tday{teacher_id}_{d}")
                        for b in variables:
                            self.m.Add(used >= b)
                        days_used.append(used)
            if limits and limits.max_gaps_per_week is not None:
                self._limit(week_gaps, limits.max_gaps_per_week, True, None, f"tgw{teacher_id}", "relaxed")
            if limits and limits.max_days_per_week is not None:
                self._limit(days_used, limits.max_days_per_week, True, None, f"tdays{teacher_id}", "relaxed")
            if week_gaps:
                self._penalize("teacher_gap", W_TEACHER_GAP, sum(week_gaps))

    def class_rules(self):
        for atom_id, keys in self.problem.cards_by("atoms").items():
            for d in range(self.problem.days):
                busy = [self._busy(keys, d, s, f"ab{atom_id}_{d}_{s}") for s in range(self.problem.periods)]
                gaps, late = self._gaps(busy, f"ag{atom_id}_{d}")
                if gaps:
                    self._penalize("class_gap", W_CLASS_GAP, sum(gaps))
                if late is not None:
                    self._penalize("class_late", W_CLASS_LATE_START, late)

    def relationships(self):
        for index, rel in enumerate(self.problem.relationships):
            hard = rel.weight is None
            name = f"rel{index}"
            if rel.condition in ("max_per_day", "different_days"):
                limit = 1 if rel.condition == "different_days" else rel.param
                for g, keys in enumerate(rel.groups):
                    for d in range(self.problem.days):
                        terms = self._day_terms(keys, d)
                        if len(terms) > limit:
                            self._limit(terms, limit, hard, rel.weight, f"{name}_{g}_{d}", "relationship")
            elif rel.condition == "max_consecutive":
                n = max(1, rel.param)
                for g, keys in enumerate(rel.groups):
                    for d in range(self.problem.days):
                        busy = [self._busy(keys, d, s, f"{name}_b{g}_{d}_{s}") for s in range(self.problem.periods)]
                        for s in range(self.problem.periods - n):
                            self._limit(busy[s : s + n + 1], n, hard, rel.weight, f"{name}_{g}_{d}_{s}", "relationship")
            elif rel.condition == "same_time" and len(rel.groups) > 1:
                first, *others = rel.groups
                for g, other in enumerate(others):
                    for a, b in zip(first, other):
                        self._same_start(a, b, hard, rel.weight, f"{name}_{g}_{a}_{b}")

    def _same_start(self, a, b, hard, weight, name):
        xa, xb = self.x[a], self.x[b]
        slots = set(xa) | set(xb)
        if hard and not self.relaxed:
            for slot in slots:
                self.m.Add(xa.get(slot, 0) == xb.get(slot, 0))
            return
        mismatch = self.m.NewBoolVar(f"mis_{name}")
        for slot in slots:
            self.m.Add(xa.get(slot, 0) - xb.get(slot, 0) <= mismatch)
            self.m.Add(xb.get(slot, 0) - xa.get(slot, 0) <= mismatch)
        if hard:
            self._penalize("relaxed", W_RELAXED, mismatch)
        else:
            self._penalize("relationship", weight, mismatch)

    def maybe_cells(self):
        for card in self.problem.cards:
            terms = [v for cell, vs in self.occ[card.key].items() if cell in card.maybe_slots for v in vs]
            if terms:
                self._penalize("maybe", W_MAYBE, sum(terms))

    def build(self):
        self.placement_vars()
        self.resource_conflicts()
        self.rooms()
        self.lesson_spread()
        self.teacher_rules()
        self.class_rules()
        self.relationships()
        self.maybe_cells()
        if self.penalties:
            self.m.Minimize(sum(w * expr for _, w, expr in self.penalties))
        return self.m


class _Progress(cp_model.CpSolverSolutionCallback):
    def __init__(self, on_progress, should_stop):
        super().__init__()
        self.on_progress = on_progress
        self.should_stop = should_stop
        self.solutions = 0

    def on_solution_callback(self):
        self.solutions += 1
        if self.on_progress:
            self.on_progress(
                {
                    "solutions": self.solutions,
                    "objective": int(self.ObjectiveValue()),
                    "bound": int(self.BestObjectiveBound()),
                    "elapsed": round(self.WallTime(), 1),
                }
            )
        if self.should_stop and self.should_stop():
            self.StopSearch()


class StopHandle:
    """Çalışan bir çözümü başka bir iş parçacığından durdurmak için."""

    def __init__(self):
        self._solver = None
        self._stopped = threading.Event()
        self._lock = threading.Lock()

    def attach(self, solver):
        with self._lock:
            self._solver = solver
            if self._stopped.is_set():
                solver.StopSearch()

    def stop(self):
        with self._lock:
            self._stopped.set()
            if self._solver is not None:
                self._solver.StopSearch()

    @property
    def stopped(self):
        return self._stopped.is_set()


def solve(
    problem,
    time_limit=60,
    workers=8,
    seed=0,
    log=False,
    mode=STRICT,
    on_progress=None,
    should_stop=None,
    stop_handle=None,
):
    builder = _Builder(problem, mode)
    model = builder.build()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    solver.parameters.log_search_progress = log
    if stop_handle is not None:
        stop_handle.attach(solver)
    callback = _Progress(on_progress, should_stop)
    status = solver.Solve(model, callback)
    solution = Solution(
        status=STATUS_NAMES.get(status, "unknown"),
        stats={
            "wall_time": round(solver.WallTime(), 2),
            "conflicts": solver.NumConflicts(),
            "branches": solver.NumBranches(),
            "cards": len(problem.cards),
            "solutions": callback.solutions,
            "mode": mode,
            "stopped": bool(stop_handle and stop_handle.stopped),
        },
    )
    if not solution.ok:
        return solution
    if builder.penalties:
        solution.objective = int(solver.ObjectiveValue())
        totals = {}
        for category, weight, expr in builder.penalties:
            value = expr if isinstance(expr, int) else solver.Value(expr)
            if value:
                totals[category] = totals.get(category, 0) + weight * value
        solution.penalties = totals
    for card in problem.cards:
        start = next((slot for slot, var in builder.x[card.key].items() if solver.Value(var)), None)
        if start is None:
            solution.unplaced.append(card.key)
            continue
        room = None
        for r, var in builder.y.get(card.key, {}).items():
            if isinstance(var, int) or solver.Value(var):
                room = r
                break
        solution.placements[card.key] = Placement(start[0], start[1], room)
    return solution
