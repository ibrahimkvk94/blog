"""Gün bazlı ayrıştırma: önce her kart bir güne, sonra her günün kartları saatlere yerleşir.

Sınıfların haftası tamamen dolu ve çok sayıda "art arda" kuralı olan programlarda (ör. KAMYO) tek parça
model sıfırdan aramada çözüm bulamıyor: bir kartı oynatmak zincirleme yer değiştirme istiyor. Burada:

1. Gün modeli: kart → gün. Her kaynağın (öğretmen, öğrenci atomu, derslik / derslik kümesi) her [s, e) saat
   aralığına mutlaka taşan kart saatleri o aralıktaki kullanılabilir hücreleri aşamaz (enerji kısıtı); art arda
   çiftler tek blok sayılır ve ortak yerleşimi olan bir güne düşer; dersin günlük kart sınırı ve öğretmen/sınıf
   günlük sınırları uygulanır.
2. Saat modeli: her gün ayrı ve küçük bir katı model (standart _Builder); "en çok kartı yerleştir" hedefiyle
   kesin çözülür (gerçek veride gün başına 1–4 sn).
3. Atma: bir günde sığmayan kart birkaç tur o günden uzak tutulur, gün modeli onu (öncekinden en az kart
   oynatarak) başka güne taşır. Bu takılınca açıkta kalan kartın günüyle başka bir gün birlikte çözülür.

Çıkan program bağımsız doğrulayıcıdan geçer; ardından standart üretim ipucu olarak alıp iyileştirebilir.
Haftaya yayılan bazı kesin kurallar henüz desteklenmez (unsupported); o zaman yöntem hiç denenmez.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field, replace

from ortools.sat.python import cp_model

from .cpsat import STRICT, _Builder, _placements, default_workers
from .validate import validate

PAIRED = ("same_time", "same_day", "consecutive", "consecutive_ordered")
TABU_WEIGHT = 20  # gün modelinde yasak (kart, gün) çiftinin cezası; bir kartı yerinde tutmanın değeri 1
STATUS_TEXT = {cp_model.INFEASIBLE: "infeasible", cp_model.UNKNOWN: "unknown", cp_model.MODEL_INVALID: "invalid"}


@dataclass
class DaySplitResult:
    status: str  # "ok", "unsupported", "infeasible" (gün dağılımı yok), "invalid", "timeout", "stopped"
    placements: dict = field(default_factory=dict)
    rounds: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    unplaced: list = field(default_factory=list)
    hard_violations: int | None = None
    wall_time: float = 0.0

    @property
    def ok(self):
        return self.status == "ok"


def unsupported(problem):
    """Bu yöntemin ele almadığı kesin kurallar; boşsa yöntem kullanılabilir."""
    reasons = []
    if problem.teacher_pools:
        reasons.append("öğretmen havuzu")
    if problem.anchors or problem.max_moves is not None:
        reasons.append("en az değişiklikle onarım")
    for rel in problem.relationships:
        if rel.weight is None and rel.condition not in PAIRED:
            reasons.append(f"kart ilişkisi: {rel.name}")
    for teacher, limits in problem.teacher_limits.items():
        if limits.max_gaps_per_week is not None:
            reasons.append(f"{problem.label('teacher', teacher)}: haftalık boşluk sınırı")
    return reasons


def _starts(card):
    return [card.fixed] if card.fixed is not None else list(card.starts)


def _pairs(problem):
    """Kesin eşleşmeli kurallardaki (kural, a, b) çiftleri; a ile b aynı günde olmak zorunda."""
    out = []
    for rel in problem.relationships:
        if rel.weight is None and rel.condition in PAIRED and len(rel.groups) > 1:
            first, *others = rel.groups
            for other in others:
                out += [(rel, a, b) for a, b in zip(first, other)]
    return out


def _pair_days(problem, rel, a, b):
    """Çiftin birlikte yerleşebildiği günler."""
    ca, cb = problem.cards[a], problem.cards[b]
    sa, sb = set(_starts(ca)), set(_starts(cb))
    if rel.condition == "same_day":
        return {d for d, _ in sa} & {d for d, _ in sb}
    if rel.condition == "same_time":
        return {d for d, _ in sa & sb}
    days = {d for d, p in sa if (d, p + ca.length) in sb}
    if rel.condition == "consecutive":
        days |= {d for d, p in sb if (d, p + cb.length) in sa}
    return days


def _required_rooms(card):
    options = card.room_options
    needed = max(1, min(card.rooms_needed, len(options))) if options else 0
    return options if options and len(options) <= needed else ()


def _effective_starts(problem, pairs):
    """Eşleşmeli ortağıyla birlikte gerçekten kullanılabilecek başlangıçlar."""
    eff = {c.key: set(_starts(c)) for c in problem.cards}
    for _ in range(2):  # birden çok çifte giren kart için bir tur daha
        for rel, a, b in pairs:
            la, lb = problem.cards[a].length, problem.cards[b].length
            sa, sb = eff[a], eff[b]
            if rel.condition == "same_time":
                eff[a] = eff[b] = sa & sb
            elif rel.condition == "same_day":
                days = {d for d, _ in sa} & {d for d, _ in sb}
                eff[a], eff[b] = {s for s in sa if s[0] in days}, {s for s in sb if s[0] in days}
            else:
                free = rel.condition == "consecutive"
                eff[a] = {(d, p) for d, p in sa if (d, p + la) in sb or (free and (d, p - lb) in sb)}
                eff[b] = {(d, p) for d, p in sb if (d, p - la) in sa or (free and (d, p + lb) in sa)}
    return eff


def _items(problem, pairs, eff, keys):
    """Bir kaynağın kartları enerji hesabı için: art arda çiftin iki kartı da bu kaynaktaysa tek blok.

    Dönüş: [(temsilci kart, uzunluk, {gün: [başlangıç saatleri]})]."""
    keys = set(keys)
    merged, items = set(), []
    for rel, a, b in pairs:
        if rel.condition not in ("consecutive", "consecutive_ordered") or a not in keys or b not in keys:
            continue
        if a in merged or b in merged:
            continue
        la, lb = problem.cards[a].length, problem.cards[b].length
        starts = defaultdict(set)
        for d, p in eff[a]:
            if (d, p + la) in eff[b]:
                starts[d].add(p)
        if rel.condition == "consecutive":
            for d, p in eff[b]:
                if (d, p + lb) in eff[a]:
                    starts[d].add(p)
        merged |= {a, b}
        items.append((a, la + lb, {d: sorted(ps) for d, ps in starts.items()}))
    for k in sorted(keys - merged):
        starts = defaultdict(list)
        for d, p in sorted(eff[k]):
            starts[d].append(p)
        items.append((k, problem.cards[k].length, dict(starts)))
    return items


class _DayModel:
    """Kart → gün modeli (enerji kısıtlarıyla); her turda önceki dağılımdan en az kart oynatılır."""

    def __init__(self, problem):
        self.problem = problem
        self.m = cp_model.CpModel()
        self.a = {}  # kart -> {gün: bool}
        D = problem.days
        days_of = {c.key: {d for d, _ in _starts(c)} for c in problem.cards}
        pairs = _pairs(problem)
        for rel, a, b in pairs:
            joint = _pair_days(problem, rel, a, b)
            days_of[a] &= joint
            days_of[b] &= joint
        for card in problem.cards:
            self.a[card.key] = {d: self.m.NewBoolVar(f"a{card.key}_{d}") for d in sorted(days_of[card.key])}
            self.m.AddExactlyOne(self.a[card.key].values())  # gün kalmadıysa model baştan çözümsüz
        for _, a, b in pairs:
            for d in range(D):
                self.m.Add(self.a[a].get(d, 0) == self.a[b].get(d, 0))

        # Kaynak kapasitesi (enerji): her gün ve her [s, e) saat aralığı için, o aralığa mutlaka taşan
        # kart saatleri ≤ kaynağın o aralıkta kullanılabilecek hücreleri. Tüm gün aralığı, günlük toplamdır.
        eff = _effective_starts(problem, pairs)
        users = defaultdict(list)
        for card in problem.cards:
            res = [("t", t) for t in card.teachers] + [("a", x) for x in card.atoms] + [("s", s) for s in card.students]
            res += [("r", r) for r in _required_rooms(card)]
            for item in res:
                users[item].append(card)
        # Birden çok seçenekli derslik kümeleri: seçenekleri kümenin içinde kalan kartlar, kümenin toplam kapasitesini paylaşır.
        # (Birden çok derslik isteyen kartlar dışarıda kalır; kart çıkarmak sınırı yalnızca gevşetir.)
        groups = {frozenset(c.room_options) for c in problem.cards if len(c.room_options) > 1 and c.rooms_needed <= 1}
        for group in groups:
            members = [c for c in problem.cards if c.room_options and c.rooms_needed <= 1 and set(c.room_options) <= group]
            if len(members) > 1:
                users[("g", group)] = members
        self.load = {}  # (kaynak, gün) -> saat ifadesi (evren ayrımı yapılmadan; sınırlar için)
        P = problem.periods
        windows = [(s, e) for s in range(P) for e in range(s + 1, P + 1)]
        self.energy = 0
        for res, cards in users.items():
            rooms = (res[1],) if res[0] == "r" else tuple(res[1]) if res[0] == "g" else ()

            def cell_cap(d, p):  # o hücrede aynı anda kaç kart (derslikte: kapalı olmayan derslik kapasiteleri)
                if not rooms:
                    return 1
                return sum(problem.room_slots.get(r, 1) for r in rooms if (d, p) not in problem.room_blocked.get(r, ()))

            for universe in problem.universes:
                active = [c.key for c in cards if universe in c.universes]
                items = _items(problem, pairs, eff, active)
                for d in range(D):
                    day_items = [(k, length, starts[d]) for k, length, starts in items if starts.get(d) and d in self.a[k]]
                    usable = {p + i for _, length, starts in day_items for p in starts for i in range(length)}
                    caps = {p: cell_cap(d, p) for p in usable}
                    for s, e in windows:
                        cap = sum(c for p, c in caps.items() if s <= p < e)
                        terms = []
                        for k, length, starts in day_items:
                            overlap = min(max(0, min(p + length, e) - max(p, s)) for p in starts)
                            if overlap:
                                terms.append((overlap, self.a[k][d]))
                        if sum(w for w, _ in terms) > cap:
                            self.m.Add(sum(w * v for w, v in terms) <= cap)
                            self.energy += 1
            if res[0] != "g":
                for d in range(D):
                    self.load[(res, d)] = sum(c.length * self.a[c.key][d] for c in cards if d in self.a[c.key])

        # Dersin günlük kart sınırı (varsayılan: her kart farklı güne).
        by_lesson = defaultdict(list)
        for card in problem.cards:
            by_lesson[card.lesson_id].append(card.key)
        for lesson_id, keys in by_lesson.items():
            limit = problem.lesson_max_per_day.get(lesson_id, len(keys))
            for d in range(D):
                terms = [self.a[k][d] for k in keys if d in self.a[k]]
                if len(terms) > limit:
                    self.m.Add(sum(terms) <= limit)

        # Öğretmen günlük/haftalık sınırları.
        for teacher, limits in problem.teacher_limits.items():
            used_days = []
            for d in range(D):
                load = self.load.get((("t", teacher), d), 0)
                if isinstance(load, int):
                    continue
                if limits.max_periods_per_day is not None:
                    self.m.Add(load <= limits.max_periods_per_day)
                if limits.max_days_per_week is not None or limits.min_periods_per_day:
                    used = self.m.NewBoolVar(f"used{teacher}_{d}")
                    keys = [c.key for c in users[("t", teacher)] if d in self.a[c.key]]
                    for k in keys:
                        self.m.Add(used >= self.a[k][d])
                    self.m.Add(used <= sum(self.a[k][d] for k in keys))
                    used_days.append(used)
                    if limits.min_periods_per_day:
                        self.m.Add(load >= limits.min_periods_per_day * used)
            if limits.max_days_per_week is not None and used_days:
                self.m.Add(sum(used_days) <= limits.max_days_per_week)

        # Sınıfın günlük en az / en fazla dersi (her atom için; atomun dersleri çakışmadığından saat toplamı).
        for item, cards in users.items():
            if item[0] != "a":
                continue
            low, high = problem.class_limits.get(problem.atom_class(item[1]), (None, None))
            for d in range(D):
                load = self.load[(item, d)]
                if high is not None and not isinstance(load, int):
                    self.m.Add(load <= high)
                if low:
                    self.m.Add(load >= low)

    def solve(self, seconds, workers, seed, previous=None, tabu=(), stop_handle=None):
        """previous verilirse en az kartı başka güne taşıyan dağılım aranır; tabu: (kart, gün) yasakları."""
        self.m.ClearHints()
        self.m.ClearObjective()
        kept = []
        if previous:
            for key, day in previous.items():
                for d, var in self.a[key].items():
                    self.m.AddHint(var, int(d == day))
                if day in self.a[key]:
                    kept.append(self.a[key][day])
            self.m.Maximize(sum(kept))
        if tabu:
            # Yasak (kart, gün) çiftleri ağır cezalıdır ama yasaklanmaz: tek günlük kartta ya da kapasite
            # zorunlu kıldığında yine o güne düşebilir, model hiçbir zaman çözümsüz kalmaz.
            terms = [self.a[k][d] for k, d in tabu if d in self.a[k]]
            self.m.Maximize(sum(kept) - TABU_WEIGHT * sum(terms))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(1.0, seconds)
        solver.parameters.num_workers = workers
        solver.parameters.random_seed = seed
        if stop_handle is not None:
            stop_handle.attach(solver)
        status = solver.Solve(self.m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return status, None, []
        return status, {k: next(d for d, v in days.items() if solver.Value(v)) for k, days in self.a.items()}, []


class _HourBuilder(_Builder):
    """Gün alt probleminin katı modeli; kartın yerleşip yerleşmediği use[k] ile gösterilir (en çok kart hedefi)."""

    def placement_vars(self):
        self.use = {}
        for card in self.problem.cards:
            xs = {(d, p): self.m.NewBoolVar(f"x{card.key}_{d}_{p}") for d, p in _starts(card)}
            use = self.m.NewBoolVar(f"use{card.key}")
            self.m.Add(sum(xs.values()) == use)
            self.use[card.key] = use
            self.x[card.key] = xs
            occ = {}
            for (d, p), var in xs.items():
                for cell in card.cells(d, p):
                    occ.setdefault(cell, []).append(var)
            self.occ[card.key] = occ


def _day_problem(problem, days, keys):
    """Yalnızca verilen günler ve kartlarla alt problem; günler 0, 1, ... olarak yeniden sıralanır.

    Dönüş: (alt problem, yeni→eski kart anahtarı). days tek bir gün de olabilir."""
    days = (days,) if isinstance(days, int) else tuple(days)
    index = {d: i for i, d in enumerate(days)}
    keys = sorted(keys)
    new_key = {old: i for i, old in enumerate(keys)}
    remap = lambda cells: frozenset((index[d], p) for d, p in cells if d in index)  # noqa: E731
    cards = []
    for old in keys:
        c = problem.cards[old]
        cards.append(replace(
            c, key=new_key[old], starts=[(index[d], p) for d, p in _starts(c) if d in index],
            fixed=(index[c.fixed[0]], c.fixed[1]) if c.fixed is not None and c.fixed[0] in index else None,
            maybe_slots=remap(c.maybe_slots), blocked={}, hint=None,
        ))
    rels = []
    for rel in problem.relationships:
        if rel.weight is not None or rel.condition not in PAIRED or len(rel.groups) < 2:
            continue  # tercihler bu aşamada aranmaz
        first, *others = rel.groups
        for other in others:
            pairs = [(new_key[a], new_key[b]) for a, b in zip(first, other) if a in new_key and b in new_key]
            if pairs:
                rels.append(replace(rel, groups=[[a for a, _ in pairs], [b for _, b in pairs]], groups_b=[],
                                    cells=None, cells_b=None))
    limits = {t: replace(lim, max_days_per_week=None, max_gaps_per_week=None) for t, lim in problem.teacher_limits.items()}
    sub = replace(
        problem, days=len(days), cards=cards, relationships=rels, teacher_limits=limits,
        room_blocked={r: remap(cells) for r, cells in problem.room_blocked.items()},
        anchors={}, room_anchors={}, max_moves=None, forbidden_move_sets=[], teacher_weights={},
    )
    return sub, {i: old for old, i in new_key.items()}


def _fill_days(problem, days, keys, seconds, workers, seed, hints=None, stop_handle=None, weights=None):
    """Verilen günlere kartların en çoğunu yerleştirir (kesin kurallarla); kartlar bu günler arasında yer
    değiştirebilir. Dönüş: ({kart: Placement}, sığmayan kartlar, kesin mi)."""
    days = (days,) if isinstance(days, int) else tuple(days)
    sub, old_of = _day_problem(problem, days, keys)
    builder = _HourBuilder(sub, STRICT)
    model = builder.build()
    model.ClearHints()
    model.Maximize(sum((weights or {}).get(old_of[k], 1) * use for k, use in builder.use.items()))
    index = {d: i for i, d in enumerate(days)}
    for new, old in old_of.items():
        place = (hints or {}).get(old)
        if place is not None and place.day in index:
            for (d, p), var in builder.x[new].items():
                model.AddHint(var, int((d, p) == (index[place.day], place.period)))
            model.AddHint(builder.use[new], 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, seconds)
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    if stop_handle is not None:
        stop_handle.attach(solver)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {}, list(keys), False
    places = {old_of[k]: replace(p, day=days[p.day]) for k, p in _placements(builder, solver, sub).items()}
    return places, sorted(set(keys) - set(places)), status == cp_model.OPTIMAL


class _State:
    """Güncel gün dağılımı ve her günün yerleşimi (gün → (kartlar, yerleşim, sığmayanlar))."""

    def __init__(self, assignment):
        self.assign = dict(assignment)
        self.days = {}

    def keys(self, day):
        return frozenset(k for k, d in self.assign.items() if d == day)

    def placements(self):
        return {k: p for _, places, _ in self.days.values() for k, p in places.items()}

    def missing(self):
        return [(k, d) for d, (_, _, miss) in sorted(self.days.items()) for k in miss]

    def apply(self, days, places, missing):
        """Birkaç günün yeni çözümünü işler; yerleşen kart yerleştiği güne geçer, sığmayan eski gününde kalır."""
        for k, p in places.items():
            self.assign[k] = p.day
        for d in days:
            self.days[d] = (self.keys(d), {k: p for k, p in places.items() if p.day == d},
                            sorted(k for k in missing if self.assign[k] == d))


def solve(problem, time_limit=300, workers=None, seed=0, on_progress=None, stop_handle=None,
          day_seconds=10.0, pair_seconds=15.0, tabu_rounds=8, stall_rounds=4):
    """Gün bazlı üretim.

    Her tur ya gün düzeyinde atma ya da iki günlük birleşik onarım yapar:
    - Atma: gün modeli kartları günlere dağıtır (öncekinden en az kart oynatarak, sığmayan kartı birkaç tur o
      günden uzak tutarak); değişen her gün "en çok kart" hedefiyle kesin çözülür.
    - Birleşik onarım (atma takılınca): açıkta kalan kartın günüyle başka bir gün birlikte çözülür; kartlar
      iki gün arasında yer değiştirebilir. Açıktaki kart sayısı azalırsa yeni yerleşim alınır.
    Açıkta kart kalmayınca program bağımsız doğrulayıcıdan geçer.
    Dönüş: DaySplitResult; ok değilse placements en az kartın açıkta kaldığı yerleşimdir (unplaced)."""
    started = time.monotonic()
    workers = workers or default_workers()
    result = DaySplitResult("timeout")
    result.reasons = unsupported(problem)
    if result.reasons:
        result.status = "unsupported"
        return result
    deadline = started + float(time_limit)
    left = lambda: deadline - time.monotonic()  # noqa: E731
    stopped = lambda: stop_handle is not None and stop_handle.stopped  # noqa: E731
    model = _DayModel(problem)
    days_of = {k: sorted(v) for k, v in model.a.items()}
    state, tabu, best = None, {}, None
    round_no = stall = pair_turn = 0
    while left() > 1 and not stopped():
        round_no += 1
        row = {"round": round_no}
        missing = state.missing() if state else None
        if state is None or stall < stall_rounds or not missing:
            # --- gün düzeyinde atma ---
            active = [kd for kd, until in tabu.items() if until >= round_no]
            status, assignment, _ = model.solve(min(15.0, left()), workers, seed + round_no,
                                                state.assign if state else None, active, stop_handle)
            if assignment is None:
                result.status = "infeasible" if status == cp_model.INFEASIBLE else "timeout"
                result.rounds.append({"round": round_no, "days": STATUS_TEXT.get(status, "unknown")})
                break
            row.update(step="days", moved=sum(1 for k, d in assignment.items() if state and state.assign[k] != d))
            hints = state.placements() if state else {}
            old_days = state.days if state else {}
            state = _State(assignment)
            solved = 0
            for day in range(problem.days):
                keys = state.keys(day)
                if day in old_days and old_days[day][0] == keys:
                    state.days[day] = old_days[day]
                    continue
                if left() < 1 or stopped():
                    break
                places, miss, _ = _fill_days(problem, (day,), keys, min(day_seconds, left()), workers, seed, hints,
                                             stop_handle)
                state.days[day] = (keys, places, miss)
                solved += 1
            if len(state.days) < problem.days:
                break  # süre doldu ya da durduruldu
            row["days_solved"] = solved
            for kd in state.missing():
                tabu[kd] = round_no + tabu_rounds
        else:
            # --- iki günlük birleşik onarım ---
            k, d1 = missing[pair_turn % len(missing)]
            others = [d for d in days_of[k] if d != d1] or [d for d in range(problem.days) if d != d1]
            d2 = others[(pair_turn // len(missing)) % len(others)]
            pair_turn += 1
            keys = state.keys(d1) | state.keys(d2)
            before = len(state.days[d1][2]) + len(state.days[d2][2])
            places, miss, _ = _fill_days(problem, (d1, d2), keys, min(pair_seconds, left()), workers, seed + round_no,
                                         state.placements(), stop_handle)
            row.update(step="pair", days=[d1, d2], before=before, after=len(miss))
            if places and len(miss) < before:
                state.apply((d1, d2), places, miss)
        missing = state.missing()
        row.update(unplaced=len(missing), time=round(time.monotonic() - started, 1))
        result.rounds.append(row)
        if on_progress:
            on_progress({"phase": "days", **row})
        if best is None or len(missing) < best[0]:
            best = (len(missing), state.placements(), [k for k, _ in missing])
            stall = 0
        else:
            stall += 1
        if not missing:
            break
        if stall >= stall_rounds + 3 * max(1, len(missing)):
            stall = 0  # birleşik onarım da ilerlemiyorsa yeniden gün düzeyine dön
    if best is not None:
        _, result.placements, result.unplaced = best
        if not result.unplaced:
            violations, _ = validate(problem, result.placements)
            result.hard_violations = sum(v.level == "hard" for v in violations)
            result.status = "ok" if result.hard_violations == 0 else "invalid"
    if stopped() and result.status == "timeout":
        result.status = "stopped"
    result.wall_time = round(time.monotonic() - started, 1)
    return result
