"""Gün bazlı ayrıştırma (solver/daysplit.py): gün modeli, gün alt problemleri ve uçtan uca üretim."""

from django.test import SimpleTestCase

from timetable.solver import daysplit
from timetable.solver.problem import RelationshipSpec, TeacherLimits
from timetable.solver.validate import validate
from timetable.tests.test_solver import make_card, make_problem


def hard(problem, placements):
    return [v for v in validate(problem, placements)[0] if v.level == "hard"]


class DaySplitTests(SimpleTestCase):
    def solve(self, problem, seconds=20):
        return daysplit.solve(problem, time_limit=seconds, workers=1)

    def test_full_class_with_consecutive_pair_is_solved_and_valid(self):
        # Sınıfın haftası tamamen dolu (2 gün × 3 saat = 6 saat) ve iki kart art arda olmak zorunda.
        cards = [
            make_card(0, length=2, teachers=[1], atoms=["a"], days=2, periods=3),
            make_card(1, length=1, teachers=[2], atoms=["a"], days=2, periods=3),
            make_card(2, length=1, teachers=[1], atoms=["a"], days=2, periods=3),
            make_card(3, length=1, teachers=[3], atoms=["a"], days=2, periods=3),
            make_card(4, length=1, teachers=[2], atoms=["a"], days=2, periods=3),
        ]
        problem = make_problem(cards, days=2, periods=3, relationships=[
            RelationshipSpec("Ardışık", "consecutive_ordered", 1, [[1], [2]]),
        ])
        result = self.solve(problem)
        self.assertEqual(result.status, "ok", result.rounds)
        self.assertEqual(len(result.placements), 5)
        self.assertFalse(hard(problem, result.placements))
        a, b = result.placements[1], result.placements[2]
        self.assertEqual((a.day, a.period + 1), (b.day, b.period))

    def test_day_model_separates_cards_that_cannot_share_a_window(self):
        # Aynı öğretmenin iki 2 saatlik kartı birinci günde yalnızca 0–2. saatlerde başlayabilir: o güne ikisi sığmaz.
        cards = [
            make_card(0, length=2, teachers=[1], starts=[(0, 0), (0, 1), (1, 0), (1, 2)]),
            make_card(1, length=2, teachers=[1], starts=[(0, 0), (0, 1), (1, 0), (1, 2)]),
        ]
        problem = make_problem(cards, days=2, periods=4, lesson_max_per_day={})
        model = daysplit._DayModel(problem)
        _, assignment, _ = model.solve(5, 1, 0)
        self.assertFalse(assignment[0] == assignment[1] == 0)

    def test_paired_cards_go_to_a_day_where_they_fit_together(self):
        cards = [
            make_card(0, teachers=[1], atoms=["a"], starts=[(0, 0), (1, 1)]),
            make_card(1, teachers=[2], atoms=["a"], starts=[(0, 3), (1, 2)]),
        ]
        problem = make_problem(cards, days=2, periods=4, relationships=[
            RelationshipSpec("Ardışık", "consecutive", 1, [[0], [1]]),
        ])
        model = daysplit._DayModel(problem)
        _, assignment, _ = model.solve(5, 1, 0)
        self.assertEqual(assignment, {0: 1, 1: 1})  # yalnızca 2. günde yan yana gelebilirler

    def test_lesson_limit_spreads_cards_over_days(self):
        cards = [make_card(k, lesson_id=7, teachers=[k], atoms=[f"a{k}"], days=3, periods=2) for k in range(3)]
        problem = make_problem(cards, days=3, periods=2, lesson_max_per_day={7: 1})
        result = self.solve(problem)
        self.assertEqual(result.status, "ok")
        self.assertEqual(sorted(p.day for p in result.placements.values()), [0, 1, 2])

    def test_multi_day_fill_moves_cards_between_days(self):
        # Üç kart aynı öğretmende; 0. günde yalnızca bir saat var. İki gün birlikte çözülünce hepsi yerleşir.
        cards = [make_card(k, teachers=[1], starts=[(0, 0), (1, 0), (1, 1)]) for k in range(3)]
        problem = make_problem(cards, days=2, periods=2, lesson_max_per_day={})
        places, missing, exact = daysplit._fill_days(problem, (0,), {0, 1, 2}, 5, 1, 0)
        self.assertEqual(len(missing), 2)
        places, missing, exact = daysplit._fill_days(problem, (0, 1), {0, 1, 2}, 5, 1, 0)
        self.assertEqual(missing, [])
        self.assertTrue(exact)
        self.assertFalse(hard(problem, places))

    def test_fixed_card_keeps_its_place(self):
        cards = [make_card(k, teachers=[1], atoms=["a"], days=2, periods=2) for k in range(4)]
        cards[2].fixed = (1, 0)
        problem = make_problem(cards, days=2, periods=2, lesson_max_per_day={})
        result = self.solve(problem)
        self.assertEqual(result.status, "ok")
        self.assertEqual((result.placements[2].day, result.placements[2].period), (1, 0))

    def test_teacher_days_limit_is_respected(self):
        cards = [make_card(k, teachers=[1], atoms=[f"a{k}"], days=3, periods=2) for k in range(4)]
        problem = make_problem(cards, days=3, periods=2, lesson_max_per_day={},
                               teacher_limits={1: TeacherLimits(max_days_per_week=2)})
        result = self.solve(problem)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len({p.day for p in result.placements.values()}), 2)

    def test_unsupported_rules_are_reported_without_solving(self):
        cards = [make_card(0, teachers=[1], days=2, periods=2), make_card(1, teachers=[1], days=2, periods=2)]
        problem = make_problem(cards, days=2, periods=2, relationships=[
            RelationshipSpec("Farklı gün", "max_per_day", 1, [[0, 1]]),
        ])
        result = self.solve(problem)
        self.assertEqual(result.status, "unsupported")
        self.assertTrue(result.reasons)
        self.assertEqual(result.rounds, [])

    def test_impossible_week_is_reported_as_infeasible(self):
        cards = [make_card(k, teachers=[1], days=1, periods=2) for k in range(3)]  # 3 saat ders, 2 saat yer
        problem = make_problem(cards, days=1, periods=2, lesson_max_per_day={})
        result = self.solve(problem, seconds=10)
        self.assertEqual(result.status, "infeasible")  # gün modeli kapasiteden bunu hemen görür
        self.assertEqual(result.placements, {})
