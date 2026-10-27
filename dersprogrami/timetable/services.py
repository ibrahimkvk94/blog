"""Uygulama katmanı: denetim, üretim ve doğrulama işlemlerini veritabanına bağlar."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import jobs
from .models import Card, Timetable
from .solver import cpsat, feasibility
from .solver.builder import build_problem
from .solver.cpsat import Placement
from .solver.validate import validate

STALE_GRACE = timedelta(seconds=90)


def check_school(school):
    return feasibility.check(build_problem(school))


def start_generation(school, name, time_limit=None, mode=Timetable.STRICT, base=None, seed=0):
    """Yeni bir program sürümü oluşturur ve üretimi arka planda başlatır."""
    timetable = Timetable.objects.create(
        school=school,
        name=name,
        status=Timetable.RUNNING,
        mode=mode,
        time_limit=time_limit or settings.TIMETABLE_SOLVER_TIME_LIMIT,
        started_at=timezone.now(),
        report={"base": base.pk if base else None},
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


def run_generation(timetable_id, base_id=None, seed=0):
    timetable = Timetable.objects.select_related("school").get(pk=timetable_id)
    base = Timetable.objects.filter(pk=base_id).first() if base_id else None
    relaxed = timetable.mode == Timetable.RELAXED
    report = dict(timetable.report)
    try:
        problem = build_problem(timetable.school, base=base)
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
            report["error"] = "Süre sınırı içinde çözüm bulunamadı. Süreyi artırın ya da gevşek modu deneyin."
        elif solution.status == "infeasible":
            report["error"] = "Bu verilerle tüm kuralları sağlayan bir program yok."
            jobs.set_progress(timetable_id, {"phase": "explain"})
            report["conflict"] = explain_conflict(
                timetable.school, problem, time_limit=min(180, max(60, timetable.time_limit)), known_infeasible=True
            )
        _finish(timetable, Timetable.FAILED, report)
        return

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
        violations, stats = validate(problem, solution.placements)
        report["validation"] = {"violations": [v.as_dict() for v in violations], "stats": stats}
        timetable.objective = solution.objective
        status = Timetable.PARTIAL if solution.unplaced else Timetable.OK
        _finish(timetable, status, report)


def _finish(timetable, status, report):
    report.pop("progress", None)
    Timetable.objects.filter(pk=timetable.pk).update(
        status=status, report=report, objective=timetable.objective, finished_at=timezone.now()
    )


def request_stop(timetable):
    Timetable.objects.filter(pk=timetable.pk).update(cancel_requested=True)
    jobs.stop(timetable.pk)


def refresh_stale(timetable):
    """Sunucu yeniden başlatılınca yarıda kalan üretimleri "üretilemedi" olarak işaretler."""
    if timetable.status != Timetable.RUNNING or jobs.is_alive(timetable.pk) or not timetable.started_at:
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
    problem = build_problem(timetable.school, timetable=timetable)
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
    changed = []
    for card in problem.cards:
        db_card = db_cards[card.card_id]
        place = solution.placements.get(card.key)
        new = (place.day, place.period, place.room, list(place.extra_rooms)) if place else (None, None, None, [])
        if (db_card.day, db_card.period, db_card.classroom_id, list(db_card.extra_rooms or [])) != new:
            db_card.day, db_card.period, db_card.classroom_id, db_card.extra_rooms = new
            changed.append(db_card)
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


def explain_conflict(school, problem, time_limit=60, known_infeasible=False):
    """Çözülemeyen programın nedenini rapor için hazırlar."""
    result = cpsat.explain(problem, time_limit=time_limit, known_infeasible=known_infeasible)
    return {
        "status": result.status,
        "minimal": result.minimal,
        "wall_time": result.wall_time,
        "rules": [{"label": label, "url": _rule_url(school, problem, key)} for label, key in zip(result.rules, result.keys)],
    }
