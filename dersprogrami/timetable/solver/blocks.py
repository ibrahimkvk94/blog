"""Gen3: kesin eşleşmeli ilişkileri ortak yerleşim seçenekleri olarak kurar.

Kurallar esnetilmez. Çok büyük bileşenler kesilip eksik seçeneklerle çözülmez; o bileşen
standart kesin kısıtlarla korunur. Sonuç ayrıca bağımsız doğrulayıcıdan geçer.
"""

import time
from collections import defaultdict
from dataclasses import replace

from ortools.sat.python import cp_model

from . import cpsat
from .validate import validate

PAIRED = {"same_time", "same_day", "consecutive", "consecutive_ordered"}


def _compatible(condition, a, sa, b, sb):
    if sa[0] != sb[0]:
        return False
    if condition == "same_day":
        return True
    if condition == "same_time":
        return sa == sb
    return sa[1] + a.length == sb[1] or (
        condition == "consecutive" and sb[1] + b.length == sa[1])


def block_options(problem, max_options=10000, max_nodes=100000, deadline=None, stopped=None):
    """(kart anahtarları, tüm geçerli ortak yerleşimler) listesi ve geri dönüş sayısı.

    None seçenek listesi bir hesaplama sınırına ulaşılmasını, boş liste kanıtlanmış
    uyumsuzluğu gösterir. Hesaplama sınırı hiçbir zaman imkânsızlık diye sunulmaz.
    """
    cards = {c.key: c for c in problem.cards}
    adjacent = defaultdict(list)
    for rel in problem.relationships:
        if rel.weight is not None or rel.condition not in PAIRED or len(rel.groups) < 2:
            continue
        for other in rel.groups[1:]:
            for a, b in zip(rel.groups[0], other):
                edge = (a, b, rel.condition)
                adjacent[a].append(edge)
                adjacent[b].append(edge)
    seen, blocks = set(), []
    for root in sorted(adjacent):
        if root in seen:
            continue
        component, pending = set(), [root]
        while pending:
            key = pending.pop()
            if key in component:
                continue
            component.add(key)
            pending.extend(b if a == key else a for a, b, _ in adjacent[key])
        seen.update(component)
        keys = tuple(sorted(component))
        # Uzun zincirde Python özyineleme sınırına yaklaşmadan tam modele dön.
        if len(keys) > 100:
            blocks.append((keys, None))
            continue
        domains = {k: sorted({cards[k].fixed} if cards[k].fixed is not None else set(cards[k].starts)) for k in keys}
        assignment, options, visits = {}, [], 0

        def search():
            nonlocal visits
            visits += 1
            if (visits > max_nodes or len(options) >= max_options
                    or (deadline is not None and time.monotonic() >= deadline)
                    or (stopped is not None and stopped())):
                raise OverflowError
            if len(assignment) == len(keys):
                options.append(tuple(assignment[k] for k in keys))
                return
            # Önce atanan bir komşusu olan ve en az adayı kalan kartı seç.
            candidates = []
            for k in keys:
                if k in assignment:
                    continue
                allowed = []
                for slot in domains[k]:
                    assignment[k] = slot
                    if all(a not in assignment or b not in assignment or
                           _compatible(cond, cards[a], assignment[a], cards[b], assignment[b])
                           for a, b, cond in adjacent[k]):
                        allowed.append(slot)
                    del assignment[k]
                candidates.append((len(allowed), k, allowed))
            _, key, allowed = min(candidates)
            for slot in allowed:
                assignment[key] = slot
                search()
                del assignment[key]

        try:
            search()
        except OverflowError:
            options = None  # Kısmi listeyi kullanmak geçerli çözümleri kaybettirirdi.
        blocks.append((keys, options))
    return blocks


