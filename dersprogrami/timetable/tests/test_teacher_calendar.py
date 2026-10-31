"""Öğretmenin Programım sayfası ve telefon takvimi (.ics) aboneliği."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from timetable import teacher_calendar as tc
from timetable.models import (Absence, Card, Duty, DutyPlace, Institution, Lesson, Membership, Period, School, SchoolClass,
                              Subject, Substitution, Teacher, Timetable)


class TeacherCalendarTests(TestCase):
    def setUp(self):
        inst = Institution.objects.create(name="Kurum")
        self.school = School.objects.create(name="MYO", days_per_week=5, institution=inst)
        for i in range(2):
            Period.objects.create(school=self.school, index=i, name=str(i + 1), start_time=datetime.time(8 + i, 0),
                                  end_time=datetime.time(8 + i, 40))
        self.user = User.objects.create_user("ali", password="pw")
        Membership.objects.create(user=self.user, institution=inst, permissions=[Membership.VIEW])
        self.ali = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya", user=self.user)
        self.can = Teacher.objects.create(school=self.school, first_name="Can", last_name="Er")
        self.tt = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        self.school.active_timetable = self.tt
        self.school.save()
        subject = Subject.objects.create(school=self.school, name="Fizik", short="FİZ")
        self.lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=5)
        self.lesson.classes.add(SchoolClass.objects.create(school=self.school, name="1A"))
        self.lesson.teachers.add(self.ali)
        for day in range(5):  # her gün 1. saat
            Card.objects.create(timetable=self.tt, lesson=self.lesson, length=1, day=day, period=0)
        other = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=1)
        other.classes.add(SchoolClass.objects.create(school=self.school, name="2B"))
        other.teachers.add(self.can)
        self.other_card = Card.objects.create(timetable=self.tt, lesson=other, length=1, day=0, period=1)

    def test_events_absence_substitution_and_duty(self):
        today = timezone.localdate()
        monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=1)
        Absence.objects.create(school=self.school, teacher=self.ali, date=monday + datetime.timedelta(days=1), reason="Rapor")
        absence = Absence.objects.create(school=self.school, teacher=self.can, date=monday)
        Substitution.objects.create(absence=absence, card=self.other_card, period=1, substitute=self.ali)
        Duty.objects.create(place=DutyPlace.objects.create(school=self.school, name="Bahçe"), day=2, teacher=self.ali)
        items = tc.events(self.ali, monday, monday + datetime.timedelta(days=7))
        kinds = [(e["date"].weekday(), e["kind"]) for e in items]
        self.assertIn((0, "vekalet"), kinds)
        self.assertIn((1, "izin"), kinds)
        self.assertIn((2, "nobet"), kinds)
        self.assertEqual(sum(1 for _, k in kinds if k == "ders"), 4)
        lesson = next(e for e in items if e["kind"] == "ders")
        self.assertEqual((lesson["start"], lesson["end"]), (datetime.time(8), datetime.time(8, 40)))

    def test_page_token_and_public_ics(self):
        self.client.force_login(self.user)
        url = reverse("timetable:my_timetable")
        page = self.client.get(url)
        self.assertContains(page, "Takvim bağlantısı oluştur")
        self.assertEqual(page.context["grid"]["hours"], 5)
        self.client.post(url, {"ogretmen": self.ali.pk, "action": "create"})
        self.ali.refresh_from_db()
        token = self.ali.calendar_token
        self.assertTrue(len(token) >= 20)
        self.client.logout()
        response = self.client.get(reverse("timetable:teacher_ics", args=[token]))  # giriş gerekmez
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("SUMMARY:FİZ · 1A", body)
        self.assertIn("BEGIN:VTIMEZONE", body)
        self.assertTrue(all(len(line.encode()) <= 75 for line in body.split("\r\n")))
        # Yenilenince eski bağlantı çalışmaz
        self.client.force_login(self.user)
        self.client.post(url, {"ogretmen": self.ali.pk, "action": "renew"})
        self.client.logout()
        self.assertEqual(self.client.get(reverse("timetable:teacher_ics", args=[token])).status_code, 404)

    def test_unlinked_user(self):
        self.client.force_login(User.objects.create_user("x", password="pw"))
        self.assertContains(self.client.get(reverse("timetable:my_timetable")), "bağlı değil")
