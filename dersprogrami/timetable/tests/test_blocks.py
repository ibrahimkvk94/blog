"""Blok modelinin kapsamı, kesinliği ve çözüm kümesini koruması."""

from itertools import product
from unittest import mock

from django.test import SimpleTestCase

from timetable.solver import blocks, cpsat
from timetable.solver.problem import RelationshipSpec, TeacherPool
from timetable.solver.validate import validate, Violation
from timetable.tests import test_solver
from timetable.tests.test_solver import make_card, make_problem


class BlockModelTests(SimpleTestCase):
    def problem(self, condition="consecutive_ordered"):
        cards = [make_card(0, length=2, periods=5, days=2), make_card(1, periods=5, days=2),
                 make_card(2, periods=5, days=2)]
        return make_problem(cards, days=2, periods=5, relationships=[
            RelationshipSpec("Çift", condition, 1, [[0], [1]]),
            RelationshipSpec("Son", "consecutive_ordered", 1, [[1], [2]])])

    def test_enumeration_matches_independent_validator_exhaustively(self):
        for condition in sorted(blocks.PAIRED):
            with self.subTest(condition=condition):
                p = self.problem(condition)
                expected = set()
                for slots in product(*(c.starts for c in p.cards)):
                    placed = {c.key: cpsat.Placement(*slot, None) for c, slot in zip(p.cards, slots)}
                    if not [v for v in validate(p, placed)[0] if v.level == "hard"]:
                        expected.add(slots)
                [(keys, options)] = blocks.block_options(p)
                self.assertEqual(keys, (0, 1, 2))
                self.assertEqual(set(options), expected)

    def test_locks_and_availability_restrict_whole_block(self):
        p = self.problem()
        p.cards[1].fixed = (1, 2)
        p.cards[2].starts = [(1, 3)]
        self.assertEqual(blocks.block_options(p)[0][1], [((1, 0), (1, 2), (1, 3))])
        result = cpsat.solve(p, algorithm="gen3", workers=1, time_limit=3)
        self.assertTrue(result.ok, result.stats)
        self.assertEqual(result.placements[0].day, 1)

    def test_contradictory_cycle_is_infeasible(self):
        p = self.problem()
        p.relationships.append(RelationshipSpec("Döngü", "consecutive_ordered", 1, [[2], [0]]))
        self.assertEqual(blocks.block_options(p)[0][1], [])
        self.assertEqual(cpsat.solve(p, algorithm="gen3", workers=1, time_limit=3).status, "infeasible")

    def test_soft_relations_are_not_forced_into_blocks(self):
        p = self.problem()
        for rel in p.relationships:
            rel.weight = 5
        self.assertEqual(blocks.block_options(p), [])

    def test_large_component_falls_back_without_losing_solutions(self):
        p = self.problem()
        builder = blocks.BlockBuilder(p, max_options=1)
        model = builder.build()
        model.ClearObjective()
        solver = blocks.cp_model.CpSolver()
        solver.parameters.num_workers = 1
        self.assertIn(solver.Solve(model), (blocks.cp_model.OPTIMAL, blocks.cp_model.FEASIBLE))
        self.assertEqual(builder.block_stats["fallback_blocks"], 1)
        self.assertFalse([v for v in validate(p, cpsat._placements(builder, solver, p))[0] if v.level == "hard"])

    def test_expired_enumeration_is_not_impossibility(self):
        self.assertIsNone(blocks.block_options(self.problem(), deadline=0)[0][1])

    def test_distinct_card_domains_do_not_get_false_symmetry_order(self):
        cards = [make_card(0, lesson_id=1, starts=[(0, 1)]),
                 make_card(1, lesson_id=1, starts=[(0, 0)])]
        result = cpsat.solve(make_problem(cards, periods=2), algorithm="gen3", workers=1, time_limit=3)
        self.assertTrue(result.ok, result.stats)
        self.assertEqual(result.placements[0].period, 1)
        self.assertEqual(result.placements[1].period, 0)

    def test_teacher_pool_is_validated_with_selected_teacher_without_mutating_input(self):
        cards = [make_card(0, periods=2), make_card(1, periods=2)]
        p = make_problem(cards, periods=2, teacher_pools=[TeacherPool("Havuz", (0, 1), {7: 2})])
        result = cpsat.solve(p, algorithm="gen3", workers=1, time_limit=3)
        self.assertTrue(result.ok, result.stats)
        self.assertNotEqual(result.placements[0].period, result.placements[1].period)
        self.assertEqual(result.teacher_choice, {0: 7, 1: 7})
        self.assertEqual(p.cards[0].teachers, ())

    def test_independent_validation_failure_is_not_returned_as_success(self):
        with mock.patch.object(blocks, "validate", return_value=([Violation("clash", "çakışma")], {})):
            result = cpsat.solve(self.problem(), algorithm="gen3", workers=1, time_limit=3)
        self.assertEqual(result.status, "invalid")
        self.assertFalse(result.placements)

    def test_pre_stopped_search_returns_without_solution(self):
        handle = cpsat.StopHandle()
        handle.stop()
        result = cpsat.solve(self.problem(), algorithm="gen3", workers=1, time_limit=3, stop_handle=handle)
        self.assertEqual(result.status, "unknown")
        self.assertTrue(result.stats["stopped"])


class BlockSolverCompatibilityTests(SimpleTestCase):
    """Ortak solve yardımcısını kullanan mevcut kural senaryolarını blok yolu ile de çalıştır."""

    def solve(self, problem):
        result = cpsat.solve(problem, algorithm="gen3", time_limit=5, workers=1)
        if result.ok:
            self.assertFalse([v for v in validate(problem, result.placements)[0] if v.level == "hard"])
        return result


# Gen3 ilk geçerli çözümde durur; tercih puanını en aza indirme testleri Katı modda kalır.
for _name, _test in vars(test_solver.SolverTests).items():
    if _name.startswith("test_") and _name not in {
        "test_class_day_starts_at_first_period", "test_teacher_gaps_are_minimised",
    }:
        setattr(BlockSolverCompatibilityTests, _name, _test)
