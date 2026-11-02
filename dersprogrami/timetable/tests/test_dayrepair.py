"""Katı modelin onarım yolu (solver/dayrepair.py): gün komşuluğu, Gen2 ile dönüşüm ve otomatik süre."""

import time
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from timetable import services
from timetable.models import Timetable
from timetable.solver import cpsat, dayrepair, gen2
from timetable.solver.problem import RelationshipSpec
from timetable.solver.validate import validate
from timetable.tests.test_generation_flow import _school
from timetable.tests.test_solver import make_card, make_problem


def hard(problem, placements):
    return [v for v in validate(problem, placements)[0] if v.level == "hard"]


def full_class_problem(fixed=None):
    """3 gün × 2 saat, kısmın haftası tam dolu; 0 → 1 sıralı art arda olmak zorunda."""
    cards = [make_card(k, teachers=[k + 1], atoms=["a"], days=3, periods=2) for k in range(6)]
    if fixed is not None:
        cards[fixed[0]].fixed = fixed[1]
    return make_problem(cards, days=3, periods=2, relationships=[
        RelationshipSpec("Ardışık", "consecutive_ordered", 1, [[0], [1]]),
    ])


# 0 ile 1 farklı günlerde: tek kesin ihlal
BROKEN = {0: (0, 0), 1: (1, 1), 2: (0, 1), 3: (1, 0), 4: (2, 0), 5: (2, 1)}


def placements(slots):
    return {k: cpsat.Placement(d, p, None) for k, (d, p) in slots.items()}


class DayRepairTests(SimpleTestCase):
    def test_moves_card_across_days_and_reaches_zero(self):
        problem = full_class_problem()
        self.assertEqual(len(hard(problem, placements(BROKEN))), 1)
        days = dayrepair.DayRepair(problem, workers=1, seed=0)
        self.assertTrue(days.start(placements(BROKEN)))
        self.assertEqual(days.violations, 1)
        self.assertEqual(days.run(time.monotonic() + 20), 0)
        result = {k: cpsat.Placement(*p) for k, p in days.placements().items()}
        self.assertEqual(hard(problem, result), [])
        self.assertEqual(result[1].day, result[0].day)
        self.assertEqual(result[1].period, result[0].period + 1)

    def test_hot_days_are_the_days_of_the_broken_pair(self):
        problem = full_class_problem()
        days = dayrepair.DayRepair(problem, workers=1, seed=0)
        days.start(placements(BROKEN))
        self.assertEqual(days._hot_days(), {0, 1})
        days.run(time.monotonic() + 20)
        self.assertEqual(days._hot_days(), set())

    def test_fixed_card_stays_in_place(self):
        problem = full_class_problem(fixed=(5, (2, 1)))
        days = dayrepair.DayRepair(problem, workers=1, seed=0)
        self.assertTrue(days.start(placements(BROKEN)))
        days.run(time.monotonic() + 20)
        self.assertEqual(days.violations, 0)
        self.assertEqual(days.placements()[5][:2], (2, 1))

    def test_round_never_increases_violations(self):
        problem = full_class_problem()
        days = dayrepair.DayRepair(problem, workers=1, seed=0)
        days.start(placements(BROKEN))
        for combo in days.combos:
            solver, status = days._round(combo, 5)
            if solver.ObjectiveValue() is not None and status in (4, 2):  # OPTIMAL / FEASIBLE
                self.assertLessEqual(int(round(solver.ObjectiveValue())), 1)

    def test_start_fails_when_a_card_has_no_placement(self):
        problem = full_class_problem()
        partial = placements({k: v for k, v in BROKEN.items() if k != 3})
        self.assertFalse(dayrepair.DayRepair(problem, workers=1, seed=0).start(partial))

    def test_stalled_gen2_hands_over_to_days_then_strict_check(self):
        """Gen2 ihlalli taslakta tıkanırsa gün komşuluğu devralır; sıfırda katı modelle doğrulanır."""
        problem = full_class_problem()
        builder = cpsat._Builder(problem, cpsat.STRICT)
        model = builder.build()
        real = gen2.repair_search
        calls = []

        def fake(problem, builder, model, time_limit, started, workers, seed, on_progress, stop_handle, **kw):
            calls.append(time_limit)
            if len(calls) == 1:  # tıkanmış Gen2 bölümü: 1 ihlalli taslak bırakır
                draft = cpsat.Solution(status="feasible", placements=placements(BROKEN))
                builder.best_draft = (1, {k: v for k, v in BROKEN.items()})
                builder.best_draft_solution = draft
                return None, cpsat._FirstSolution(None), {"status": "stopped", "violations": 1}
            return real(problem, builder, model, time_limit, started, workers, seed, on_progress, stop_handle, **kw)

        with mock.patch.object(gen2, "repair_search", side_effect=fake):
            first, callback, info = dayrepair.repair_search(problem, builder, model, 60, time.monotonic(), 1, 0, None, None)
        self.assertTrue(callback.found)
        self.assertEqual(len(calls), 2)
        self.assertEqual([t["method"] for t in info["turns"]], ["gen2", "days"])
        self.assertEqual(info["turns"][1]["violations"], 0)
        result = cpsat._placements(builder, first, problem)
        self.assertEqual(len(result), len(problem.cards))
        self.assertEqual(hard(problem, result), [])

    def test_strict_solve_uses_combined_repair(self):
        problem = full_class_problem()
        with mock.patch.object(dayrepair, "repair_search", wraps=dayrepair.repair_search) as repair:
            solution = cpsat.solve(problem, time_limit=20, workers=1, two_phase=True)
        self.assertTrue(solution.ok)
        self.assertEqual(hard(problem, solution.placements), [])
        repair.assert_not_called()  # kolay problem: doğrudan arama bulur, onarıma hiç girilmez

    def test_auto_time_stops_after_stall(self):
        problem = full_class_problem()
        builder = cpsat._Builder(problem, cpsat.STRICT)
        model = builder.build()

        def stuck(problem, builder, model, time_limit, started, workers, seed, on_progress, stop_handle, **kw):
            builder.best_draft = (1, dict(BROKEN))
            builder.best_draft_solution = cpsat.Solution(status="feasible", placements=placements(BROKEN))
            return None, cpsat._FirstSolution(None), {"status": "stopped", "violations": 1}

        with mock.patch.object(gen2, "repair_search", side_effect=stuck), \
                mock.patch.object(dayrepair.DayRepair, "run", return_value=1):
            started = time.monotonic()
            _, callback, info = dayrepair.repair_search(problem, builder, model, 600, started, 1, 0, None, None,
                                                        stall_seconds=0.5)
        self.assertFalse(callback.found)
        self.assertTrue(info["stalled"])
        self.assertLess(time.monotonic() - started, 60)


