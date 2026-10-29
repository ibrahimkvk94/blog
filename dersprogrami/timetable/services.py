"""Uygulama katmanı: denetim, üretim ve doğrulama işlemlerini veritabanına bağlar."""

from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import editing, jobs, versions
from .models import Card, Timetable
from .solver import cpsat, feasibility
from .solver.builder import build_problem
from .solver.cpsat import Placement
from .solver.validate import validate

STALE_GRACE = timedelta(seconds=90)


def check_school(school):
    from .problem_cache import school_problem

    return feasibility.check(school_problem(school))


def start_generation(school, name, time_limit=None, mode=Timetable.STRICT, base=None, seed=0, only=None):
    """Yeni bir program sürümü oluşturur ve üretimi arka planda başlatır.

    only: {"classes": [...], "teachers": [...]} — yalnızca bunların kartları yeniden yerleşir, diğerleri
    başlangıç sürümündeki yerinde sabitlenir (kısmi üretim; büyük programlarda çok daha hızlı)."""
    timetable = Timetable.objects.create(
        school=school,
        name=name,
        status=Timetable.RUNNING,
        mode=mode,
        time_limit=time_limit or settings.TIMETABLE_SOLVER_TIME_LIMIT,
        started_at=timezone.now(),
        report={"base": base.pk if base else None, **({"only": only} if only and any(only.values()) else {})},
    )
    jobs.start(timetable.pk, run_generation, base.pk if base else None, seed)
    return timetable


def generate_timetable(school, name, time_limit=None, base=None, seed=0, mode=Timetable.STRICT):
    """Programı eşzamanlı üretir (komut satırı ve testler için)."""
    timetable = Timetable.objects.create(
        school=school,
        name=name,
        status=Timetable.RUNNING,
        mode=mode,
        time_limit=time_limit or settings.TIMETABLE_SOLVER_TIME_LIMIT,
        started_at=timezone.now(),
    )
    run_generation(timetable.pk, base.pk if base else None, seed)
    timetable.refresh_from_db()
    return timetable


def freeze_except(problem, only):
    """Kısmi üretim: seçilen kısım/öğretmenlere dokunmayan kartları başlangıç yerinde sabitler."""
    classes, teachers = set(only.get("classes") or []), set(only.get("teachers") or [])
    frozen = 0
    for card in problem.cards:
        if card.fixed is not None or card.hint is None:
            continue
        touches = bool(teachers & set(card.teachers)) or bool(classes & {problem.atom_class(a) for a in card.atoms})
        if not touches:
            card.fixed = (card.hint[0], card.hint[1])
            card.fixed_room = card.hint[2]
            frozen += 1
    return frozen


