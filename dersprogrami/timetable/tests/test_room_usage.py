"""Derslik doluluk raporu."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import occupancy
from timetable.models import Availability, Card, Classroom, Lesson, Period, School, SchoolClass, Subject, Timetable


class RoomUsageTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=2)
        for i in range(2):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.lab = Classroom.objects.create(school=self.school, name="Lab 2")
        self.hall = Classroom.objects.create(school=self.school, name="Lab 10")
        Availability.objects.create(school=self.school, classroom=self.hall, day=1, period=1, state=Availability.NO)
        cls = SchoolClass.objects.create(school=self.school, name="1A")
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Fizik", short="FİZ"), periods_per_week=3)
        lesson.classes.set([cls])
        self.timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        Card.objects.create(timetable=self.timetable, lesson=lesson, length=2, day=0, period=0, classroom=self.lab)
        Card.objects.create(timetable=self.timetable, lesson=lesson, length=1, day=0, period=0, classroom=self.hall)
        Card.objects.create(timetable=self.timetable, lesson=lesson, length=1, day=None, period=None, classroom=self.hall)

    def test_report(self):
        data = occupancy.report(self.timetable)
        lab, hall = data["rooms"]  # doğal sıralama: Lab 2, Lab 10
        self.assertEqual((lab["room"], lab["used"], lab["open"], lab["pct"]), (self.lab, 2, 4, 50))
        self.assertEqual((hall["used"], hall["open"], hall["pct"]), (1, 3, 33))
        self.assertEqual(hall["strip"][1][1], "closed")
        first = data["grid"][0]["cells"][0]
        self.assertEqual((first["pct"], first["used"], first["free"]), (100, 2, []))
        self.assertIn("Lab 2: FİZ (1A)", first["busy"])
        last = data["grid"][1]["cells"][1]  # Lab 10 kapalı → yalnızca Lab 2 açık
        self.assertEqual((last["open"], last["pct"], last["free"]), (1, 0, ["Lab 2"]))
        s = data["summary"]
        self.assertEqual((s["rooms"], s["average"], s["peak"]["pct"], s["unused"]), (2, 42, 100, 0))

    def test_page(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        response = self.client.get(reverse("timetable:room_usage", args=[self.timetable.pk]))
        self.assertContains(response, "Derslik doluluğu")
        self.assertContains(response, "ru-days")