class BlockBuilder(cpsat._Builder):
    def __init__(self, problem, deadline=None, stopped=None, max_options=10000):
        super().__init__(problem)
        self.deadline, self.stopped, self.max_options = deadline, stopped, max_options
        self.block_stats = {}

    def placement_vars(self):
        super().placement_vars()
        blocks = block_options(self.problem, max_options=self.max_options, deadline=self.deadline, stopped=self.stopped)
        self.block_stats = {"blocks": sum(rows is not None for _, rows in blocks),
                            "block_cards": sum(len(keys) for keys, rows in blocks if rows is not None),
                            "block_options": sum(len(rows) for _, rows in blocks if rows is not None),
                            "fallback_blocks": sum(rows is None for _, rows in blocks)}
        for index, (keys, rows) in enumerate(blocks):
            if rows is None:
                continue
            choices = [self.m.NewBoolVar(f"block{index}_{i}") for i in range(len(rows))]
            self.m.AddExactlyOne(choices)
            for position, key in enumerate(keys):
                projection = defaultdict(list)
                for row, choice in zip(rows, choices):
                    projection[row[position]].append(choice)
                for slot, var in self.x[key].items():
                    self.m.Add(var == sum(projection[slot]))

    def lesson_spread(self):
        # Kart ilişkileri kimliğe bağlıdır: aynı dersin kartları her zaman birbirinin
        # yerine geçmez. Gen3, kanıtlanmamış sıralama/simetri kısıtları eklemez.
        by_lesson = defaultdict(list)
        for card in self.problem.cards:
            by_lesson[card.lesson_id].append(card.key)
        for lesson, keys in by_lesson.items():
            limit = self.problem.lesson_max_per_day.get(lesson, len(keys))
            for day in range(self.problem.days):
                self.m.Add(sum(self._day_terms(keys, day)) <= limit)


def solve(problem, time_limit=1800, workers=None, seed=0, on_progress=None, stop_handle=None, should_stop=None, log=False):
    started = time.monotonic()
    deadline = started + time_limit
    stopped = lambda: bool((stop_handle and stop_handle.stopped) or (should_stop and should_stop()))
    if on_progress:
        on_progress({"phase": "blocks", "stage": "build"})
    builder = BlockBuilder(problem, deadline=deadline, stopped=stopped)
    model = builder.build()
    model.ClearObjective()  # Önce yalnızca kesin kuralları sağlayan ilk yerleşimi bul.
    info = {"algorithm": "gen3", **builder.block_stats}
    if stopped() or time.monotonic() >= deadline:
        return cpsat.Solution(status="unknown", stats={**info, "stopped": stopped(), "wall_time": time.monotonic() - started})
    if on_progress:
        on_progress({"phase": "blocks", "stage": "search", **builder.block_stats})
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, deadline - time.monotonic())
    solver.parameters.num_workers = workers or cpsat.default_workers()
    solver.parameters.random_seed = seed
    solver.parameters.log_search_progress = log
    if stop_handle:
        stop_handle.attach(solver)
    callback = cpsat._FirstSolution(on_progress)
    status = solver.Solve(model, callback)
    result = cpsat.Solution(status=cpsat.STATUS_NAMES.get(status, "unknown"), stats={
        **info, "wall_time": round(time.monotonic() - started, 2), "stopped": stopped(), "cards": len(problem.cards)})
    if not result.ok:
        return result
    result.placements = cpsat._placements(builder, solver, problem)
    result.teacher_choice = {lesson: next(t for t, v in choices.items() if solver.Value(v))
                             for lesson, choices in builder.z.items()}
    checked_problem = replace(problem, cards=[
        replace(c, teachers=(result.teacher_choice[c.lesson_id],)) if c.lesson_id in result.teacher_choice else c
        for c in problem.cards])
    violations, counts = validate(checked_problem, result.placements)
    hard = [v for v in violations if v.level == "hard"]
    result.stats["validation"] = {**counts, "hard": len(hard)}
    if hard:
        result.status = "invalid"
        result.stats["error"] = "Blok çözümü bağımsız denetimden geçemedi."
        result.placements = {}
        return result
    result.objective = cpsat._objective(solver, builder)
    for category, weight, expr in builder.penalties:
        value = expr if isinstance(expr, int) else solver.Value(expr)
        if value:
            result.penalties[category] = result.penalties.get(category, 0) + weight * value
    return result