def run_generation(timetable_id, base_id=None, seed=0):
    timetable = Timetable.objects.select_related("school").get(pk=timetable_id)
    base = Timetable.objects.filter(pk=base_id).first() if base_id else None
    relaxed = timetable.mode == Timetable.RELAXED
    report = dict(timetable.report)
    try:
        problem = build_problem(timetable.school, base=base)
        if base is not None and report.get("only"):
            report["frozen"] = freeze_except(problem, report["only"])
        issues = feasibility.check(problem)
        report["issues"] = [i.as_dict() for i in issues]
        if feasibility.has_errors(issues, relaxed=relaxed):
            _finish(timetable, Timetable.FAILED, report)
            return

        solution = cpsat.solve(
            problem,
            time_limit=timetable.time_limit,
            seed=seed,
            mode=timetable.mode,
            on_progress=lambda progress: jobs.set_progress(timetable_id, progress),
            stop_handle=jobs.handle_for(timetable_id),
        )
    except Exception as exc:  # beklenmeyen hatada iş "üretiliyor" durumunda asılı kalmasın
        report["error"] = str(exc)
        _finish(timetable, Timetable.FAILED, report)
        raise

    report["solver"] = {"status": solution.status, **solution.stats}
    report["penalties"] = solution.penalties
    if not solution.ok:
        if solution.status == "unknown":
            report["error"] = "Süre sınırı içinde tüm kuralları sağlayan bir program bulunamadı."
        elif solution.status == "infeasible":
            report["error"] = "Bu verilerle tüm kuralları sağlayan bir program yok."
            jobs.set_progress(timetable_id, {"phase": "explain"})
            report["conflict"] = explain_conflict(
                timetable.school, problem, time_limit=min(180, max(60, timetable.time_limit)), known_infeasible=True
            )
        stopped = solution.stats.get("stopped") or jobs.handle_for(timetable_id).stopped
        if solution.status in ("unknown", "infeasible") and not relaxed and not stopped:
            # Tanı: kurallar ağır cezalı esnetilerek en yakın taslak aranır; hangi kuralların ne kadar
            # esnetildiği ve hangi kartların sığmadığı "neden" raporu olur, taslak da açılabilir program olarak kalır.
            # Önce her kart yerleşmek zorunda, yalnızca kurallar esner ("hangi kural esnemeli?" sorusunun cevabı);
            # kartlar o şekilde de sığmıyorsa tam gevşek mod (sığmayan kartlar da bekler).
            jobs.set_progress(timetable_id, {"phase": "diagnose"})
            budget = min(240, max(60, timetable.time_limit // 3))
            progress = lambda p: jobs.set_progress(timetable_id, {**p, "phase": "diagnose"})  # noqa: E731
            draft = cpsat.solve(problem, time_limit=budget, seed=seed, mode=Timetable.RELAXED, place_all=True,
                                stop_handle=jobs.handle_for(timetable_id), on_progress=progress)
            if not draft.ok and not jobs.handle_for(timetable_id).stopped:
                draft = cpsat.solve(problem, time_limit=budget, seed=seed, mode=Timetable.RELAXED,
                                    stop_handle=jobs.handle_for(timetable_id), on_progress=progress)
            report["diagnosis"] = diagnosis(timetable.school, problem, solution.status, draft)
            if draft.ok:
                report["strict_failed"] = {"status": solution.status, "error": report.pop("error")}
                report["solver"] = {"status": draft.status, **draft.stats, "strict": report["solver"]}
                report["penalties"] = draft.penalties
                Timetable.objects.filter(pk=timetable.pk).update(mode=Timetable.RELAXED)
                solution = draft
        if not solution.ok:
            _finish(timetable, Timetable.FAILED, report)
            return

    _retry_locked(lambda: _save_result(timetable, problem, solution, report))


def _retry_locked(func, attempts=8):
    """SQLite'ta aynı anda biten iki üretimin kaydı çakışırsa ("database is/table is locked") iş asılı kalmasın:
    kısa aralıklarla yeniden dener (işlem atomik olduğundan yarım kayıt kalmaz)."""
    import time

    from django.db import OperationalError

    for attempt in range(attempts):
        try:
            return func()
        except OperationalError as exc:
            if "locked" not in str(exc) or attempt == attempts - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def _save_result(timetable, problem, solution, report):
    with transaction.atomic():
        cards = []
        for card in problem.cards:
            place = solution.placements.get(card.key)
            cards.append(
                Card(
                    timetable=timetable,
                    lesson_id=card.lesson_id,
                    length=card.length,
                    day=place.day if place else None,
                    period=place.period if place else None,
                    classroom_id=place.room if place else None,
                    extra_rooms=list(place.extra_rooms) if place else [],
                    locked=card.fixed is not None,
                )
            )
        Card.objects.bulk_create(cards)
        if solution.teacher_choice:
            report["pools"] = apply_teacher_choice(timetable.school, problem, solution.teacher_choice)
        versions.save_version(timetable, note="Üretim sonucu", auto=True)
        violations, stats = validate(problem, solution.placements)
        report["validation"] = {"violations": [v.as_dict() for v in violations], "stats": stats}
        timetable.objective = solution.objective
        status = Timetable.PARTIAL if solution.unplaced else Timetable.OK
        _finish(timetable, status, report)


def apply_teacher_choice(school, problem, choice):
    """Öğretmen havuzu: çözücünün seçtiği öğretmenleri derslere yazar ve doğrulama için problemdeki kartlara
    işler. Dönüş: rapor özeti {"changed": n, "pools": {ad: {öğretmen: kısım}}}."""
    from collections import Counter

    from .models import Lesson
    from .problem_cache import bump

    current = {}
    for lesson_id, teacher_id in Lesson.teachers.through.objects.filter(lesson_id__in=list(choice)).values_list("lesson_id", "teacher_id"):
        current.setdefault(lesson_id, []).append(teacher_id)
    changed = 0
    for lesson in Lesson.objects.filter(pk__in=list(choice)):
        if current.get(lesson.id) != [choice[lesson.id]]:
            lesson.teachers.set([choice[lesson.id]])
            changed += 1
    for card in problem.cards:
        if card.lesson_id in choice:
            card.teachers = (choice[card.lesson_id],)
    names = problem.labels.get("teacher", {})
    pools = {pool.name: dict(Counter(names.get(choice[l], str(choice[l])) for l in pool.lessons)) for pool in problem.teacher_pools}
    if changed:
        bump(school.pk)
    return {"changed": changed, "pools": pools}


def _finish(timetable, status, report):
    report.pop("progress", None)
    Timetable.objects.filter(pk=timetable.pk).update(
        status=status, report=report, objective=timetable.objective, finished_at=timezone.now()
    )


def request_stop(timetable):
    Timetable.objects.filter(pk=timetable.pk).update(cancel_requested=True)
    jobs.stop(timetable.pk)
    # Sırada bekleyen (henüz başlamamış) iş hemen iptal edilir.
    if Timetable.objects.filter(pk=timetable.pk, job_state="queued").update(job_state=""):
        report = dict(Timetable.objects.get(pk=timetable.pk).report)
        report["error"] = "Üretim sırada beklerken iptal edildi."
        _finish(timetable, Timetable.FAILED, report)


def refresh_stale(timetable):
    """Sunucu yeniden başlatılınca yarıda kalan üretimleri "üretilemedi" olarak işaretler."""
    if timetable.status != Timetable.RUNNING or not timetable.started_at:
        return timetable
    # Çalışan kipte iş başka süreçtedir; bu sürecin bellekteki kaydı bir şey söylemez.
    if jobs.worker_mode():
        if jobs.queued_or_alive(timetable):
            return timetable
        report = dict(timetable.report)
        report["error"] = "Üretim yarıda kesildi (çalışan süreç durmuş olabilir)."
        _finish(timetable, Timetable.FAILED, report)
        timetable.refresh_from_db()
        return timetable
    if jobs.is_alive(timetable.pk):
        return timetable
    if timezone.now() > timetable.started_at + timedelta(seconds=timetable.time_limit) + STALE_GRACE:
        report = dict(timetable.report)
        report["error"] = "Üretim yarıda kesildi (sunucu yeniden başlatılmış olabilir)."
        _finish(timetable, Timetable.FAILED, report)
        timetable.refresh_from_db()
    return timetable


def placements_of(problem, timetable):
    db_cards = {c.id: c for c in timetable.cards.all()}
    placements = {}
    for card in problem.cards:
        db_card = db_cards[card.card_id]
        if db_card.is_placed:
            rooms = db_card.room_ids
            placements[card.key] = Placement(db_card.day, db_card.period, rooms[0] if rooms else None, tuple(rooms[1:]))
    return placements


def verify_timetable(timetable):
    """Kaydedilmiş (elle düzenlenmiş olabilir) bir programı doğrular."""
    from .problem_cache import problem_for

    problem = problem_for(timetable)
    return validate(problem, placements_of(problem, timetable))


def repair_timetable(timetable, time_limit=20):
    """Yerleşmeyen kartları yerleştirir (aSc'deki "bekleyen kartları yerleştir").

    1. adım: yerleşmiş kartlar yerinde sabit, yalnızca bekleyenler yerleşir.
    2. adım (gerekirse): kilitsiz kartlar mevcut yerlerini ipucu alarak yeniden düzenlenir.
    Her iki adım da gevşek modda çalışır; sığmayan kart yine bekleyenlerde kalır.
    """
    problem = build_problem(timetable.school, timetable=timetable)
    placements = placements_of(problem, timetable)
    for card in problem.cards:
        if card.key in placements:
            place = placements[card.key]
            card.fixed, card.fixed_room, card.fixed_rooms = (place.day, place.period), place.room, place.rooms
    solution = cpsat.solve(problem, time_limit=min(time_limit, 10), mode=cpsat.RELAXED)
    step = 1
    if not solution.ok or solution.unplaced:
        problem = build_problem(timetable.school, timetable=timetable)
        solution2 = cpsat.solve(problem, time_limit=time_limit, mode=cpsat.RELAXED)
        if solution2.ok and (not solution.ok or len(solution2.unplaced) < len(solution.unplaced)):
            solution, step = solution2, 2
    if not solution.ok:
        return {"ok": False, "message": "Çözüm bulunamadı."}

    db_cards = {c.id: c for c in timetable.cards.all()}
    updates = []
    for card in problem.cards:
        db_card = db_cards[card.card_id]
        place = solution.placements.get(card.key)
        new = (place.day, place.period, place.room, list(place.extra_rooms)) if place else (None, None, None, [])
        if (db_card.day, db_card.period, db_card.classroom_id, list(db_card.extra_rooms or [])) != new:
            updates.append((db_card, new))
    changed = [db_card for db_card, _ in updates]
    editing.record(timetable, "bekleyenler yerleştirildi", editing.snapshot(changed))
    for db_card, new in updates:
        db_card.day, db_card.period, db_card.classroom_id, db_card.extra_rooms = new
    Card.objects.bulk_update(changed, ["day", "period", "classroom", "extra_rooms"])
    if not solution.unplaced and timetable.status == Timetable.PARTIAL:
        Timetable.objects.filter(pk=timetable.pk).update(status=Timetable.OK)
    return {
        "ok": True,
        "step": step,
        "moved": len(changed),
        "unplaced": len(solution.unplaced),
        "message": f"{len(changed)} kart güncellendi, {len(solution.unplaced)} kart beklemede.",
    }


ENTITY_PAGES = {"teacher": "ogretmenler", "school_class": "siniflar", "subject": "ders-adlari", "classroom": "derslikler"}


def _rule_url(school, problem, key):
    """Açıklamadaki bir kuralın düzeltilebileceği ekranın adresi."""
    kind, target = key
    if kind in ("teacher_max", "teacher_gaps_day", "teacher_gaps_week", "teacher_days", "teacher_consecutive", "teacher_min"):
        return reverse("timetable:data_edit", args=[school.pk, "ogretmenler", target])
    if kind == "avail" and target[0] == "school":
        return reverse("timetable:school_settings", args=[school.pk])
    if kind in ("class_max", "class_min"):
        return reverse("timetable:data_edit", args=[school.pk, "siniflar", target])
    if kind == "spread":
        return reverse("timetable:lesson_edit", args=[school.pk, target])
    if kind == "rel":
        rel_id = problem.relationships[target].id
        return reverse("timetable:data_edit", args=[school.pk, "kart-iliskileri", rel_id]) if rel_id else ""
    if kind == "avail":
        entity_kind, entity_id = target
        if entity_kind == "lesson":
            return reverse("timetable:lesson_edit", args=[school.pk, entity_id])
        return reverse("timetable:data_edit", args=[school.pk, ENTITY_PAGES[entity_kind], entity_id])
    return ""


def diagnosis(school, problem, strict_status, draft):
    """Katı modda bulunamayan programın nedeni: gevşek taslakta esnetilen kurallar (ne kadar) ve sığmayan kartlar."""
    # Aynı kuralın sınıf/ders kopyaları ("aSc 3: Art arda … – BİL121 (57SVN)", "… (58SVN)") tek satırda toplanır.
    groups = {}
    for r in draft.relaxed_rules if draft.ok else []:
        name = r["label"].split(" – ")[0]
        g = groups.setdefault(name, {"label": name, "amount": 0, "count": 0, "examples": [],
                                     "url": _rule_url(school, problem, r["rule"]) if isinstance(r["rule"], tuple) else ""})
        g["amount"] += r["amount"]
        g["count"] += 1
        if " – " in r["label"] and len(g["examples"]) < 4:
            g["examples"].append(r["label"].split(" – ", 1)[1])
    rules = sorted(groups.values(), key=lambda g: -g["amount"])
    total = sum(g["amount"] for g in rules)
    for g in rules:
        # Toplam aşımın en az beşte birini tek başına oluşturan kural asıl nedendir; gerisi ikincil.
        g["main"] = total > 0 and g["amount"] * 5 >= total
    unplaced = defaultdict(int)
    who = defaultdict(int)
    by_key = {c.key: c for c in problem.cards}
    for key in draft.unplaced if draft.ok else []:
        card = by_key[key]
        unplaced[problem.label("lesson", card.lesson_id)] += card.length
        for t in card.teachers:
            who[problem.label("teacher", t)] += card.length
    return {
        "strict_status": strict_status, "found": draft.ok, "rules": rules[:60], "rule_count": len(rules),
        "relaxed_total": total, "main": [g for g in rules if g["main"]][:6],
        "secondary": [g for g in rules if not g["main"]][:60],
        "unplaced": [{"label": k, "hours": n} for k, n in sorted(unplaced.items(), key=lambda kv: -kv[1])][:30],
        "unplaced_hours": sum(unplaced.values()),
        "teachers": [{"label": k, "hours": n} for k, n in sorted(who.items(), key=lambda kv: -kv[1])][:10],
    }


def explain_conflict(school, problem, time_limit=60, known_infeasible=False):
    """Çözülemeyen programın nedenini rapor için hazırlar."""
    result = cpsat.explain(problem, time_limit=time_limit, known_infeasible=known_infeasible)
    return {
        "status": result.status,
        "minimal": result.minimal,
        "wall_time": result.wall_time,
        "rules": [{"label": label, "url": _rule_url(school, problem, key)} for label, key in zip(result.rules, result.keys)],
    }
