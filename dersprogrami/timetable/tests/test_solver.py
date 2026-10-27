"""Çözücünün Django'dan bağımsız testleri."""

from django.test import SimpleTestCase

from timetable.solver import cpsat, feasibility
from timetable.solver.problem import Problem, ProblemCard, RelationshipSpec, TeacherLimits, class_atoms, lesson_atoms
from timetable.solver.validate import validate

ALL = frozenset({(0, 0)})


def make_card(key, lesson_id=None, length=1, teachers=(), atoms=(), rooms=(), universes=ALL, starts=None, days=1, periods=1):
    if starts is None:
        starts = [(d, p) for d in range(days) for p in range(periods - length + 1)]
    return ProblemCard(
        key=key,
        lesson_id=key if lesson_id is None else lesson_id,
        length=length,
        teachers=tuple(teachers),
        atoms=tuple(atoms),
        room_options=tuple(rooms),
        universes=universes,
        starts=starts,
    )


def make_problem(cards, days=1, periods=1, universes=ALL, **kwargs):
    return Problem(days=days, periods=periods, universes=universes, cards=cards, **kwargs)


class AtomTests(SimpleTestCase):
    def test_atoms_are_cartesian_product_of_divisions(self):
        atoms = class_atoms(1, [[10, 11], [20, 21]])
        self.assertEqual(len(atoms), 4)
        self.assertIn(frozenset({10, 21}), atoms.values())

    def test_class_without_divisions_has_single_atom(self):
        self.assertEqual(list(class_atoms(1, []).values()), [frozenset()])

    def test_lesson_atoms_for_group_and_whole_class(self):
        atoms_by_class = {1: class_atoms(1, [[10, 11]]), 2: class_atoms(2, [])}
        class_of_group = {10: 1, 11: 1}
        self.assertEqual(lesson_atoms([1], [10], atoms_by_class, class_of_group), ("1|10",))
        self.assertEqual(set(lesson_atoms([1, 2], [], atoms_by_class, class_of_group)), {"1|10", "1|11", "2|"})


