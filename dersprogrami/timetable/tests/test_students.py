"""Öğrenciler, seçmeli derslere dağıtım, öğrenci programı ve çözücüde öğrenci çakışmaları."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import copying, students
from timetable.models import Card, Division, Group, Lesson, Period, School, SchoolClass, Student, Subject, Teacher, Timetable
from timetable.solver.builder import build_problem
from timetable.solver.cpsat import solve


class StudentTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=2)
        for i in range(3):
            Period.objects.create(school=self.school, index=i, name=f"{i + 1}")
        self.a = SchoolClass.objects.create(school=self.school, name="1.KISIM", short="1SVN")
        self.b = SchoolClass.objects.create(school=self.school, name="2.KISIM", short="2SVN")
        division = Division.objects.create(school_class=self.a, name="G")
        self.g1 = Group.objects.create(division=division, name="Grup 1")
        self.g2 = Group.objects.create(division=division, name="Grup 2")
        self.subject = {}
        for short in ("MAT", "LAB", "BİL", "MÜZ"):
            self.subject[short] = Subject.objects.create(school=self.school, name=short.title(), short=short)

        def lesson(short, classes, teacher, groups=(), elective=False, capacity=None):
            t = Teacher.objects.create(school=self.school, first_name=teacher, last_name="Hoca")
            obj = Lesson.objects.create(school=self.school, subject=self.subject[short], elective=elective, capacity=capacity)
            obj.classes.set(classes)
            obj.groups.set(groups)
            obj.teachers.set([t])
            return obj

        self.mat = lesson("MAT", [self.a], "A")
        self.lab1 = lesson("LAB", [self.a], "B", groups=[self.g1])
        # Seçmeli BİL iki şube: biri 2. kısımla ortak açılmış
        self.bil1 = lesson("BİL", [self.a], "C", elective=True, capacity=1)
        self.bil2 = lesson("BİL", [self.b], "D", elective=True)
        self.muz = lesson("MÜZ", [self.b], "E", elective=True)
        self.user = User.objects.create_superuser("admin", "a@x.tr", "pw")
        self.client.force_login(self.user)

    def _import(self):
        return students.import_text(self.school, "1\tAyşe Kaya\t1SVN\tGrup 1\tBİL, MÜZ\n2\tCan Er\t1SVN\tGrup 2\tBİL\n3\tDeniz Ak\t2SVN\t\tBİL, XYZ")

    def test_import_and_attendance(self):
        added, updated, errors = self._import()
        self.assertEqual((added, updated), (3, 0))
        self.assertEqual(len(errors), 1)  # XYZ dersi yok
        ayse = Student.objects.get(number="1")
        self.assertEqual(list(ayse.groups.all()), [self.g1])
        att = students.attendance(self.school)
        self.assertEqual(att[ayse.id], {self.mat.id, self.lab1.id})  # seçmeliler kayıtla gelir
        can = Student.objects.get(number="2")
        self.assertEqual(att[can.id], {self.mat.id})  # LAB yalnız Grup 1
        added, updated, _ = students.import_text(self.school, "1\tAyşe Kaya Demir\t1SVN\tGrup 1\tBİL")
        self.assertEqual((added, updated), (0, 1))

    def test_distribute_respects_capacity_and_clashes(self):
        self._import()
        tt = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        Card.objects.create(timetable=tt, lesson=self.mat, day=0, period=0)
        Card.objects.create(timetable=tt, lesson=self.bil1, day=0, period=0)  # MAT ile aynı saatte
        Card.objects.create(timetable=tt, lesson=self.bil2, day=0, period=1)
        Card.objects.create(timetable=tt, lesson=self.muz, day=1, period=0)
        result = students.distribute(self.school, tt)
        ayse = Student.objects.get(number="1")
        # BİL1 MAT ile çakıştığı için 1. kısım öğrencileri BİL2'ye; BİL1'in tek yeri 2. kısımdan Deniz'e
        self.assertEqual(set(ayse.lessons.all()), {self.bil2, self.muz})
        self.assertEqual([s.number for s in self.bil1.students.all()], ["3"])
        self.assertEqual(result["unassigned"], [])
        self.assertEqual(students.clashes(self.school, tt), [])
        # Kontenjan: BİL1 doluyken MAT ile çakışan şube yerine de olsa boş şube seçilir
        self.bil2.capacity = 2
        self.bil2.save()
        reset = students.distribute(self.school, tt, reset=True)
        self.assertEqual(reset["assigned"], 4)
        self.assertLessEqual(self.bil1.students.count(), 1)
        # İkinci dağıtım mevcut kayıtları korur
        again = students.distribute(self.school, tt)
        self.assertEqual(again["assigned"], 0)
        self.assertEqual(again["kept"], 4)

    def test_solver_keeps_student_lessons_apart(self):
        self._import()
        ayse = Student.objects.get(number="1")
        self.bil2.students.add(ayse)
        self.muz.students.add(ayse)
        problem = build_problem(self.school)
        keys = {c.lesson_id: c.students for c in problem.cards}
        self.assertTrue(set(keys[self.bil2.id]) & set(keys[self.muz.id]))
        self.assertTrue(set(keys[self.mat.id]) & set(keys[self.muz.id]))
        solution = solve(problem, time_limit=10)
        self.assertTrue(solution.ok)
        place = {c.lesson_id: solution.placements[c.key] for c in problem.cards}
        cells = {(place[lid].day, place[lid].period) for lid in (self.mat.id, self.lab1.id, self.bil2.id, self.muz.id)}
        self.assertEqual(len(cells), 4)  # Ayşe'nin dört dersi dört ayrı saatte

    def test_pages(self):
        self._import()
        url = reverse("timetable:students", args=[self.school.pk])
        self.assertContains(self.client.get(url), "Ayşe Kaya")
        self.client.post(url, {"action": "distribute"})
        ayse = Student.objects.get(number="1")
        page = self.client.get(reverse("timetable:student_timetable", args=[self.school.pk, ayse.pk]))
        self.assertEqual(page.status_code, 200)
        self.client.post(url, {"action": "delete", "sec": [ayse.pk]})
        self.assertFalse(Student.objects.filter(pk=ayse.pk).exists())

    def test_copy_program_with_students(self):
        self._import()
        students.distribute(self.school)
        target, parts = copying.copy_program(self.school, "Kopya", {"ogrenciler"})
        self.assertIn("dersler", parts)
        self.assertEqual(target.students.count(), 3)
        self.assertEqual(sum(lesson.students.count() for lesson in target.lessons.all()),
                         sum(lesson.students.count() for lesson in self.school.lessons.all()))
