"""İhlalli başlangıcın korunması ve günler arası sınırlı onarımın davranışı."""

import time
from unittest import mock

from django.test import SimpleTestCase
from ortools.sat.python import cp_model

from timetable.solver import cpsat, gen2
from timetable.solver.problem import RelationshipSpec
from timetable.solver.validate import validate
from timetable.tests.test_solver import make_card, make_problem


class RepairNeighbourhoodTests(SimpleTestCase):
    def setUp(self):
        cards = [
            make_card(0, teachers=[1], atoms=["a"], days=2, periods=3),
            make_card(1, teachers=[2], atoms=["a"], days=2, periods=3),
            make_card(2, teachers=[1], atoms=["b"], days=2, periods=3),
            make_card(3, teachers=[3], atoms=["b"], days=2, periods=3),
            make_card(4, teachers=[4], atoms=["c"], days=2, periods=3),
        ]
        for card, slot in zip(cards, [(0, 0), (1, 1), (1, 0), (1, 2), (0, 2)]):
            card.hint = (*slot, None)
        self.problem = make_problem(cards, days=2, periods=3, relationships=[
            RelationshipSpec("Ardışık", "consecutive_ordered", 1, [[0], [1]]),
        ])
        self.builder = cpsat._Builder(self.problem, cpsat.RELAXED, place_all=True)
        self.model = self.builder.build()
        self.slacks = sum(e for _, _, e in self.builder.relaxed_slacks)
        self.model.Minimize(self.slacks)
        self.initial = gen2._hinted_draft(self.problem, self.builder, self.model, 2, 1, None)
        self.assertIsNotNone(self.initial)
        self.best = (int(self.initial.ObjectiveValue()), list(self.initial.ResponseProto().solution), self.initial)
        self.assertEqual(self.best[0], 1)

    def solve(self, model):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 2
        solver.parameters.num_workers = 1
        return solver, solver.Solve(model)

    def test_starting_timetable_is_completed_without_moving_cards(self):
        places = cpsat._placements(self.builder, self.initial, self.problem)
        self.assertEqual([(places[c.key].day, places[c.key].period) for c in self.problem.cards],
                         [c.hint[:2] for c in self.problem.cards])
        self.assertEqual(sum(v.level == "hard" for v in validate(self.problem, places)[0]), 1)

    def test_resource_neighbours_on_other_days_are_released(self):
        local = gen2._violation_neighbourhood(self.problem, self.builder, self.initial, depth=1)
        self.assertEqual(local, {0, 1, 2})  # kart 2 başka gündeki aynı öğretmeni serbest bırakır
        wider = gen2._violation_neighbourhood(self.problem, self.builder, self.initial, depth=2)
        self.assertEqual(wider, {0, 1, 2, 3})

    def test_hard_paired_relationship_releases_its_other_end(self):
        self.problem.relationships.append(RelationshipSpec("Eş", "same_day", 1, [[2], [4]]))
        local = gen2._violation_neighbourhood(self.problem, self.builder, self.initial, depth=1)
        self.assertIn(4, local)

    def test_fixed_card_is_kept_even_inside_released_area(self):
        self.problem.cards[4].fixed = (0, 2)
        builder = cpsat._Builder(self.problem, cpsat.RELAXED, place_all=True)
        model = builder.build()
        model.Minimize(sum(e for _, _, e in builder.relaxed_slacks))
        initial = gen2._hinted_draft(self.problem, builder, model, 2, 1, None)
        best = (int(initial.ObjectiveValue()), list(initial.ResponseProto().solution), initial)
        local = gen2._draft_neighbourhood_model(model, builder, best, set(builder.x))
        solver, status = self.solve(local)
        self.assertIn(status, (cp_model.OPTIMAL, cp_model.FEASIBLE))
        places = cpsat._placements(builder, solver, self.problem)
        self.assertEqual((places[4].day, places[4].period), (0, 2))

    def test_initial_completion_and_repair_produce_strict_valid_solution(self):
        strict = cpsat._Builder(self.problem)
        model = strict.build()
        solver, callback, info = gen2.repair_search(self.problem, strict, model, 10, time.monotonic(),
                                                     1, 0, None, None)
        self.assertTrue(callback.found, info)
        self.assertEqual(info["rounds"][0]["violations"], 1)
        self.assertEqual(info["violations"], 0)
        places = cpsat._placements(strict, solver, self.problem)
        self.assertFalse([v for v in validate(self.problem, places)[0] if v.level == "hard"])

    def test_gen2_dispatches_repair_and_returns_independently_valid_result(self):
        with mock.patch.object(gen2, "repair_search", wraps=gen2.repair_search) as repair:
            result = cpsat.solve(self.problem, algorithm="gen2", time_limit=5, workers=1)
        repair.assert_called_once()
        self.assertTrue(result.ok, result.stats)
        self.assertFalse([v for v in validate(self.problem, result.placements)[0] if v.level == "hard"])

    def test_local_repair_removes_violation_and_keeps_unrelated_card(self):
        local = gen2._draft_neighbourhood_model(self.model, self.builder, self.best, {0, 1, 2, 3})
        solver, status = self.solve(local)
        self.assertIn(status, (cp_model.OPTIMAL, cp_model.FEASIBLE))
        self.assertEqual(solver.ObjectiveValue(), 0)
        places = cpsat._placements(self.builder, solver, self.problem)
        self.assertFalse([v for v in validate(self.problem, places)[0] if v.level == "hard"])
        self.assertEqual((places[4].day, places[4].period), (0, 2))

    def test_frozen_placements_are_local_to_one_round(self):
        local = gen2._draft_neighbourhood_model(self.model, self.builder, self.best, {0, 1, 2, 3})
        local.Add(self.builder.x[4][(1, 2)] == 1)
        self.assertEqual(self.solve(local)[1], cp_model.INFEASIBLE)
        original = self.model.clone()
        original.Add(self.builder.x[4][(1, 2)] == 1)
        self.assertIn(self.solve(original)[1], (cp_model.OPTIMAL, cp_model.FEASIBLE))

    def test_round_cannot_return_more_violations(self):
        local = gen2._draft_neighbourhood_model(self.model, self.builder, self.best, set(self.builder.x))
        local.Add(self.slacks > self.best[0])
        self.assertEqual(self.solve(local)[1], cp_model.INFEASIBLE)

    def test_stopping_after_initial_completion_keeps_input_as_draft(self):
        strict = cpsat._Builder(self.problem)
        model = strict.build()
        stop = cpsat.StopHandle()

        def progress(info):
            if info.get("round") == 0:
                stop.stop()

        _, callback, info = gen2.repair_search(self.problem, strict, model, 10, time.monotonic(),
                                                1, 0, progress, stop)
        self.assertFalse(callback.found)
        self.assertEqual(info["status"], "stopped")
        self.assertEqual(strict.best_draft[0], 1)
        self.assertEqual(len(strict.best_draft_solution.placements), 5)

    def test_incomplete_or_conflicting_hint_is_not_treated_as_impossibility(self):
        self.problem.cards[0].hint = None
        self.assertIsNone(gen2._hinted_draft(self.problem, self.builder, self.model, 2, 1, None))
        self.problem.cards[0].hint = (1, 0, None)  # kart 2 ile aynı öğretmen ve saat
        self.assertIsNone(gen2._hinted_draft(self.problem, self.builder, self.model, 2, 1, None))
        self.assertIn(self.solve(self.model)[1], (cp_model.OPTIMAL, cp_model.FEASIBLE))