class SolverTests(SimpleTestCase):
    def solve(self, problem):
        solution = cpsat.solve(problem, time_limit=10, workers=1)
        if solution.ok:
            violations, _ = validate(problem, solution.placements)
            self.assertEqual(violations, [])
        return solution

    def test_teacher_cannot_teach_two_cards_at_once(self):
        cards = [make_card(0, teachers=[1], atoms=["a"], periods=2), make_card(1, teachers=[1], atoms=["b"], periods=2)]
        solution = self.solve(make_problem(cards, periods=2))
        self.assertTrue(solution.ok)
        self.assertNotEqual(solution.placements[0].period, solution.placements[1].period)

    def test_groups_of_same_division_can_be_simultaneous(self):
        cards = [make_card(0, teachers=[1], atoms=["c|boys"]), make_card(1, teachers=[2], atoms=["c|girls"])]
        self.assertTrue(self.solve(make_problem(cards)).ok)

    def test_overlapping_groups_cannot_be_simultaneous(self):
        # "Kızlar" ve "1. grup" farklı bölünmelerde: ortak atomları var.
        cards = [
            make_card(0, teachers=[1], atoms=["c|girls-g1", "c|girls-g2"]),
            make_card(1, teachers=[2], atoms=["c|girls-g1", "c|boys-g1"]),
        ]
        self.assertEqual(self.solve(make_problem(cards)).status, "infeasible")

    def test_ab_weeks_share_a_slot(self):
        week_a, week_b = frozenset({(0, 0)}), frozenset({(1, 0)})
        cards = [
            make_card(0, teachers=[1], atoms=["a"], universes=week_a),
            make_card(1, teachers=[1], atoms=["a"], universes=week_b),
        ]
        problem = make_problem(cards, universes=week_a | week_b)
        self.assertTrue(self.solve(problem).ok)

    def test_room_options_are_assigned_without_clash(self):
        cards = [make_card(0, teachers=[1], atoms=["a"], rooms=[7, 8]), make_card(1, teachers=[2], atoms=["b"], rooms=[7, 8])]
        solution = self.solve(make_problem(cards))
        self.assertTrue(solution.ok)
        self.assertEqual({solution.placements[0].room, solution.placements[1].room}, {7, 8})

    def test_single_shared_room_forces_infeasibility(self):
        cards = [make_card(0, teachers=[1], atoms=["a"], rooms=[7]), make_card(1, teachers=[2], atoms=["b"], rooms=[7])]
        self.assertEqual(self.solve(make_problem(cards)).status, "infeasible")

    def test_double_card_occupies_consecutive_periods(self):
        cards = [make_card(0, length=2, teachers=[1], atoms=["a"], periods=3), make_card(1, teachers=[1], atoms=["b"], periods=3)]
        solution = self.solve(make_problem(cards, periods=3))
        self.assertTrue(solution.ok)
        self.assertIn(solution.placements[1].period, (0, 2))

    def test_lesson_cards_spread_over_days(self):
        cards = [make_card(k, lesson_id=1, teachers=[1], atoms=["a"], days=3, periods=2) for k in range(3)]
        problem = make_problem(cards, days=3, periods=2, lesson_max_per_day={1: 1})
        solution = self.solve(problem)
        self.assertEqual(sorted(p.day for p in solution.placements.values()), [0, 1, 2])

    def test_teacher_gaps_are_minimised(self):
        cards = [make_card(k, lesson_id=k, teachers=[1], atoms=[f"a{k}"], periods=4) for k in range(2)]
        solution = self.solve(make_problem(cards, periods=4, teacher_limits={1: TeacherLimits()}))
        periods = sorted(p.period for p in solution.placements.values())
        self.assertEqual(periods[1] - periods[0], 1)
        # Kalan ceza yalnızca sınıflardan birinin güne geç başlamasıdır; öğretmen boşluğu yok.
        self.assertEqual(solution.objective, cpsat.W_CLASS_LATE_START)

    def test_class_day_starts_at_first_period(self):
        cards = [make_card(0, teachers=[1], atoms=["a"], periods=4)]
        solution = self.solve(make_problem(cards, periods=4))
        self.assertEqual(solution.placements[0].period, 0)

    def test_teacher_daily_maximum(self):
        cards = [make_card(k, lesson_id=k, teachers=[1], atoms=[f"a{k}"], days=2, periods=3) for k in range(4)]
        limits = {1: TeacherLimits(max_periods_per_day=2)}
        solution = self.solve(make_problem(cards, days=2, periods=3, teacher_limits=limits))
        days = [p.day for p in solution.placements.values()]
        self.assertEqual(sorted(days), [0, 0, 1, 1])

    def test_locked_card_stays_in_place(self):
        card = make_card(0, teachers=[1], atoms=["a"], periods=3)
        card.fixed = (0, 2)
        solution = self.solve(make_problem([card], periods=3))
        self.assertEqual((solution.placements[0].day, solution.placements[0].period), (0, 2))


class FeasibilityTests(SimpleTestCase):
    def test_teacher_overload_is_reported(self):
        cards = [make_card(k, teachers=[1], atoms=[f"a{k}"], periods=2) for k in range(3)]
        issues = feasibility.check(make_problem(cards, periods=2, teacher_available={1: 2}))
        self.assertIn("teacher_overload", [i.code for i in issues])
        self.assertTrue(feasibility.has_errors(issues))

    def test_empty_domain_is_reported(self):
        cards = [make_card(0, teachers=[1], atoms=["a"], starts=[])]
        self.assertIn("empty_domain", [i.code for i in feasibility.check(make_problem(cards))])

    def test_valid_problem_has_no_errors(self):
        cards = [make_card(0, teachers=[1], atoms=["a"])]
        self.assertFalse(feasibility.has_errors(feasibility.check(make_problem(cards))))


