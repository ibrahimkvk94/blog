"""Genel bakış: programın durumu ve sıradaki işler."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.models import Card, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable


class DashboardTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=str(i + 1), start_time=datetime.time(8 + i), end_time=datetime.time(8 + i, 40))
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Fizik"), periods_per_week=2)
        lesson.classes.add(SchoolClass.objects.create(school=self.school, name="1A"))
        lesson.teachers.add(Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya"))
        self.lesson = lesson
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:school_detail", args=[self.school.pk])

    def test_without_timetable(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Henüz program yok")
        self.assertContains(page, 'id="uret"')
        self.assertNotContains(page, 'class="hero')

    def test_status_and_next_steps(self):
        tt = Timetable.objects.create(school=self.school, name="Güz", status=Timetable.OK)
        Card.objects.create(timetable=tt, lesson=self.lesson, length=1, day=0, period=0)
        Card.objects.create(timetable=tt, lesson=self.lesson, length=1)  # yerleşmemiş
        page = self.client.get(self.url)
        status = page.context["board"]["status"]
        self.assertEqual((status["waiting"], status["cards"], status["published"]), (1, 2, False))
        texts = [n["text"] for n in page.context["board"]["next"]]
        self.assertIn("1 kart yerleşmedi.", texts)
        self.assertIn("Bu program henüz yayında değil.", texts)
        self.assertContains(page, "Yayında değil")
        self.assertContains(page, reverse("timetable:pending", args=[tt.pk]))
