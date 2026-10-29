"""Vekâlet bildirimi: yeni vekile görev, değiştirilen vekile iptal, sınıf öğretmenine özet (saatleriyle)."""

import datetime

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable.models import Absence, Card, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SubstitutionMailTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        Period.objects.create(school=self.school, index=0, name="1", start_time=datetime.time(8, 20), end_time=datetime.time(9))
        t = lambda name: Teacher.objects.create(school=self.school, first_name=name, last_name="Öğretmen", email=f"{name.lower()}@x.tr")  # noqa: E731
        self.absent, self.first, self.second, self.head = t("Ali"), t("Bora"), t("Cem"), t("Deniz")
        cls = SchoolClass.objects.create(school=self.school, name="1A", class_teacher=self.head)
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Fizik"), periods_per_week=1)
        lesson.classes.add(cls)
        lesson.teachers.add(self.absent)
        tt = Timetable.objects.create(school=self.school, name="Ana", status=Timetable.OK)
        self.card = Card.objects.create(timetable=tt, lesson=lesson, length=1, day=0, period=0)
        self.school.active_timetable = tt
        self.school.save()
        self.date = datetime.date(2026, 11, 2)  # pazartesi
        self.absence = Absence.objects.create(school=self.school, date=self.date, teacher=self.absent)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def save(self, teacher):
        url = reverse("timetable:substitutions", args=[self.school.pk])
        self.client.post(url + f"?tarih={self.date.isoformat()}", {"action": "save", "absence": self.absence.pk, "tarih": self.date.isoformat(),
                                                                  f"slot-{self.card.pk}-0": str(teacher.pk), "notify": "1"})

    def mails(self):
        return {m.to[0]: (m.subject, m.body) for m in mail.outbox}

    def test_assign_then_change(self):
        self.save(self.first)
        sent = self.mails()
        self.assertEqual(set(sent), {"bora@x.tr", "deniz@x.tr"})
        self.assertIn("1. saat (08:20–09:00) · Fizik · 1A", sent["bora@x.tr"][1])
        self.assertIn("→ Bora Öğretmen", sent["deniz@x.tr"][1])
        mail.outbox.clear()
        self.save(self.second)
        sent = self.mails()
        self.assertEqual(set(sent), {"cem@x.tr", "bora@x.tr", "deniz@x.tr"})
        self.assertTrue(sent["bora@x.tr"][0].startswith("Vekâlet görevi iptal"))
        mail.outbox.clear()
        self.save(self.second)  # değişiklik yok: e-posta yok
        self.assertEqual(mail.outbox, [])
