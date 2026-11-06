"""Katı modelin onarım yolu: Gen2 turları ile gün komşuluğu dönüşümlü çalışır.

Sıkışık programlarda (KAMYO Manuel: 1104 kart, kısımların haftası tam dolu, 150 kesin art arda kuralı) Gen2'nin
kaynak komşuluğu son birkaç ihlalde tıkanır. Kalan ihlal çoğu zaman bir dersin başka güne geçmesini ve o günlerin
bütün derslerinin birlikte yeniden dizilmesini gerektirir; ihlalin öğretmen/kısım çevresini açmak bunu sağlamaz.
Gün komşuluğu her turda 2–3 günün bütün kartlarını serbest bırakır, diğer günleri yerinde sabitler; aşım
artırılamaz ama eşit aşımlı farklı yerleşim kabul edilir (yan adımlar sonraki turlara yol açar).
Manuel'de Gen2 20 dakikada 3 ihlalde tıkandı; gün komşuluğu 7,5 dakikada 3 → 0 indirdi.

Akış: Gen2 turları (tıkanınca durur) → gün komşuluğu (iki tam turda iyileşme yoksa durur) → en iyi taslak ipucu
olarak yeniden Gen2 … Sıfır aşımda taslak Gen2'nin kesin doğrulamasından geçer (katı model + yardımcı değişkenler).
"""

import itertools
import random
import time

from ortools.sat.python import cp_model

from . import gen2
from .cpsat import RELAXED, STATUS_NAMES, _Builder, _FirstSolution, _relaxed_solution, _StopAtZero

GEN2_SLICE = 1200.0  # bir Gen2 bölümünün en uzun süresi (tur uzunluğu buna göre ölçeklenir)
GEN2_STALL = 180.0  # Gen2 bu kadar saniye yeni en düşük aşım bulamazsa gün komşuluğuna geçilir (son aşamada o daha etkili)
DAY_ROUND = 25.0  # bir gün komşuluğu turunun en uzun süresi
DAY_ROUND_WIDE = 60.0  # 4 günlük grup turunun en uzun süresi
SHAKE_SHARE = 0.2  # serbest kartların bu payı "yerinde kalma" cezası alır (yan adımlar için)
PAIRED = ("same_time", "same_day", "consecutive", "consecutive_ordered")
DAY_STALL_CYCLES = 2  # bütün gün grupları bu kadar kez iyileşmesiz denenirse Gen2'ye dönülür


class _StallGuard:
    """Gen2'ye verilen durdurma tutamağı: kullanıcı durdurursa ya da bölüm tıkanırsa "durdu" der."""

    def __init__(self, outer, state, stall):
        self.outer = outer
        self.state = state
        self.stall = stall
        self.started = time.monotonic()

    def attach(self, solver):
        if self.outer is not None:
            self.outer.attach(solver)

    @property
    def stopped(self):
        if self.outer is not None and self.outer.stopped:
            return True
        return time.monotonic() - max(self.started, self.state["improved"]) > self.stall


