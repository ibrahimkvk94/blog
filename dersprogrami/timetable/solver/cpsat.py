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
    extra_rooms: tuple = ()

    @property
    def rooms(self):
        return ((self.room,) if self.room is not None else ()) + tuple(self.extra_rooms)


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
    def __init__(self, problem, mode=STRICT, explain=False, active=None):
        self.problem = problem
        self.relaxed = mode == RELAXED
        # Açıklama modu: amaç yoktur; sert kurallar adlandırılır ve yalnızca `active` kümesindekiler
        # eklenir (None = hepsi). Böylece kuralların her alt kümesi ayrı bir modelle denenebilir.
        self.explain = explain
        self.active = active
        self.rule_labels = {}
        self.m = cp_model.CpModel()
        self.x = {}  # key -> {(d, p): var}
        self.occ = {}  # key -> {(d, s): [var, ...]}
        self.y = {}  # key -> {room: var | 1}
        self.penalties = []  # (kategori, ağırlık, ifade)
        self.room_usage = {}  # derslik -> {(kart, hücre): 0/1 ifadesi}
        self._busy_cache = {}

    # --- yardımcılar -------------------------------------------------------------------------

    def _penalize(self, category, weight, expr):
        if not self.explain:
            self.penalties.append((category, weight, expr))

    def _enforced(self, rule, label):
        """Açıklama modunda kuralı kaydeder; kural bu modelde uygulanacaksa True döner."""
        if rule is None:
            return True
        self.rule_labels.setdefault(rule, label)
        return self.active is None or rule in self.active

    def _limit(self, terms, limit, hard, weight, name, category, rule=None, label=""):
        """sum(terms) <= limit. Yumuşaksa ya da gevşek moddaysa aşım cezalandırılır."""
        variables = [t for t in terms if not isinstance(t, int)]
        constant = sum(t for t in terms if isinstance(t, int))
        if not variables:
            return
        if self.explain:
            if hard and self._enforced(rule, label):
                self.m.Add(sum(variables) + constant <= limit)
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

    def _at_least(self, terms, n, hard, weight, name, category, rule=None, label="", condition=1):
        """sum(terms) >= n * condition (condition: 1 ya da bool). Yumuşak/gevşekte eksik cezalandırılır."""
        variables = [t for t in terms if not isinstance(t, int)]
        constant = sum(t for t in terms if isinstance(t, int))
        if n <= 0:
            return
        expr = sum(variables) + constant if variables else constant
        if self.explain:
            if hard and self._enforced(rule, label):
                self.m.Add(expr >= n * condition)
            return
        if hard and not self.relaxed:
            self.m.Add(expr >= n * condition)
            return
        slack = self.m.NewIntVar(0, n, f"short_{name}")
        self.m.Add(expr + slack >= n * condition)
        if hard:
            self._penalize("relaxed", W_RELAXED, slack)
        else:
            self._penalize(category, weight, slack)

    def _any(self, terms, name):
        """Terimlerden biri 1 ise 1 olan bool (iki yönden bağlı); terim yoksa 0."""
        variables = [t for t in terms if not isinstance(t, int)]
        if not variables:
            return int(any(terms))
        flag = self.m.NewBoolVar(name)
        for t in variables:
            self.m.Add(flag >= t)
        self.m.Add(flag <= sum(variables))
        return flag

    def _violation(self, v, hard, weight, rule=None, label=""):
        """v: kural ihlal edilince 1 olmak zorunda olan bool. Mod ve öneme göre yasaklar ya da cezalandırır."""
        if self.explain:
            if hard and self._enforced(rule, label):
                self.m.Add(v == 0)
            return
        if hard and not self.relaxed:
            self.m.Add(v == 0)
        elif hard:
            self._penalize("relaxed", W_RELAXED, v)
        else:
            self._penalize("relationship", weight, v)

    def _day_expr(self, key, day):
        return sum(v for (d, _), v in self.x[key].items() if d == day)

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
        entity_labels = self.problem.labels.get("entity", {})
        for card in self.problem.cards:
            if self.explain:
                # Müsaitlik ve kilit de birer kural olarak gevşetilebilsin diye tüm başlangıçlar açılır.
                starts = sorted(set(card.starts) | set(card.blocked) | ({card.fixed} if card.fixed else set()))
            else:
                starts = [card.fixed] if card.fixed is not None else card.starts
            xs = {(d, p): self.m.NewBoolVar(f"x{card.key}_{d}_{p}") for d, p in starts}
            if self.explain:
                for start, var in xs.items():
                    for entity in card.blocked.get(start, ()):
                        label = f"{entity_labels.get(entity, entity)}: müsaitlik (yasak saatler)"
                        if self._enforced(("avail", entity), label):
                            self.m.Add(var == 0)
                if card.fixed is not None:
                    d, p = card.fixed
                    label = f"{self.problem.label('lesson', card.lesson_id)}: kilitli kart ({d + 1}. gün, {p + 1}. saat)"
                    if self._enforced(("locked", card.key), label):
                        self.m.Add(xs[card.fixed] == 1)
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
            needed = max(1, min(card.rooms_needed, len(options))) if options else 0
            fixed = tuple(r for r in (card.fixed_rooms or ((card.fixed_room,) if card.fixed_room is not None else ())) if r in options)
            if len(fixed) >= needed and fixed:
                options = fixed[:needed]
            if len(options) > needed:
                ys = {r: self.m.NewBoolVar(f"y{card.key}_{r}") for r in options}
                self.m.Add(sum(ys.values()) == needed)
                self.y[card.key] = ys
                if card.hint is not None and card.hint[2] in ys:
                    self.m.AddHint(ys[card.hint[2]], 1)
            elif options:
                self.y[card.key] = {r: 1 for r in options}

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
                    self.m.Add(w <= occupied)
                    self.m.Add(w <= y)
                    usage[(key, cell)] = w
            self.room_usage[room] = usage
            slots = self.problem.room_slots.get(room, 1)
            for subset in self._universe_subsets(keys):
                cells = {cell for (k, cell) in usage if k in subset}
                for cell in cells:
                    terms = [usage[(k, cell)] for k in subset if (k, cell) in usage]
                    if len(terms) > slots:
                        self.m.Add(sum(terms) <= slots)

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
                    self._limit(
                        terms, limit, True, None, f"spread{lesson_id}_{d}", "relaxed",
                        rule=("spread", lesson_id),
                        label=f"{self.problem.label('lesson', lesson_id)}: günde en fazla {limit} kart (farklı günlere dağılım)",
                    )
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
            who = self.problem.label("teacher", teacher_id)
            week_gaps, days_used = [], []
            for d in range(self.problem.days):
                busy = [self._busy(keys, d, s, f"tb{teacher_id}_{d}_{s}") for s in range(self.problem.periods)]
                gaps, _ = self._gaps(busy, f"tg{teacher_id}_{d}")
                week_gaps += gaps
                if limits and limits.max_periods_per_day is not None:
                    self._limit(
                        busy, limits.max_periods_per_day, True, None, f"tmax{teacher_id}_{d}", "relaxed",
                        rule=("teacher_max", teacher_id), label=f"{who}: günde en fazla {limits.max_periods_per_day} ders",
                    )
                if limits and limits.max_gaps_per_day is not None:
                    self._limit(
                        gaps, limits.max_gaps_per_day, True, None, f"tgd{teacher_id}_{d}", "relaxed",
                        rule=("teacher_gaps_day", teacher_id), label=f"{who}: günde en fazla {limits.max_gaps_per_day} boşluk",
                    )
                if limits and limits.max_days_per_week is not None:
                    variables = [b for b in busy if not isinstance(b, int)]
                    if variables:
                        used = self.m.NewBoolVar(f"tday{teacher_id}_{d}")
                        for b in variables:
                            self.m.Add(used >= b)
                        days_used.append(used)
                if limits and limits.max_consecutive is not None:
                    n = limits.max_consecutive
                    for s in range(self.problem.periods - n):
                        self._limit(
                            busy[s : s + n + 1], n, True, None, f"tcons{teacher_id}_{d}_{s}", "relaxed",
                            rule=("teacher_consecutive", teacher_id), label=f"{who}: art arda en fazla {n} ders",
                        )
                if limits and limits.min_periods_per_day:
                    n = limits.min_periods_per_day
                    self._at_least(
                        busy, n, True, None, f"tmin{teacher_id}_{d}", "relaxed",
                        rule=("teacher_min", teacher_id), label=f"{who}: geldiği günlerde en az {n} ders",
                        condition=self._any(busy, f"tday_any{teacher_id}_{d}"),
                    )
            if limits and limits.max_gaps_per_week is not None:
                self._limit(
                    week_gaps, limits.max_gaps_per_week, True, None, f"tgw{teacher_id}", "relaxed",
                    rule=("teacher_gaps_week", teacher_id), label=f"{who}: haftada en fazla {limits.max_gaps_per_week} boşluk",
                )
            if limits and limits.max_days_per_week is not None:
                self._limit(
                    days_used, limits.max_days_per_week, True, None, f"tdays{teacher_id}", "relaxed",
                    rule=("teacher_days", teacher_id), label=f"{who}: haftada en fazla {limits.max_days_per_week} gün",
                )
            if week_gaps:
                self._penalize("teacher_gap", W_TEACHER_GAP, sum(week_gaps))

    def class_limits(self):
        """Sınıfların günlük en az / en fazla ders sınırı (her öğrenci atomu için)."""
        if not self.problem.class_limits:
            return
        for atom_id, keys in self.problem.cards_by("atoms").items():
            class_id = self.problem.atom_class(atom_id)
            low, high = self.problem.class_limits.get(class_id, (None, None))
            if low is None and high is None:
                continue
            name = self.problem.label("class", class_id)
            for d in range(self.problem.days):
                busy = [self._busy(keys, d, s, f"ab{atom_id}_{d}_{s}") for s in range(self.problem.periods)]
                if high is not None:
                    self._limit(
                        busy, high, True, None, f"cmax{atom_id}_{d}", "relaxed",
                        rule=("class_max", class_id), label=f"{name}: günde en fazla {high} ders",
                    )
                if low:
                    self._at_least(
                        busy, low, True, None, f"cmin{atom_id}_{d}", "relaxed",
                        rule=("class_min", class_id), label=f"{name}: günde en az {low} ders",
                    )

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
        D, P = self.problem.days, self.problem.periods
        for index, rel in enumerate(self.problem.relationships):
            hard = rel.weight is None
            name = f"rel{index}"
            opts = {"rule": ("rel", index), "label": f"Kart ilişkisi: {rel.name}"}
            cells_a = rel.cells

            def limit(terms, n, tag):
                self._limit(terms, n, hard, rel.weight, f"{name}_{tag}", "relationship", **opts)

            def at_least(terms, n, tag, condition=1):
                self._at_least(terms, n, hard, rel.weight, f"{name}_{tag}", "relationship", condition=condition, **opts)

            def violation(tag):
                v = self.m.NewBoolVar(f"v_{name}_{tag}")
                self._violation(v, hard, rel.weight, **opts)
                return v

            def in_map(cell, cells="A"):
                cells = cells_a if cells == "A" else cells
                return cells is None or cell in cells

            def busy(keys, d, s, tag):
                return self._busy(keys, d, s, f"{name}_{tag}_{d}_{s}")

            def map_busy(keys, d, tag, cells="A"):
                return [busy(keys, d, s, tag) for s in range(P) if in_map((d, s), cells)]

            cond = rel.condition
            for g, keys in enumerate(rel.groups):
                if cond in ("max_per_day", "different_days"):
                    n = 1 if cond == "different_days" else rel.param
                    for d in range(D):
                        terms = self._day_terms(keys, d)
                        if len(terms) > n:
                            limit(terms, n, f"{g}_{d}")
                elif cond == "min_gap_days":
                    # Aynı kümedeki iki kart arasında en az N boş gün: gün farkı N'den büyük olmalı.
                    for i, a in enumerate(keys):
                        for b in keys[i + 1 :]:
                            v = violation(f"{g}_{a}_{b}")
                            for da in range(D):
                                for db in range(D):
                                    if abs(da - db) <= rel.param:
                                        self.m.Add(self._day_expr(a, da) + self._day_expr(b, db) <= 1 + v)
                elif cond in ("max_days", "range_max_days"):
                    flags = []
                    for d in range(D):
                        terms = map_busy(keys, d, f"m{g}")
                        if any(not isinstance(t, int) for t in terms):
                            used = self.m.NewBoolVar(f"{name}_u{g}_{d}")
                            for t in terms:
                                self.m.Add(used >= t)
                            flags.append(used)
                    limit(flags, rel.param, f"{g}")
                elif cond == "min_days":
                    flags = []
                    for d in range(D):
                        terms = self._day_terms(keys, d)
                        if terms:
                            unused = self.m.NewBoolVar(f"{name}_n{g}_{d}")
                            self.m.Add(unused >= 1 - sum(terms))
                            flags.append(unused)
                    # Hiç kart konamayacak günler zaten "kullanılmamış" sayılır.
                    limit(flags, len(flags) - rel.param, f"{g}")
                elif cond == "range_max_per_day":
                    for d in range(D):
                        limit(map_busy(keys, d, f"r{g}"), rel.param, f"{g}_{d}")
                elif cond == "map_max_week":
                    limit([b for d in range(D) for b in map_busy(keys, d, f"w{g}")], rel.param, f"{g}")
                elif cond == "map_min_week":
                    at_least([b for d in range(D) for b in map_busy(keys, d, f"w{g}")], rel.param, f"{g}")
                elif cond == "map_min_if_any":
                    for d in range(D):
                        terms = map_busy(keys, d, f"i{g}")
                        if terms:
                            at_least(terms, rel.param, f"{g}_{d}", condition=self._any(terms, f"{name}_any{g}_{d}"))
                elif cond == "max_consecutive":
                    n = max(1, rel.param)
                    for d in range(D):
                        row = [busy(keys, d, s, f"b{g}") for s in range(P)]
                        for s in range(P - n):
                            limit(row[s : s + n + 1], n, f"{g}_{d}_{s}")
                elif cond in ("max_gaps_per_day", "max_gap_length"):
                    for d in range(D):
                        row = [busy(keys, d, s, f"b{g}") for s in range(P)]
                        gaps, _ = self._gaps(row, f"{name}_gap{g}_{d}")
                        if cond == "max_gaps_per_day":
                            limit(gaps, rel.param, f"{g}_{d}")
                        else:
                            n = rel.param
                            for s in range(len(gaps) - n):
                                limit(gaps[s : s + n + 1], n, f"{g}_{d}_{s}")
                elif cond == "max_distinct_periods":
                    used = []
                    for p in range(P):
                        starts = [v for k in keys for (d, q), v in self.x[k].items() if q == p]
                        if starts:
                            flag = self.m.NewBoolVar(f"{name}_p{g}_{p}")
                            for v in starts:
                                self.m.Add(flag >= v)
                            used.append(flag)
                    limit(used, rel.param, f"{g}")
                elif cond == "max_same_period_days":
                    for p in range(P):
                        limit([busy(keys, d, p, f"b{g}") for d in range(D)], rel.param, f"{g}_{p}")
                elif cond in ("not_simultaneous", "max_per_position", "min_per_position"):
                    n = 1 if cond == "not_simultaneous" else rel.param
                    for d in range(D):
                        for p in range(P):
                            if cond != "not_simultaneous" and not in_map((d, p)):
                                continue
                            terms = [v for k in keys for v in self.occ[k].get((d, p), ())]
                            if cond == "min_per_position":
                                at_least(terms, n, f"{g}_{d}_{p}")
                            elif len(terms) > n:
                                limit(terms, n, f"{g}_{d}_{p}")
                elif cond in ("room_max_week", "room_min_week"):
                    group = set(keys)
                    terms = [
                        u
                        for room in rel.rooms
                        for (k, cell), u in self.room_usage.get(room, {}).items()
                        if k in group and in_map(cell)
                    ]
                    if cond == "room_max_week":
                        limit(terms, rel.param, f"{g}")
                    else:
                        at_least(terms, rel.param, f"{g}")
                elif cond == "max_rooms_week":
                    group = set(keys)
                    used = []
                    for room, usage in self.room_usage.items():
                        terms = [u for (k, _), u in usage.items() if k in group]
                        if any(not isinstance(t, int) for t in terms):
                            flag = self.m.NewBoolVar(f"{name}_room{g}_{room}")
                            for t in terms:
                                if not isinstance(t, int):
                                    self.m.Add(flag >= t)
                            used.append(flag)
                    limit(used, rel.param, f"{g}")
                elif cond == "max_buildings_day":
                    group = set(keys)
                    for d in range(D):
                        by_building = {}
                        for room, usage in self.room_usage.items():
                            building = self.problem.room_building.get(room)
                            if building is None:
                                continue
                            by_building.setdefault(building, []).extend(
                                u for (k, cell), u in usage.items() if k in group and cell[0] == d and not isinstance(u, int)
                            )
                        flags = []
                        for building, terms in by_building.items():
                            if terms:
                                flag = self.m.NewBoolVar(f"{name}_bld{g}_{d}_{building}")
                                for t in terms:
                                    self.m.Add(flag >= t)
                                flags.append(flag)
                        limit(flags, rel.param, f"{g}_{d}")
                elif cond in ("ab_not_same_day", "ab_not_day_after", "ab_not_consecutive"):
                    keys_b = rel.groups_b[g]
                    if cond == "ab_not_consecutive":
                        for d in range(D):
                            for s in range(P - 1):
                                limit([busy(keys, d, s, f"a{g}"), busy(keys_b, d, s + 1, f"b{g}")], 1, f"{g}_{d}_{s}_ab")
                                limit([busy(keys_b, d, s, f"b{g}"), busy(keys, d, s + 1, f"a{g}")], 1, f"{g}_{d}_{s}_ba")
                        continue
                    has_a = [self._any(map_busy(keys, d, f"a{g}"), f"{name}_ha{g}_{d}") for d in range(D)]
                    has_b = [self._any(map_busy(keys_b, d, f"b{g}", rel.cells_b), f"{name}_hb{g}_{d}") for d in range(D)]
                    for d in range(D):
                        if cond == "ab_not_same_day":
                            limit([has_a[d], has_b[d]], 1, f"{g}_{d}")
                        elif d + 1 < D:
                            limit([has_a[d], has_b[d + 1]], 1, f"{g}_{d}")

            if cond in ("same_time", "same_day", "consecutive", "consecutive_ordered") and len(rel.groups) > 1:
                first, *others = rel.groups
                for g, other in enumerate(others):
                    for a, b in zip(first, other):
                        v = violation(f"pair{g}_{a}_{b}")
                        if cond == "same_time":
                            for slot in set(self.x[a]) | set(self.x[b]):
                                xa, xb = self.x[a].get(slot, 0), self.x[b].get(slot, 0)
                                self.m.Add(xa - xb <= v)
                                self.m.Add(xb - xa <= v)
                        elif cond == "same_day":
                            for d in range(D):
                                self.m.Add(self._day_expr(a, d) - self._day_expr(b, d) <= v)
                                self.m.Add(self._day_expr(b, d) - self._day_expr(a, d) <= v)
                        else:
                            # a'nın hemen ardından b başlar; sırası serbestse b'nin ardından a da olur.
                            len_a, len_b = self.problem.cards[a].length, self.problem.cards[b].length
                            ordered = cond == "consecutive_ordered"
                            for (d, p), xa in self.x[a].items():
                                after = self.x[b].get((d, p + len_a), 0)
                                before = 0 if ordered or p - len_b < 0 else self.x[b].get((d, p - len_b), 0)
                                self.m.Add(xa <= after + before + v)
                            for (d, p), xb in self.x[b].items():
                                before_a = self.x[a].get((d, p - len_a), 0) if p - len_a >= 0 else 0
                                after_a = 0 if ordered else self.x[a].get((d, p + len_b), 0)
                                self.m.Add(xb <= before_a + after_a + v)

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
        self.class_limits()
        self.relationships()
        if self.explain:
            return self.m
        self.class_rules()
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
        rooms = [r for r, var in builder.y.get(card.key, {}).items() if isinstance(var, int) or solver.Value(var)]
        solution.placements[card.key] = Placement(start[0], start[1], rooms[0] if rooms else None, tuple(rooms[1:]))
    return solution


