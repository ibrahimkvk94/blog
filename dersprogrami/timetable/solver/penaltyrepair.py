"""Ana görünümde "Cezayı düşür": var olan programın yumuşak cezasını gün komşuluğuyla azaltır.

Model üretimdeki amaçla aynıdır (esnek model, ceza ağırlıkları cpsat.py'den). Her turda 2–3 günün kilitsiz
kartları serbest kalır, diğer günler yerinde sabittir; kesin ihlal sayısı artamaz, bekleyen kartlar bekler,
yerleşmiş kart yerleşik kalır. Tur ancak ceza azalırsa kabul edilir, bu yüzden sonuç hiçbir zaman daha kötü
olmaz. Kilitli kartlar modelde zaten tek hücreye bağlıdır.
"""

import itertools
import random
import time

from ortools.sat.python import cp_model

from .cpsat import RELAXED, Placement, _Builder

ROUND = 12.0  # bir turun en uzun süresi
SKIP = ("moved", "moved_room")  # çözüm merkezinin "yerinden oynayan kart" cezaları üretimin amacında yoktur


def _fix(model, variables, value):
    for var in variables:
        if not isinstance(var, int):  # sabit (kilitli kart, tek derslik) değişken modelde zaten bağlı
            model.Add(var == value)


class PenaltyRepair:
    def __init__(self, problem, workers, seed=0):
        self.problem = problem
        self.workers = workers
        self.seed = seed
        self.builder = _Builder(problem, RELAXED)
        self.model = self.builder.build()
        self.slacks = [e for _, _, e in self.builder.relaxed_slacks]
        self.terms = [(w, e) for c, w, e in self.builder.penalties if c not in SKIP]
        self.model.Minimize(sum(w * e for w, e in self.terms))
        days = sorted({d for slots in self.builder.x.values() for d, _ in slots})
        self.combos = [set(c) for size in (2, 3) if size <= len(days) for c in itertools.combinations(days, size)]
        self.original = {}
        self.values = None
        self.violations = None
        self.penalty = None
        self.rounds = 0

    def _value(self, var):
        return var if isinstance(var, int) else self.values[var.Index()]

    def _accept(self, solver):
        self.values = list(solver.ResponseProto().solution)
        value = lambda e: e if isinstance(e, int) else solver.Value(e)  # noqa: E731 (ifade de olabilir)
        self.violations = sum(value(e) for e in self.slacks)
        self.penalty = sum(w * value(e) for w, e in self.terms)

    def _solver(self, seconds):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = seconds
        solver.parameters.num_workers = self.workers
        solver.parameters.random_seed = self.seed + self.rounds
        return solver

    def start(self, placements, seconds=15.0):
        """Programı modelde değerlendirir (ceza değişkenleri en küçük değerlerini alır). Olmazsa False."""
        self.original = placements
        candidate = self.model.clone()
        for card in self.problem.cards:
            place = placements.get(card.key)
            slots = self.builder.x[card.key]
            if place is None:
                _fix(candidate, slots.values(), 0)
                continue
            var = slots.get((place.day, place.period))
            if var is None:
                return False
            _fix(candidate, [var], 1)
            _fix(candidate, [v for room, v in self.builder.y.get(card.key, {}).items() if room in place.rooms], 1)
        solver = self._solver(seconds)
        if solver.Solve(candidate) != cp_model.OPTIMAL:
            return False
        self._accept(solver)
        return True

    def _round(self, days, seconds):
        candidate = self.model.clone()
        candidate.ClearHints()
        for index, value in enumerate(self.values):
            candidate.AddHint(candidate.GetIntVarFromProtoIndex(index), value)
        candidate.Add(sum(self.slacks) <= self.violations)
        for key, slots in self.builder.x.items():
            current = next((slot for slot, var in slots.items() if self._value(var)), None)
            if current is None:  # bekleyen kart bekler
                _fix(candidate, slots.values(), 0)
                continue
            if current[0] in days:
                _fix(candidate, [var for slot, var in slots.items() if slot[0] not in days], 0)
                continue
            _fix(candidate, [slots[current]], 1)
            for var in self.builder.y.get(key, {}).values():
                _fix(candidate, [var], self._value(var))
        solver = self._solver(seconds)
        return solver, solver.Solve(candidate)

    def run(self, deadline):
        """Süre bitene kadar gün gruplarını sırayla dener; her grup bir kez denenince sıra karışır."""
        rng = random.Random(self.seed)
        order = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining < 2 or not self.penalty:
                return self.penalty
            if not order:
                order = list(self.combos)
                rng.shuffle(order)
            days = order.pop()
            self.rounds += 1
            solver, status = self._round(days, min(ROUND, remaining))
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and solver.ObjectiveValue() <= self.penalty:
                self._accept(solver)

    def placements(self):
        out = {}
        for key, slots in self.builder.x.items():
            slot = next((s for s, var in slots.items() if self._value(var)), None)
            if slot is None:
                continue
            rooms = [r for r, var in self.builder.y.get(key, {}).items() if self._value(var)]
            before = self.original.get(key)
            if before is not None and set(before.rooms) == set(rooms):
                rooms = list(before.rooms)  # derslikler değişmediyse ana derslik de aynı kalır
            out[key] = Placement(slot[0], slot[1], rooms[0] if rooms else None, tuple(rooms[1:]))
        return out