class DayRepair:
    """Gün komşuluğu: esnek model bir kez kurulur, her tur kopyasında seçili günlerin dışı sabitlenir."""

    def __init__(self, problem, workers, seed, stop_handle=None, on_progress=None):
        self.problem = problem
        self.workers = workers
        self.seed = seed
        self.stop_handle = stop_handle
        self.on_progress = on_progress
        self.relaxed = _Builder(problem, RELAXED, place_all=True)
        self.model = self.relaxed.build()
        self.slacks = [e for _, _, e in self.relaxed.relaxed_slacks]
        self.model.Minimize(sum(self.slacks))
        days = sorted({d for slots in self.relaxed.x.values() for d, _ in slots})
        self.combos = [set(c) for size in (2, 3) if size <= len(days) for c in itertools.combinations(days, size)]
        # 2–3 günlük gruplar tıkanınca açılan geniş kademe (bir gün dışında her şey serbest; turlar daha uzun).
        self.wide = [set(c) for c in itertools.combinations(days, 4)] if len(days) > 4 else []
        self.solver = None  # kabul edilen son yerleşimin çözücüsü
        self.values = None
        self.violations = None
        self.rounds = 0

    def _accept(self, solver):
        self.solver = solver
        self.values = list(solver.ResponseProto().solution)
        self.violations = sum(e if isinstance(e, int) else solver.Value(e) for e in self.slacks)

    def _value(self, var):
        return var if isinstance(var, int) else self.values[var.Index()]

    def start(self, placements, seconds=10.0):
        """Başlangıç yerleşimini esnek modelde değerlendirir (yardımcı değişkenler çözücüden). Olmazsa False."""
        candidate = self.model.clone()
        for card in self.problem.cards:
            place = placements.get(card.key)
            var = self.relaxed.x[card.key].get((place.day, place.period)) if place else None
            if var is None:
                return False
            candidate.Add(var == 1)
            for room, rvar in self.relaxed.y.get(card.key, {}).items():
                if not isinstance(rvar, int) and room in place.rooms:
                    candidate.Add(rvar == 1)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = seconds
        solver.parameters.num_workers = self.workers
        if self.stop_handle is not None:
            self.stop_handle.attach(solver)
        if solver.Solve(candidate) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return False
        self._accept(solver)
        return True

    def _round(self, days, seconds):
        candidate = self.model.clone()
        candidate.ClearHints()
        candidate.Add(sum(self.slacks) <= self.violations)
        for index, value in enumerate(self.values):
            candidate.AddHint(candidate.GetIntVarFromProtoIndex(index), value)
        rng = random.Random(self.seed * 7919 + self.rounds)
        stay = []  # yerinde kalırsa küçük ceza alan kartlar: eşit aşımda çözücü yerleşimi gerçekten değiştirir
        for key, slots in self.relaxed.x.items():
            current = next(slot for slot, var in slots.items() if self._value(var))
            if current[0] in days:
                for slot, var in slots.items():
                    if slot[0] not in days and not isinstance(var, int):
                        candidate.Add(var == 0)
                if not isinstance(slots[current], int) and rng.random() < SHAKE_SHARE:
                    stay.append(slots[current])
                continue
            if not isinstance(slots[current], int):
                candidate.Add(slots[current] == 1)
            for var in self.relaxed.y.get(key, {}).values():
                if not isinstance(var, int):
                    candidate.Add(var == self._value(var))
        if stay:
            # Aşım her zaman önce gelir; kalan kartların hepsi yerinde kalsa bile bir aşımdan ucuzdur.
            candidate.Minimize((len(stay) + 1) * sum(self.slacks) + sum(stay))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = seconds
        solver.parameters.num_workers = self.workers
        solver.parameters.random_seed = self.seed + self.rounds
        if self.stop_handle is not None:
            self.stop_handle.attach(solver)
        status = solver.Solve(candidate, _StopAtZero([e for e in self.slacks if not isinstance(e, int)]))
        return solver, status

    def run(self, deadline, stall_cycles=DAY_STALL_CYCLES, on_improve=None):
        """Süre bitene, aşım sıfırlanana ya da `stall_cycles` tam turda iyileşme olmayana kadar."""
        rng = random.Random(self.seed)
        idle = 0
        used = {}
        while self.violations and idle < stall_cycles:
            before = self.violations
            combos = [(c, DAY_ROUND) for c in self.combos]
            if idle:  # bir tam tur iyileşmesiz geçti: 4 günlük gruplar da denenir
                combos += [(c, DAY_ROUND_WIDE) for c in self.wide]
            for _ in range(len(combos)):
                # İhlalli çiftlerin günlerini içeren gruplar önce; aynı öncelikte en az denenen, eşitlikte rastgele.
                hot = self._hot_days()
                days, seconds = min(combos, key=lambda item: (-len(hot & item[0]), used.get(frozenset(item[0]), 0),
                                                             rng.random()))
                used[frozenset(days)] = used.get(frozenset(days), 0) + 1
                remaining = deadline - time.monotonic()
                if remaining < 1 or not self.violations or (self.stop_handle and self.stop_handle.stopped):
                    return self.violations
                self.rounds += 1
                solver, status = self._round(days, min(seconds, remaining))
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    previous = self.violations
                    self._accept(solver)  # eşit aşımlı farklı yerleşim de kabul: sonraki turlara yol açar
                    if self.on_progress:
                        self.on_progress({"phase": "repair", "method": "days", "round": self.rounds,
                                          "violations": self.violations})
                    if self.violations < previous and on_improve:
                        on_improve(self.violations)
            idle = idle + 1 if self.violations >= before else 0
        return self.violations

    def _hot_days(self):
        """Kesin eşleşmeli kuralı (art arda, aynı gün/saat) bozulan kart çiftlerinin bugünkü günleri."""
        slot = {key: next(s for s, var in slots.items() if self._value(var)) for key, slots in self.relaxed.x.items()}
        cards = self.problem.cards
        hot = set()
        for rel in self.problem.relationships:
            if rel.weight is not None or rel.condition not in PAIRED or len(rel.groups) < 2:
                continue
            for other in rel.groups[1:]:
                for a, b in zip(rel.groups[0], other):
                    (da, pa), (db, pb) = slot[a], slot[b]
                    if rel.condition == "same_time":
                        ok = (da, pa) == (db, pb)
                    elif rel.condition == "same_day":
                        ok = da == db
                    elif rel.condition == "consecutive_ordered":
                        ok = da == db and pa + cards[a].length == pb
                    else:
                        ok = da == db and (pa + cards[a].length == pb or pb + cards[b].length == pa)
                    if not ok:
                        hot.update((da, db))
        return hot

    def placement_objects(self, original=None):
        """{kart: Placement} bütün derslikleriyle; derslikleri değişmeyen kartın ana dersliği aynı kalır."""
        from .cpsat import Placement

        original = original or {}
        out = {}
        for key, slots in self.relaxed.x.items():
            slot = next(s for s, var in slots.items() if self._value(var))
            rooms = [r for r, var in self.relaxed.y.get(key, {}).items() if self._value(var)]
            before = original.get(key)
            if before is not None and set(before.rooms) == set(rooms):
                rooms = list(before.rooms)
            out[key] = Placement(slot[0], slot[1], rooms[0] if rooms else None, tuple(rooms[1:]))
        return out

    def placements(self):
        out = {}
        for key, slots in self.relaxed.x.items():
            slot = next(s for s, var in slots.items() if self._value(var))
            rooms = [r for r, var in self.relaxed.y.get(key, {}).items() if self._value(var)]
            out[key] = (slot[0], slot[1], rooms[0] if rooms else None)
        return out


