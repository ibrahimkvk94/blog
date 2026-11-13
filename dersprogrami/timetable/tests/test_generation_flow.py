"""Üretim akışı: taslak → turlu onarım → kesin kurallar; tek süre sınırı ve bağımsız doğrulama."""

import datetime
from unittest import mock

from django.test import TestCase, override_settings

from timetable import services
from timetable.models import Card, CardRelationship, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable
from timetable.services import start_generation
from timetable.solver import cpsat
from timetable.solver.builder import build_problem


def _school():
    school = School.objects.create(name="MYO", days_per_week=2)
    for i in range(3):
        Period.objects.create(school=school, index=i, name=str(i + 1), start_time=datetime.time(8 + i), end_time=datetime.time(8 + i, 40))
    teacher = Teacher.objects.create(school=school, first_name="Ali", last_name="Kaya")
    lessons = []
    for name, cls in (("Fizik", "1A"), ("Kimya", "1B")):
        lesson = Lesson.objects.create(school=school, subject=Subject.objects.create(school=school, name=name), periods_per_week=1)
        lesson.classes.add(SchoolClass.objects.create(school=school, name=cls))
        lesson.teachers.add(teacher)
        lessons.append(lesson)
    return school, lessons


@override_settings(TIMETABLE_RUN_IN_BACKGROUND=False)
class GenerationFlowTests(TestCase):
    def setUp(self):
        self.school, self.lessons = _school()
        # Kesin "aynı anda": aynı öğretmen iki derste olamayacağı için kesin kurallarla program yok.
        rel = CardRelationship.objects.create(school=self.school, name="Birlikte", condition=CardRelationship.SAME_TIME,
                                              importance=CardRelationship.STRICT)
        rel.lessons.set(self.lessons)

    def test_violated_draft_is_saved_without_extra_search(self):
        """Süre taslak turlarında dolduysa en iyi taslak kaydedilir; süre sınırını aşan ek arama yapılmaz."""
        problem = build_problem(self.school)
        draft = cpsat.solve(problem, time_limit=5, mode=cpsat.RELAXED, place_all=True)
        self.assertTrue(draft.ok and draft.relaxed_rules)
        unknown = cpsat.Solution(status="unknown", draft={k: (p.day, p.period) for k, p in draft.placements.items()},
                                 draft_solution=draft, stats={"draft_violations": 1, "mode": "strict"})
        with mock.patch.object(services.cpsat, "solve", return_value=unknown) as solve:
            tt = start_generation(self.school, "deneme", time_limit=10)
        self.assertEqual(solve.call_count, 1)  # tanı için ikinci bir arama yok
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.PARTIAL)
        self.assertEqual(tt.mode, Timetable.RELAXED)
        self.assertEqual(tt.report["strict_failed"]["violations"], 1)
        self.assertEqual(tt.hard_violations, 1)
        self.assertEqual(tt.status_label, "İhlalli taslak · 1")
        self.assertEqual(tt.status_class, "violated")
        self.assertEqual(tt.cards.filter(day__isnull=True).count(), 0)

    def test_success_requires_independent_validation(self):
        """Çözücü "tamam" dese de doğrulama kesin ihlal bulursa program "üretildi" sayılmaz."""
        problem = build_problem(self.school)
        draft = cpsat.solve(problem, time_limit=5, mode=cpsat.RELAXED, place_all=True)
        draft.status = "optimal"  # çözücü yanılmış gibi
        with mock.patch.object(services.cpsat, "solve", return_value=draft):
            tt = start_generation(self.school, "deneme", time_limit=10)
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.PARTIAL)
        self.assertGreater(tt.hard_violations, 0)


@override_settings(TIMETABLE_RUN_IN_BACKGROUND=False)
class RepairRoundsTests(TestCase):
    def test_rounds_are_recorded_and_stop_at_zero(self):
        import time

        from timetable.demo import create_demo_school

        school = create_demo_school()
        problem = build_problem(school)
        builder = cpsat._Builder(problem, cpsat.STRICT)
        model = builder.build()
        solver, callback, info = cpsat._repair_search(problem, builder, model, 40, time.monotonic(), 8, 0, None, None,
                                                      draft_until=0.9, fix_until=0.95)
        self.assertTrue(callback.found, info)
        self.assertEqual(info["violations"], 0)
        self.assertTrue(info["rounds"])
        self.assertEqual(info["rounds"][-1]["violations"], 0)
        self.assertIsNotNone(builder.best_draft_solution)
        self.assertEqual(builder.best_draft_solution.stats["violations"], 0)

    def test_refresh_status_follows_validation(self):
        school, lessons = _school()
        tt = start_generation(school, "deneme", time_limit=10)
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.OK)
        # Aynı öğretmenin iki dersini aynı saate koy: çakışma → ihlalli
        a, b = Card.objects.filter(timetable=tt).order_by("pk")
        b.day, b.period = a.day, a.period
        b.save()
        services.refresh_status(tt)
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.PARTIAL)
        self.assertGreater(tt.hard_violations, 0)
        b.day, b.period = (a.day, (a.period + 1) % 3)
        b.save()
        services.refresh_status(tt)
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.OK)
