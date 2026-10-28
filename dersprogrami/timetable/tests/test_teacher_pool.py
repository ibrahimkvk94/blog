"""Öğretmen havuzu: ders adının kısımlarına öğretmeni kotalara göre üretimde çözücü seçer."""

from collections import Counter

from django.test import TestCase

from timetable.models import Availability, Lesson, Period, School, SchoolClass, Subject, Teacher, TeacherQuota, Timetable
from timetable.services import generate_timetable
from timetable.solver import cpsat
from timetable.solver.problem import Problem, ProblemCard, TeacherPool

U = frozenset({(0, 0)})


def _card(key, starts, teachers=()):
    return ProblemCard(key=key, lesson_id=key, length=1, teachers=teachers, atoms=(f"a{key}",), room_options=(),
                       universes=U, starts=starts)


class PoolSolverTests(TestCase):
    def test_parallel_sections_get_different_teachers(self):
        cards = [_card(k, [(0, 0)]) for k in range(3)]
        pool = TeacherPool("TEM100", (0, 1, 2), {1: 1, 2: 1, 3: 1})
        solution = cpsat.solve(Problem(days=1, periods=2, universes=U, cards=cards, teacher_pools=[pool]), time_limit=5, workers=1)
        self.assertTrue(solution.ok)
        self.assertEqual(sorted(solution.teacher_choice.values()), [1, 2, 3])
        # Aynı saatteki 3 kısma 2 öğretmen yetmez
        pool.quotas = {1: 2, 2: 1}
        self.assertEqual(cpsat.solve(Problem(days=1, periods=2, universes=U, cards=cards, teacher_pools=[pool]),
                                     time_limit=5, workers=1).status, "infeasible")
        # Kısımlar iki saate yayılabiliyorsa 2 öğretmen yeter ve kotalar tutar
        for c in cards:
            c.starts = [(0, 0), (0, 1)]
        solution = cpsat.solve(Problem(days=1, periods=2, universes=U, cards=cards, teacher_pools=[pool]), time_limit=5, workers=1)
        self.assertEqual(Counter(solution.teacher_choice.values()), Counter({1: 2, 2: 1}))
        by_teacher = {}
        for lesson_id, t in solution.teacher_choice.items():
            by_teacher.setdefault(t, []).append(solution.placements[lesson_id].period)
        self.assertEqual(sorted(by_teacher[1]), [0, 1])

    def test_closed_cells_and_fixed_lessons_of_pool_teachers(self):
        # Öğretmen 1: (0,0)'da gelemiyor; öğretmen 2: (0,1)'de başka sınıfta sabit dersi var
        cards = [_card(0, [(0, 0)]), _card(1, [(0, 1)]), _card(2, [(0, 1)], teachers=(2,))]
        pool = TeacherPool("X", (0, 1), {1: 1, 2: 1}, closed={1: frozenset({(0, 0)})})
        solution = cpsat.solve(Problem(days=1, periods=2, universes=U, cards=cards, teacher_pools=[pool]), time_limit=5, workers=1)
        self.assertEqual(solution.teacher_choice, {0: 2, 1: 1})


class PoolGenerationTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=1)
        for i in range(3):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.math = Subject.objects.create(school=self.school, name="Matematik", short="TEM100")
        self.t = [Teacher.objects.create(school=self.school, first_name=n, last_name="Hoca") for n in ("Ali", "Can")]
        self.lessons = []
        for i in range(4):
            lesson = Lesson.objects.create(school=self.school, subject=self.math, periods_per_week=1)
            lesson.classes.add(SchoolClass.objects.create(school=self.school, name=f"{i + 1}.KISIM"))
            self.lessons.append(lesson)
        # Ali 1. saatte gelemiyor
        Availability.objects.create(school=self.school, teacher=self.t[0], day=0, period=0, state=Availability.NO)

    def test_generation_assigns_by_quota_and_respects_lock(self):
        self.lessons[0].teachers.add(self.t[1])
        self.lessons[0].teacher_locked = True
        self.lessons[0].save()
        TeacherQuota.objects.create(school=self.school, subject=self.math, teacher=self.t[0], count=2)
        TeacherQuota.objects.create(school=self.school, subject=self.math, teacher=self.t[1], count=2)
        timetable = generate_timetable(self.school, "t", time_limit=10)
        self.assertEqual(timetable.status, Timetable.OK)
        assigned = {l.id: [t.id for t in l.teachers.all()] for l in Lesson.objects.filter(pk__in=[x.id for x in self.lessons])}
        self.assertEqual(assigned[self.lessons[0].id], [self.t[1].id])  # kilitli kısım değişmez
        self.assertEqual(Counter(ts[0] for ts in assigned.values()), Counter({self.t[0].id: 2, self.t[1].id: 2}))
        # Ali'nin kısımları 1. saatte değil; hiçbir öğretmen aynı saatte iki kısımda değil
        for card in timetable.cards.all():
            teacher = card.lesson.teachers.first()
            if teacher == self.t[0]:
                self.assertNotEqual(card.period, 0)
        cells = Counter((c.lesson.teachers.first().id, c.day, c.period) for c in timetable.cards.all())
        self.assertEqual(max(cells.values()), 1)
        self.assertEqual(timetable.report["pools"]["changed"], 3)
        self.assertFalse(timetable.report["validation"]["violations"])
        from django.contrib.auth.models import User
        from django.urls import reverse

        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        page = self.client.get(reverse("timetable:timetable_detail", args=[timetable.pk]))
        self.assertContains(page, "kısmın öğretmeni değişti")

    def test_wrong_quota_stops_generation(self):
        TeacherQuota.objects.create(school=self.school, subject=self.math, teacher=self.t[0], count=1)
        timetable = generate_timetable(self.school, "t", time_limit=10)
        self.assertEqual(timetable.status, Timetable.FAILED)
        self.assertTrue(any("kotaları tutmuyor" in i["message"] for i in timetable.report["issues"]))