def repair_search(problem, builder, model, time_limit, started, workers, seed, on_progress, stop_handle,
                  draft_until=0.7, fix_until=0.75, stall_seconds=None):
    """cpsat.solve'un onarım yolu (gen2.repair_search ile aynı arayüz). stall_seconds: otomatik sürede, bu kadar
    saniye yeni en düşük aşım bulunamazsa en iyi taslakla durulur."""
    deadline = started + float(time_limit)
    state = {"best": None, "improved": time.monotonic()}
    info = {"turns": []}  # gen2.repair_search özetinin üstüne eklenir; "rounds" Gen2 turlarıdır
    days = None

    def improve(violations):
        if state["best"] is None or violations < state["best"]:
            state["best"], state["improved"] = violations, time.monotonic()

    def progress(p):
        if "violations" in p:
            improve(p["violations"])
        if on_progress:
            # Gen2 bölümünün kendi süre bütçesi gösterilmez; ilerleme çubuğu üretimin toplam süresine göre ilerler.
            on_progress({k: v for k, v in p.items() if k not in ("budget_seconds", "extension_seconds", "extensions")})

    def stopped():
        return bool(stop_handle and stop_handle.stopped)

    def stalled():
        return stall_seconds is not None and time.monotonic() - state["improved"] > stall_seconds

    turn = 0
    while True:
        now = time.monotonic()
        if deadline - now < 1 or stopped() or stalled():
            break
        # 1) Gen2 turları: ilk bölümde sıfırdan taslak kurar, sonrakilerde en iyi taslaktan (ipucu) başlar.
        guard = _StallGuard(stop_handle, state, GEN2_STALL)
        first, callback, gen_info = gen2.repair_search(problem, builder, model, min(GEN2_SLICE, deadline - now), now,
                                                       workers, seed + turn, progress, guard)
        info["turns"].append({"method": "gen2", "status": gen_info.get("status"), "violations": gen_info.get("violations")})
        if callback.found or gen_info.get("status") == "infeasible":
            info.update(gen_info)  # Gen2 özeti (durum, aşım, süre) + dönüşüm turları
            return first, callback, info
        if getattr(builder, "best_draft", None) is None or stopped():
            break
        improve(builder.best_draft[0])
        # 2) Gün komşuluğu en iyi taslaktan devam eder.
        if deadline - time.monotonic() < 5 or stalled():
            break
        if days is None:
            days = DayRepair(problem, workers, seed, stop_handle, progress)
        if not days.start(builder.best_draft_solution.placements):
            info["turns"].append({"method": "days", "status": "start_failed"})
            break
        days.run(deadline, on_improve=improve)
        info["turns"].append({"method": "days", "violations": days.violations, "rounds": days.rounds})
        if days.violations < builder.best_draft[0]:
            builder.best_draft = (days.violations, {k: p[:2] for k, p in days.placements().items()})
            builder.best_draft_solution = _relaxed_solution(problem, days.relaxed, days.solver, days.violations)
        # Sonraki Gen2 bölümü (ya da sıfırda kesin doğrulama) bu yerleşimden başlar; Gen2 ipucunu ancak her kartta
        # (sabitler dahil) varsa kullanır.
        placed = days.placements()
        for card in problem.cards:
            card.hint = placed[card.key]
        if days.violations == 0:
            first, callback, gen_info = gen2.repair_search(problem, builder, model, max(30.0, deadline - time.monotonic()),
                                                           time.monotonic(), workers, seed, progress, stop_handle)
            info.update(gen_info)  # Gen2 özeti (durum, aşım, süre) + dönüşüm turları
            return first, callback, info
        turn += 1
    info["status"] = "stopped" if stopped() else "unknown"
    info["stalled"] = stalled()
    return None, _FirstSolution(None), info
