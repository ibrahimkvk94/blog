"""Öğretmen atama sayfası ve ders formundaki öğretmen önerileri."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.data_views import _teacher_hints
from timetable.models import Lesson, School, SchoolClass, Subject, Teacher


class TeacherAssignTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO")
        self.math = Subject.objects.create(school=self.school, name="Matematik")
        self.ahmet = Teacher.objects.create(school=self.school, first_name="Ahmet", last_name="Er")
        self.mehmet = Teacher.objects.create(school=self.school, first_name="Mehmet", last_name="Kaya")
        self.ayse = Teacher.objects.create(school=self.school, first_name="Ayşe", last_name="Ak")
        self.ayse.subjects.add(self.math)
        self.lessons = []
        for name, teachers in (("2.KISIM", [self.ahmet]), ("10.KISIM", []), ("3.KISIM", [self.ahmet, self.mehmet])):
            lesson = Lesson.objects.create(school=self.school, subject=self.math, periods_per_week=3)
            lesson.classes.add(SchoolClass.objects.create(school=self.school, name=name))
            lesson.teachers.set(teachers)
            self.lessons.append(lesson)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:teacher_assign", args=[self.school.pk])

    def test_page_lists_sections_and_saves(self):
        page = self.client.get(self.url)
        self.assertContains(page, "1 öğretmensiz")
        rows = [r["classes"] for r in page.context["rows"]]
        self.assertEqual(rows, ["2.KISIM", "3.KISIM", "10.KISIM"])  # doğal sıralama
        data = page.context["options_json"]
        self.assertEqual([t["name"] for t in data["teaching"]], ["Ahmet Er", "Mehmet Kaya"])
        self.assertEqual([t["name"] for t in data["branch"]], ["Ayşe Ak"])
        l2, l10, l3 = self.lessons
        self.client.post(self.url, {"ders": self.math.pk, f"ogretmen-{l2.pk}": self.mehmet.pk,
                                    f"ogretmen-{l10.pk}": self.ayse.pk, f"ogretmen-{l3.pk}": ""})
        self.assertEqual(list(l2.teachers.all()), [self.mehmet])
        self.assertEqual(list(l10.teachers.all()), [self.ayse])
        self.assertEqual(l3.teachers.count(), 2)  # çok öğretmenli derse dokunulmaz

    def test_lesson_form_hints(self):
        hints = _teacher_hints(self.school)
        self.assertEqual(hints["teaching"][self.math.pk], sorted([self.ahmet.pk, self.mehmet.pk]))
        self.assertEqual(hints["branch"][self.math.pk], [self.ayse.pk])
        self.assertEqual(hints["loads"][self.ahmet.pk], 6)
        page = self.client.get(reverse("timetable:lesson_edit", args=[self.school.pk, self.lessons[0].pk]))
        self.assertContains(page, 'id="teacher-hints"')
