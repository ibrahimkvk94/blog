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


class StudentRuleTests(TestCase):
    """Seçmeli ve öğrenci kuralları (kart ilişkisi olarak tanımlanır, dağıtımda uygulanır)."""

    def setUp(self):
        from timetable.models import CardRelationship

        self.R = CardRelationship
        self.school = School.objects.create(name="MYO", days_per_week=1, terms_count=2)
        Period.objects.create(school=self.school, index=0, name="1")
        self.cls = SchoolClass.objects.create(school=self.school, name="1.KISIM")
        self.ali = Teacher.objects.create(school=self.school, first_name="Ali", last_name="K")
        self.veli = Teacher.objects.create(school=self.school, first_name="Veli", last_name="C")
        self.x = Subject.objects.create(school=self.school, name="X", short="X")
        self.y = Subject.objects.create(school=self.school, name="Y", short="Y")

        def section(subject, teacher, term=None):
            obj = Lesson.objects.create(school=self.school, subject=subject, elective=True, terms_mask=term)
            obj.classes.set([self.cls])
            obj.teachers.set([teacher])
            return obj

        self.x_ali, self.x_veli = section(self.x, self.ali, 1), section(self.x, self.veli, 2)
        self.y_ali, self.y_veli = section(self.y, self.ali, 1), section(self.y, self.veli, 2)
        self.st = Student.objects.create(school=self.school, first_name="Ayşe", school_class=self.cls)
        self.st.choices.set([self.x, self.y])

    def rule(self, condition, a=(), b=(), teachers=(), param=1, importance="strict"):
        rel = self.R.objects.create(school=self.school, name=condition, condition=condition, param=param, importance=importance)
        rel.subjects.set(a)
        rel.subjects_b.set(b)
        rel.teachers.set(teachers)
        return rel

    def sections(self):
        return {lesson.subject_id: lesson for lesson in self.st.lessons.all()}

    def test_same_and_different_teacher(self):
        self.rule("st_same_teacher", a=[self.x, self.y])
        students.distribute(self.school, reset=True)
        mine = self.sections()
        self.assertEqual(set(mine[self.x.id].teachers.all()), set(mine[self.y.id].teachers.all()))
        self.R.objects.all().delete()
        self.rule("st_diff_teacher", a=[self.x, self.y])
        students.distribute(self.school, reset=True)
        mine = self.sections()
        self.assertNotEqual(set(mine[self.x.id].teachers.all()), set(mine[self.y.id].teachers.all()))

    def test_teacher_list(self):
        self.rule("st_teacher_in", a=[self.x, self.y], teachers=[self.veli])
        students.distribute(self.school, reset=True)
        self.assertEqual(set(self.st.lessons.all()), {self.x_veli, self.y_veli})
        self.R.objects.all().delete()
        self.rule("st_teacher_not_in", a=[self.x, self.y], teachers=[self.veli])
        students.distribute(self.school, reset=True)
        self.assertEqual(set(self.st.lessons.all()), {self.x_ali, self.y_ali})

    def test_term_order(self):
        self.rule("st_term_before", a=[self.y], b=[self.x])  # Y, X'ten önceki dönemde
        students.distribute(self.school, reset=True)
        self.assertEqual(set(self.st.lessons.all()), {self.y_ali, self.x_veli})
        self.R.objects.all().delete()
        self.rule("st_same_term", a=[self.x], b=[self.y])
        students.distribute(self.school, reset=True)
        terms = {lesson.terms_mask for lesson in self.st.lessons.all()}
        self.assertEqual(len(terms), 1)

    def test_impossible_hard_rule_leaves_choice_unassigned(self):
        self.rule("st_teacher_in", a=[self.x], teachers=[])  # öğretmen listesi boş: hiçbir şube uymaz
        result = students.distribute(self.school, reset=True)
        self.assertEqual([s.id for s, subject, _ in result["unassigned"]], [self.st.id])

    def test_min_max_electives_warnings(self):
        self.rule("st_max_electives", a=[self.x, self.y], param=1)
        self.rule("st_min_electives", a=[self.x, self.y], param=2)
        warnings = students.rule_warnings(self.school)
        self.assertEqual(len(warnings), 1)
        self.assertIn("en fazla 1", warnings[0])

    def test_student_rules_skip_solver(self):
        self.rule("st_same_teacher", a=[self.x, self.y])
        self.assertEqual(build_problem(self.school).relationships, [])
