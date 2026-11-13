"""Gen2: en iyi taslağı koruyan, günler arası kaynak komşuluklarını yeniden çözen üretim.

Kesin kurallar standart katı model ve bağımsız doğrulayıcıyla denetlenir. KAMYO gibi
sıkışık programlarda önceki taslağı kaybetmeden onarım yapar; sıfır ihlal garantisi vermez.
"""

import time

from ortools.sat.python import cp_model

from .cpsat import (
    RELAXED, STATUS_NAMES, _Builder, _DraftRound, _FirstSolution, _relaxed_solution,
)

DRAFT_FIRST_SHARE = 0.25
DRAFT_ROUND_SHARE = 0.08


class _SearchBudget:
    """Son dakikadaki ilerleme ilk uzatmayı, uzatmadaki her rekor bir dakika daha açar."""

    def __init__(self, started, seconds):
        self.started = started
        self.base_deadline = started + seconds
        self.deadline = self.base_deadline
        self.extensions = 0
        self.best = None

    def observe(self, violations, now):
        previous = self.best
        if previous is not None and violations >= previous:
            return
        self.best = violations
        # İlk taslak bir karşılaştırma noktasıdır; sıfırda hedefe ulaşıldığından uzatma gerekmez.
        if previous is None or violations == 0 or now >= self.deadline:
            return
        if now >= self.base_deadline:
            self.extensions += 1
            self.deadline += 60
        elif now >= self.base_deadline - 60 and self.extensions == 0:
            self.extensions = 1
            self.deadline += 60

    def stats(self):
        return {"budget_seconds": round(self.deadline - self.started, 1),
                "extension_seconds": self.extensions * 60, "extensions": self.extensions}


class _TimedDraftRound(_DraftRound):
    def __init__(self, on_progress, round_no, best, budget):
        super().__init__(on_progress, round_no, best)
        self.budget = budget

    def on_solution_callback(self):
        self.budget.observe(int(round(self.ObjectiveValue())), time.monotonic())
        super().on_solution_callback()


def _violation_neighbourhood(problem, relaxed, solver, turn=0, depth=2):
    """Bir ihlalin etrafındaki kaynak komşuluğu; günler arası değiş tokuşa da izin verir.

    Bütün ihlalleri aynı anda serbest bırakmak neredeyse sıfırdan aramaya dönüşür. Her tur başka
    ihlal seçilir; aynı öğretmen/öğrenci/olası dersliği paylaşan kartlarla alan genişletilir.
    Kesin eşleşmeli ilişkilerin diğer uçları da alana katılır.
    """
    value = lambda v: v if isinstance(v, int) else solver.Value(v)  # noqa: E731
    targets = []
    by_teacher, by_class, by_lesson = {}, {}, {}
    for card in problem.cards:
        by_lesson.setdefault(card.lesson_id, []).append(card.key)
        for t in card.teachers:
            by_teacher.setdefault(t, []).append(card.key)
        for atom in card.atoms:
            by_class.setdefault(problem.atom_class(atom), []).append(card.key)
    for rule, _label, expr in relaxed.relaxed_slacks:
        if not value(expr) or not isinstance(rule, tuple):
            continue
        kind, ref = rule[0], rule[1]
        seeds = set()
        if kind == "rel" and ref < len(problem.relationships):
            spec = problem.relationships[ref]
            seeds.update(k for group in list(spec.groups) + list(spec.groups_b) for k in group)
        elif kind == "spread":
            seeds.update(by_lesson.get(ref, ()))
        elif kind.startswith("teacher"):
            seeds.update(by_teacher.get(ref, ()))
        elif kind.startswith("class"):
            seeds.update(by_class.get(ref, ()))
        if seeds and seeds not in targets:
            targets.append(seeds)
    if not targets:
        return set(relaxed.x)
    resources, card_resources = {}, {}
    pools = problem.pooled_lessons()
    for card in problem.cards:
        teachers = set(card.teachers)
        if card.lesson_id in pools:
            teachers.update(pools[card.lesson_id].quotas)
        res = {("t", t) for t in teachers} | {("a", a) for a in card.atoms}
        res |= {("s", s) for s in card.students} | {("r", r) for r in card.room_options}
        card_resources[card.key] = res
        for item in res:
            resources.setdefault(item, set()).add(card.key)
    loose = set(targets[turn % len(targets)])
    for _ in range(depth):
        for key in list(loose):
            for item in card_resources[key]:
                loose.update(resources[item])
    pairs = [(a, b) for rel in problem.relationships
             if rel.weight is None and rel.condition in ("same_time", "same_day", "consecutive", "consecutive_ordered")
             and rel.groups for group in rel.groups[1:] for a, b in zip(rel.groups[0], group)]
    while True:
        before = len(loose)
        for a, b in pairs:
            if a in loose or b in loose:
                loose.update((a, b))
        if len(loose) == before:
            break
    return loose