class RelaxedAndRelationshipTests(SimpleTestCase):
    def test_relaxed_mode_returns_partial_solution(self):
        # Tek hücreye aynı öğretmenin iki kartı sığmaz: katı modda çözüm yok, gevşekte biri bekler.
        cards = [make_card(0, teachers=[1], atoms=["a"]), make_card(1, teachers=[1], atoms=["b"])]
        problem = make_problem(cards)
        self.assertEqual(cpsat.solve(problem, time_limit=5, workers=1).status, "infeasible")
        solution = cpsat.solve(problem, time_limit=5, workers=1, mode=cpsat.RELAXED)
        self.assertTrue(solution.ok)
        self.assertEqual(len(solution.placements), 1)
        self.assertEqual(len(solution.unplaced), 1)
        self.assertIn("unplaced", solution.penalties)

    def test_relaxed_mode_breaks_rule_instead_of_failing(self):
        cards = [make_card(k, lesson_id=k, teachers=[1], atoms=[f"a{k}"], periods=3) for k in range(3)]
        problem = make_problem(cards, periods=3, teacher_limits={1: TeacherLimits(max_periods_per_day=2)})
        self.assertEqual(cpsat.solve(problem, time_limit=5, workers=1).status, "infeasible")
        solution = cpsat.solve(problem, time_limit=5, workers=1, mode=cpsat.RELAXED)
        self.assertEqual(len(solution.placements), 3)
        violations, _ = validate(problem, solution.placements)
        self.assertEqual([v.code for v in violations], ["teacher_daily_max"])

    def test_max_per_day_relationship(self):
        cards = [make_card(k, lesson_id=k, teachers=[k], atoms=["a"], days=2, periods=2) for k in range(4)]
        rel = RelationshipSpec("sayısal", "max_per_day", 2, [[0, 1, 2]])
        problem = make_problem(cards, days=2, periods=2, relationships=[rel])
        solution = cpsat.solve(problem, time_limit=5, workers=1)
        days = [solution.placements[k].day for k in (0, 1, 2)]
        self.assertLessEqual(max(days.count(0), days.count(1)), 2)
        self.assertEqual(validate(problem, solution.placements)[0], [])

    def test_soft_relationship_is_reported_when_broken(self):
        cards = [make_card(k, lesson_id=k, teachers=[k], atoms=["a"], periods=2) for k in range(2)]
        rel = RelationshipSpec("farklı gün", "different_days", 1, [[0, 1]], weight=60)
        problem = make_problem(cards, periods=2, relationships=[rel])
        solution = cpsat.solve(problem, time_limit=5, workers=1)
        self.assertTrue(solution.ok)
        self.assertEqual(solution.penalties.get("relationship"), 60)
        violations, _ = validate(problem, solution.placements)
        self.assertEqual([(v.code, v.level) for v in violations], [("relationship", "soft")])

    def test_same_time_relationship(self):
        cards = [make_card(0, teachers=[1], atoms=["a"], periods=4), make_card(1, teachers=[2], atoms=["b"], periods=4)]
        cards[0].starts = [(0, 1), (0, 2)]
        rel = RelationshipSpec("birlikte", "same_time", 1, [[0], [1]])
        solution = cpsat.solve(make_problem(cards, periods=4, relationships=[rel]), time_limit=5, workers=1)
        self.assertEqual(solution.placements[0].period, solution.placements[1].period)

    def test_max_consecutive_relationship(self):
        cards = [make_card(k, lesson_id=k, teachers=[k], atoms=["a"], periods=4) for k in range(3)]
        rel = RelationshipSpec("art arda", "max_consecutive", 2, [[0, 1, 2]])
        problem = make_problem(cards, periods=4, relationships=[rel])
        solution = cpsat.solve(problem, time_limit=5, workers=1)
        periods = sorted(p.period for p in solution.placements.values())
        self.assertNotEqual(periods, [periods[0], periods[0] + 1, periods[0] + 2])

    def test_teacher_max_days(self):
        cards = [make_card(k, lesson_id=k, teachers=[1], atoms=[f"a{k}"], days=3, periods=2) for k in range(4)]
        limits = {1: TeacherLimits(max_days_per_week=2)}
        solution = cpsat.solve(make_problem(cards, days=3, periods=2, teacher_limits=limits), time_limit=5, workers=1)
        self.assertEqual(len({p.day for p in solution.placements.values()}), 2)

    def test_progress_callback_and_stop(self):
        cards = [make_card(k, lesson_id=k, teachers=[k % 3], atoms=[f"a{k % 4}"], days=5, periods=8) for k in range(30)]
        seen = []
        handle = cpsat.StopHandle()
        handle.stop()
        solution = cpsat.solve(make_problem(cards, days=5, periods=8), time_limit=30, workers=1, on_progress=seen.append, stop_handle=handle)
        self.assertTrue(solution.stats["stopped"])
        self.assertLess(solution.stats["wall_time"], 10)
