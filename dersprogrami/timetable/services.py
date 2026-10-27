"""Uygulama katmanı: denetim, üretim ve doğrulama işlemlerini veritabanına bağlar."""

from django.conf import settings
from django.db import transaction

from .models import Card, Timetable
from .solver import cpsat, feasibility
from .solver.builder import build_problem
from .solver.cpsat import Placement
from .solver.validate import validate


def check_school(school):
    return feasibility.check(build_problem(school))


def generate_timetable(school, name, time_limit=None, base=None, seed=0):
    """Yeni bir program sürümü üretir ve kaydeder.

    base verilirse o sürümün kilitli kartları yerinde kalır, diğer kartların yerleri çözücüye
    başlangıç ipucu olarak verilir. Sonradan eklenen dersler de üretime dahil edilir.
    """
    time_limit = time_limit or settings.TIMETABLE_SOLVER_TIME_LIMIT
    problem = build_problem(school, base=base)
    issues = feasibility.check(problem)
    report = {"issues": [i.as_dict() for i in issues]}

    if feasibility.has_errors(issues):
        return Timetable.objects.create(school=school, name=name, status=Timetable.FAILED, report=report)

    solution = cpsat.solve(problem, time_limit=time_limit, seed=seed)
    report["solver"] = {"status": solution.status, **solution.stats}

    with transaction.atomic():
        timetable = Timetable.objects.create(
            school=school,
            name=name,
            status=Timetable.OK if solution.ok else Timetable.FAILED,
            objective=solution.objective,
            report=report,
        )
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
                    locked=card.fixed is not None,
                )
            )
        Card.objects.bulk_create(cards)
        if solution.ok:
            violations, stats = validate(problem, solution.placements)
            timetable.report["validation"] = {"violations": [v.as_dict() for v in violations], "stats": stats}
            timetable.save(update_fields=["report"])
    return timetable


def verify_timetable(timetable):
    """Kaydedilmiş (elle düzenlenmiş olabilir) bir programı doğrular."""
    problem = build_problem(timetable.school, timetable=timetable)
    db_cards = {c.id: c for c in timetable.cards.all()}
    placements = {}
    for card in problem.cards:
        db_card = db_cards[card.card_id]
        if db_card.is_placed:
            placements[card.key] = Placement(db_card.day, db_card.period, db_card.classroom_id)
    return validate(problem, placements)
