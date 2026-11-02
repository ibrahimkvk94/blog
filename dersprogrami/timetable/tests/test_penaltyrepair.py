"""Ana görünümde "Cezayı düşür" (solver/penaltyrepair.py): ceza azalır, kesin ihlal artmaz, geri alınabilir."""

import time
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from timetable.demo import create_demo_school
from timetable.services import generate_timetable, reduce_penalty, verify_timetable
from timetable.solver import cpsat
from timetable.solver.penaltyrepair import PenaltyRepair
from timetable.solver.validate import validate
from timetable.tests.test_solver import make_card, make_problem


def gappy_problem():
    """2 gün × 4 saat, bir kısmın üç dersi; (0,0) ile (0,3) arası iki saat boşluk."""
    cards = [make_card(k, teachers=[k + 1], atoms=["a"], days=2, periods=4) for k in range(3)]
    return make_problem(cards, days=2, periods=4)


GAPPY = {0: cpsat.Placement(0, 0, None), 1: cpsat.Placement(0, 3, None), 2: cpsat.Placement(1, 0, None)}


def hard(problem, placements):
    return [v for v in validate(problem, placements)[0] if v.level == "hard" and v.code != "unplaced"]


class PenaltyRepairTests(SimpleTestCase):
    def test_closes_class_gap(self):
        problem = gappy_problem()
        repair = PenaltyRepair(problem, workers=1)
        self.assertTrue(repair.start(GAPPY))
        before = repair.penalty
        self.assertGreater(before, 0)
        repair.run(time.monotonic() + 10)
        self.assertLess(repair.penalty, before)
        result = repair.placements()
        self.assertEqual(len(result), 3)
        self.assertEqual(hard(problem, result), [])

    def test_locked_card_stays(self):
        problem = gappy_problem()
        problem.cards[1].fixed = (0, 3)
        repair = PenaltyRepair(problem, workers=1)
        repair.start(GAPPY)
        repair.run(time.monotonic() + 10)
        p = repair.placements()[1]
        self.assertEqual((p.day, p.period), (0, 3))

    def test_pending_card_stays_pending(self):
        problem = gappy_problem()
        partial = {k: v for k, v in GAPPY.items() if k != 2}
        repair = PenaltyRepair(problem, workers=1)
        self.assertTrue(repair.start(partial))
        repair.run(time.monotonic() + 10)
        self.assertNotIn(2, repair.placements())
        self.assertEqual(len(repair.placements()), 2)

    def test_never_gets_worse(self):
        problem = gappy_problem()
        repair = PenaltyRepair(problem, workers=1)
        repair.start(GAPPY)
        seen = [repair.penalty]
        for combo in repair.combos:
            solver, status = repair._round(combo, 5)
            if status in (2, 4) and solver.ObjectiveValue() <= repair.penalty:
                repair._accept(solver)
            seen.append(repair.penalty)
        self.assertEqual(seen, sorted(seen, reverse=True))


class ReducePenaltyServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.timetable = generate_timetable(cls.school, "t", time_limit=20)

    def hard(self):
        return sum(1 for v in verify_timetable(self.timetable)[0] if v.level == "hard")

    def test_reduces_without_new_violations_and_undo(self):
        before_cards = {c.id: (c.day, c.period) for c in self.timetable.cards.all()}
        hard_before = self.hard()
        result = reduce_penalty(self.timetable, time_limit=10)  # kesin ihlal artmaz (bağımsız doğrulama)
        self.assertTrue(result["ok"], result)
        self.assertLessEqual(result["after"], result["before"])
        self.assertLessEqual(self.hard(), hard_before)
        if result["moved"]:
            self.timetable.refresh_from_db()
            self.assertEqual(self.timetable.objective, result["after"])
            self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
            self.client.post(reverse("timetable:api_undo", args=[self.timetable.pk]))
            self.assertEqual({c.id: (c.day, c.period) for c in self.timetable.cards.all()}, before_cards)

    def test_api_maps_duration_and_page_has_button(self):
        from timetable import quick_jobs

        self.client.force_login(User.objects.create_superuser("admin2", "b@x.tr", "pw"))
        url = reverse("timetable:api_penalty", args=[self.timetable.pk])
        with mock.patch.object(quick_jobs.school_improve, "start") as start:
            start.return_value = mock.Mock(kind="penalty", **{"refresh_from_db.return_value": None})
            with mock.patch.object(quick_jobs, "state", return_value={}):
                self.client.post(url, data='{"sure": 300}', content_type="application/json")
                self.client.post(url, data='{"sure": 9999}', content_type="application/json")
        self.assertEqual([c.kwargs["seconds"] for c in start.call_args_list], [300, 60])
        page = self.client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk]))
        self.assertContains(page, "Cezayı düşür")
        self.assertContains(page, 'data-job-start="900"')


class StrictPolishTests(SimpleTestCase):
    def test_polish_lowers_objective_of_strict_solution(self):
        problem = gappy_problem()
        repair = PenaltyRepair(problem, workers=1)
        repair.start(GAPPY)
        solution = cpsat.Solution(status="feasible", placements=dict(GAPPY), objective=repair.penalty, stats={})
        progress = []
        cpsat._polish(problem, solution, time.monotonic(), 120, 1, 0, progress.append, None)
        self.assertLess(solution.objective, repair.penalty)
        self.assertEqual(solution.stats["polish"]["before"], repair.penalty)
        self.assertEqual(hard(problem, solution.placements), [])
        self.assertEqual(progress[0]["phase"], "polish")

    def test_auto_strict_solve_runs_polish_only_with_auto_time(self):
        problem = gappy_problem()
        with mock.patch.object(cpsat, "_polish") as polish:
            cpsat.solve(problem, time_limit=20, workers=1, two_phase=False)
            polish.assert_not_called()
        # Kolay problemde ceza zaten 0 olabilir; çağrının koşulu yalnızca otomatik süre ve sıfır olmayan ceza.
        with mock.patch.object(cpsat, "_polish") as polish:
            solution = cpsat.solve(problem, time_limit=20, workers=1, two_phase=False, auto_time=True)
        self.assertEqual(polish.called, bool(solution.objective))
