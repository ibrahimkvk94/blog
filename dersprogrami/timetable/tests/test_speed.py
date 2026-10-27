"""Üretim hızı: iki aşamalı arama ve kısmi (seçili kısım/öğretmen) yeniden üretim."""

from django.test import TestCase

from timetable.demo import create_demo_school
from timetable.models import Timetable
from timetable.services import freeze_except, generate_timetable, run_generation, verify_timetable
from timetable.solver import cpsat
from timetable.solver.builder import build_problem


class SpeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()

    def test_two_phase_finds_valid_timetable(self):
        problem = build_problem(self.school)
        solution = cpsat.solve(problem, time_limit=30, two_phase=True)
        self.assertTrue(solution.ok, solution.status)
        self.assertIn(solution.stats["phase1"]["status"], ("feasible", "optimal"))
        self.assertFalse(solution.unplaced)
        self.assertIsNotNone(solution.objective)

    def test_two_phase_reports_infeasible_early(self):
        problem = build_problem(self.school)
        teacher = next(iter(problem.teacher_limits))
        problem.teacher_limits[teacher].max_periods_per_day = 0
        solution = cpsat.solve(problem, time_limit=30, two_phase=True)
        self.assertEqual(solution.status, "infeasible")

    def test_stop_during_search_keeps_phase1_solution(self):
        problem = build_problem(self.school)
        handle = cpsat.StopHandle()
        solution = cpsat.solve(problem, time_limit=30, two_phase=True, stop_handle=handle,
                               on_progress=lambda p: handle.stop() if p.get("phase") == "feasible" else None)
        self.assertTrue(solution.ok, solution.status)
        self.assertFalse(solution.unplaced)

    def test_partial_regeneration_keeps_other_cards(self):
        base = generate_timetable(self.school, "taban", time_limit=20)
        cls = self.school.classes.get(name="9-A")
        problem = build_problem(self.school, base=base)
        frozen = freeze_except(problem, {"classes": [cls.pk]})
        self.assertGreater(frozen, 0)
        moving = [c for c in problem.cards if c.fixed is None]
        self.assertTrue(all(any(problem.atom_class(a) == cls.pk for a in c.atoms) for c in moving))

        # Arka plan iş parçacığı test işlemine yazamaz; aynı akış eşzamanlı çalıştırılır.
        timetable = Timetable.objects.create(
            school=self.school, name="kısmi", status=Timetable.RUNNING, time_limit=20,
            report={"base": base.pk, "only": {"classes": [cls.pk], "teachers": []}},
        )
        run_generation(timetable.pk, base.pk)
        timetable.refresh_from_db()
        self.assertEqual(timetable.status, Timetable.OK, timetable.report)
        self.assertEqual(timetable.report["frozen"], frozen)
        before = {(c.lesson_id, c.day, c.period) for c in base.cards.exclude(lesson__classes=cls)}
        after = {(c.lesson_id, c.day, c.period) for c in timetable.cards.exclude(lesson__classes=cls)}
        self.assertEqual(before, after)
        self.assertFalse([v for v in verify_timetable(timetable)[0] if v.level == "hard"])