@dataclass
class Explanation:
    """Katı modda çözülemeyen programın nedeni.

    status: "core" (birlikte imkânsız kurallar bulundu), "no_rules" (hiçbir kural gevşetilmeden de
    imkânsız: kaynak yetersizliği), "feasible" (kurallar birlikte sağlanabiliyor; sorun süre
    sınırıydı) ya da "unknown" (süre yetmedi).
    """

    status: str
    rules: list[str] = field(default_factory=list)
    keys: list = field(default_factory=list)
    minimal: bool = False
    checks: int = 0
    wall_time: float = 0.0


def explain(problem, time_limit=60, check_limit=10, workers=8, known_infeasible=False):
    """Birlikte sağlanamayan sert kuralların en küçük kümelerinden birini bulur (QuickXplain).

    Her denemede yalnızca seçili kurallarla temiz bir model kurulur; böylece CP-SAT'in ön işlemesi
    tam güçle çalışır ve imkânsızlık hızla kanıtlanır. Süre biterse ya da bir deneme belirsiz
    kalırsa sonuç yine çelişen bir kümedir ama en küçük olmayabilir (minimal=False).
    known_infeasible: tüm kurallarla imkânsız olduğu zaten biliniyorsa ilk deneme atlanır.
    """
    import time

    started = time.monotonic()
    checks = 0
    labels = {}
    exact = True

    def infeasible(active):
        """True: bu kurallarla imkânsız; False: mümkün ya da belirsiz."""
        nonlocal checks, exact
        checks += 1
        builder = _Builder(problem, STRICT, explain=True, active=frozenset(active))
        model = builder.build()
        labels.update(builder.rule_labels)
        remaining = time_limit - (time.monotonic() - started)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(1.0, min(check_limit, remaining))
        solver.parameters.num_workers = workers
        status = solver.Solve(model)
        if status == cp_model.UNKNOWN:
            exact = False
        return status == cp_model.INFEASIBLE

    def result(status, rules=()):
        return Explanation(
            status, [labels[k] for k in rules], list(rules), exact, checks, round(time.monotonic() - started, 2)
        )

    # Tüm kural adlarını öğrenmek için modeli bir kez kur.
    everything = _Builder(problem, STRICT, explain=True)
    everything.build()
    labels.update(everything.rule_labels)
    keys = list(everything.rule_labels)

    if not known_infeasible and not infeasible(keys):
        return result("feasible" if exact else "unknown")
    if infeasible([]):
        return result("no_rules")

    def out_of_time():
        return time.monotonic() - started > time_limit

    def quickxplain(background, delta, candidates):
        if delta and (out_of_time() or infeasible(background)):
            return []
        if len(candidates) == 1:
            return list(candidates)
        half = len(candidates) // 2
        first, second = candidates[:half], candidates[half:]
        x2 = quickxplain(background + first, first, second)
        x1 = quickxplain(background + x2, x2, first)
        return x1 + x2

    core = quickxplain([], [], keys)
    if out_of_time():
        exact = False
    if not core or not infeasible(core):
        return result("unknown")
    return result("core", core)