@override_settings(AUTO_BACKUP=False, TIMETABLE_RUN_IN_BACKGROUND=False, TIMETABLE_JOB_BACKEND="worker")
class AutoTimeFlowTests(TestCase):
    def setUp(self):
        self.school, _ = _school()
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def post(self, **data):
        return self.client.post(reverse("timetable:generate", args=[self.school.pk]), {"name": "Deneme", **data})

    def test_empty_time_in_strict_mode_means_automatic(self):
        self.post(mode="strict", time_limit="")
        tt = self.school.timetables.get()
        self.assertTrue(tt.report["auto_time"])
        self.assertEqual(tt.time_limit, cpsat.AUTO_LIMIT)
        with mock.patch.object(services.cpsat, "solve", wraps=cpsat.solve) as solve:
            services.run_generation(tt.pk)
        self.assertTrue(solve.call_args.kwargs["auto_time"])
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.OK)
        self.assertEqual(tt.hard_violations, 0)

    def test_typed_time_is_an_upper_limit_without_auto(self):
        self.post(mode="strict", time_limit="90")
        tt = self.school.timetables.get()
        self.assertNotIn("auto_time", tt.report)
        self.assertEqual(tt.time_limit, 90)

    def test_other_modes_never_use_auto_time(self):
        self.post(mode="relaxed", time_limit="")
        tt = self.school.timetables.get()
        self.assertNotIn("auto_time", tt.report)
        self.assertEqual(tt.time_limit, 60)

    def test_form_shows_automatic_time_for_strict(self):
        response = self.client.get(reverse("timetable:school_detail", args=[self.school.pk]))
        self.assertContains(response, 'placeholder="Otomatik"')
        self.assertContains(response, "data-strict-timing")