def _hinted_draft(problem, relaxed, model, seconds, workers, stop_handle):
    """Tam başlangıç yerleşimini kısa bir tamamlamayla güvenceye al; yalnızca ipucuna güvenme.

    Yardımcı değişkenler ve ihlal miktarları çözücü tarafından hesaplanır. Girdiler değiştiyse
    ya da kaynak çakışması varsa bu kısıtlı denemenin başarısızlığı asıl probleme taşınmaz.
    """
    if seconds <= 0 or not problem.cards or any(c.hint is None for c in problem.cards):
        return None
    candidate = model.clone()
    for card in problem.cards:
        var = relaxed.x[card.key].get(card.hint[:2])
        if var is None:
            return None
        candidate.Add(var == 1)
        room = relaxed.y.get(card.key, {}).get(card.hint[2])
        if room is not None and not isinstance(room, int):
            candidate.Add(room == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = workers
    if stop_handle is not None:
        stop_handle.attach(solver)
    status = solver.Solve(candidate)
    return solver if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None


def _draft_neighbourhood_model(model, relaxed, best, loose):
    """Yalnızca seçili alanı aç, geri kalan yerleşimi sabitle; en iyi aşımı geçme.

    Eşit kalitede çözümler kabul edilir: farklı bir yerleşim sonraki turda ilerleme sağlayabilir.
    Her tur temiz kopya kullanır; önceki turların sabitlemeleri birikmez.
    """
    candidate = model.clone()
    candidate.ClearHints()
    candidate.Add(sum(expr for _, _, expr in relaxed.relaxed_slacks) <= best[0])
    for index, value in enumerate(best[1]):
        candidate.AddHint(candidate.GetIntVarFromProtoIndex(index), value)
    for key, slots in relaxed.x.items():
        if key in loose:
            continue
        for var in slots.values():
            if best[2].Value(var):
                candidate.Add(var == 1)
        for var in relaxed.y.get(key, {}).values():
            if not isinstance(var, int):
                candidate.Add(var == best[2].Value(var))
    return candidate


def repair_search(problem, builder, model, time_limit, started, workers, seed, on_progress, stop_handle,
                   draft_until=0.7, fix_until=0.75):
    """1. aşamanın yedeği: önce her dersin yerleştiği, kesin kural aşımı en az bir taslak kurulur (esnek model:
    her kart yerleşmek zorunda, kurallar cezalı); sonra taslak turlarla onarılır ve aşımı sıfırlanan taslak katı
    modele aktarılır. (çözücü, geri çağırma, özet) döner.

    Turlar: her tur en iyi taslaktan başlar; sorunlu bölgenin dışı sabitlenir, toplam aşım artırılamaz.
    Tıkandığında farklı ihlal ve daha geniş komşuluk denenir. Ana sürenin son dakikasında ilerleme varsa
    bir dakika uzar; uzatmada her yeni rekor bir dakika daha ekler. Sıfırda katı doğrulamaya geçer.
    draft_until/fix_until, ortak çağrı arayüzü için kabul edilir; Gen2 ana sürenin tamamını kullanır."""
    budget = _SearchBudget(started, float(time_limit))
    notify = on_progress

    def on_progress(progress):
        if notify:
            notify({**progress, **budget.stats()})

    if on_progress:
        on_progress({"phase": "repair"})
    info = {"rounds": []}
    relaxed = _Builder(problem, RELAXED, place_all=True)
    relaxed_model = relaxed.build()
    # Taslakta yalnızca kural aşımı en aza indirilir (tercih cezaları kesin kurallar sağlandıktan sonraya kalır).
    slacks = [expr for _, _, expr in relaxed.relaxed_slacks]
    relaxed_model.Minimize(sum(slacks))
    best = None  # (aşım, çözüm vektörü)
    round_seed, round_no, stalls = seed, 0, 0
    draft = None
    initial = _hinted_draft(problem, relaxed, relaxed_model,
                            min(5.0, max(0.0, budget.deadline - time.monotonic())), workers, stop_handle)
    if initial is not None:
        best = (int(round(initial.ObjectiveValue())), list(initial.ResponseProto().solution), initial)
        draft = initial
        budget.observe(best[0], time.monotonic())
        info["rounds"].append({"round": 0, "violations": best[0], "seed": seed,
                               "time": round(initial.WallTime(), 1), "initial": True})
        if on_progress:
            on_progress({"phase": "repair", "round": 0, "violations": best[0]})
    while True:
        remaining = budget.deadline - time.monotonic()
        if remaining < 0.1 or (best is not None and best[0] == 0) or (stop_handle and stop_handle.stopped):
            break
        round_no += 1
        floor, share = (30.0, DRAFT_FIRST_SHARE) if best is None else (10.0, DRAFT_ROUND_SHARE)
        draft = cp_model.CpSolver()
        draft.parameters.num_workers = workers
        draft.parameters.random_seed = round_seed
        candidate = relaxed_model
        loose = set(relaxed.x)
        if best is not None:
            # Küçük alan yetmezse genişlet; düzenli olarak tüm kartları açarak komşuluk sınırından çık.
            if round_no % 6:
                loose = _violation_neighbourhood(problem, relaxed, best[2], turn=round_no - 1,
                                                 depth=2 + min(1, stalls // 6))
            candidate = _draft_neighbourhood_model(relaxed_model, relaxed, best, loose)
            draft.parameters.use_lns_only = True
        remaining = budget.deadline - time.monotonic()
        if remaining < 0.1:
            break
        draft.parameters.max_time_in_seconds = min(remaining, max(floor, float(time_limit) * share))
        if stop_handle is not None:
            stop_handle.attach(draft)
        status = draft.Solve(candidate, _TimedDraftRound(on_progress, round_no, best[0] if best else None, budget))
        row = {"round": round_no, "status": STATUS_NAMES.get(status, "unknown"), "seed": round_seed,
               "time": round(draft.WallTime(), 1), "lns": bool(draft.parameters.use_lns_only), "free_cards": len(loose)}
        info["rounds"].append(row)
        if status == cp_model.INFEASIBLE and best is None:  # kurallar esnese bile kartlar sığmıyor
            info.update(status="infeasible", draft="infeasible", **budget.stats())
            return draft, _FirstSolution(None), info
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            violations = int(round(draft.ObjectiveValue()))
            row["violations"] = violations
            improved = best is None or violations < best[0]
            if best is None or violations <= best[0]:
                best = (violations, list(draft.ResponseProto().solution), draft)
            if improved:
                stalls = 0
            else:
                stalls += 1
            if best[0] == 0:
                break
        else:
            stalls += 1
        round_seed += 1
    info["draft_time"] = round(time.monotonic() - started, 2)
    info.update(budget.stats())
    if best is None:
        info["status"] = "no_draft"
        return draft, _FirstSolution(None), info
    info["draft"] = "optimal" if best[0] == 0 else "feasible"
    info["violations"] = best[0]
    values = best[1]
    value = lambda v: v if isinstance(v, int) else values[v.Index()]  # noqa: E731
    previous = getattr(builder, "best_draft", None)
    if previous is None or best[0] < previous[0]:
        builder.best_draft = (best[0], {key: slot for key, slots in relaxed.x.items() for slot, v in slots.items() if value(v)})
        builder.best_draft_solution = _relaxed_solution(problem, relaxed, best[2], best[0])
    if stop_handle and stop_handle.stopped:
        info["status"] = "stopped"
        return draft, _FirstSolution(None), info
    if best[0]:
        # Süre bitti: ek bir arama başlatmadan eldeki en iyi taslağı teslim et.
        info["status"] = "unknown"
        return best[2], _FirstSolution(None), info
    # Katı model özdeş kartları başlangıç sırasına dizer; taslakta sıra farklı olabilir, kartlar ona göre eşlenir.
    source = {key: key for key in builder.x}
    first_slot = {key: min((slot for slot, v in slots.items() if value(v)), default=(99, 99)) for key, slots in relaxed.x.items()}
    for chain in builder.chains:
        for key, other in zip(chain, sorted(chain, key=first_slot.get)):
            source[key] = other
    pairs = []  # (katı modeldeki değişken, taslaktaki değeri)
    for key, slots in builder.x.items():
        chosen = relaxed.x.get(source[key], {})
        pairs += [(var, int(slot in chosen and value(chosen[slot]))) for slot, var in slots.items()]
    for key, rooms in builder.y.items():
        chosen = relaxed.y.get(source[key], {})
        pairs += [(var, int(room in chosen and value(chosen[room]))) for room, var in rooms.items()]
    for lesson_id, zs in builder.z.items():
        chosen = relaxed.z.get(lesson_id, {})
        pairs += [(var, int(teacher in chosen and value(chosen[teacher]))) for teacher, var in zs.items()]
    pairs = [(var, v) for var, v in pairs if not isinstance(var, int)]
    feasibility = model.clone()
    feasibility.ClearObjective()
    feasibility.ClearHints()
    if not info["violations"]:
        # Taslak hiçbir kuralı aşmıyor: yerleşim sabitlenip yalnızca yardımcı değişkenler tamamlanır (saniyeler sürer).
        for var, v in pairs:
            feasibility.Add(feasibility.GetIntVarFromProtoIndex(var.Index()) == v)
    else:
        for var, v in pairs:
            feasibility.AddHint(feasibility.GetIntVarFromProtoIndex(var.Index()), v)
    fixer = cp_model.CpSolver()
    # Sıfır ihlalli sabit yerleşimin yardımcı değişkenlerini tamamlamak için kısa doğrulama payı.
    fixer.parameters.max_time_in_seconds = min(10.0, max(1.0, float(time_limit)))
    fixer.parameters.num_workers = workers
    fixer.parameters.random_seed = seed
    # repair_hint burada kullanılmaz: amaç fonksiyonu olmayan kopya modelde OR-Tools'u çökertebiliyor
    # ("heuristics.fixed_search"); ipucu yine aramayı yönlendirir.
    if stop_handle is not None:
        stop_handle.attach(fixer)
    callback = _FirstSolution(on_progress)
    status = fixer.Solve(feasibility, callback)
    info["status"] = STATUS_NAMES.get(status, "unknown")
    if status == cp_model.INFEASIBLE and not info["violations"]:
        info["status"] = "unknown"  # sabitlenen taslak tamamlanamadı; bu, kuralların imkânsız olduğunu göstermez
    info["wall_time"] = round(fixer.WallTime(), 2)
    return fixer, callback, info
