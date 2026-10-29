"""Sürüm karşılaştırma ve değişiklik bildirimi."""

import datetime

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable import change_report as cr, versions
from timetable.models import Card, Classroom, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable


class ChangeReportTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=str(i + 1), start_time=datetime.time(8 + i), end_time=datetime.time(8 + i, 40))
        self.ali = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya", email="ali@x.tr")
        self.can = Teacher.objects.create(school=self.school, first_name="Can", last_name="Er")
        self.room = Classroom.objects.create(school=self.school, name="Lab 1")
        self.tt = Timetable.objects.create(school=self.school, name="Yeni", status=Timetable.OK)
        self.cards = {}
        for name, teacher in (("Fizik", self.ali), ("Kimya", self.can)):
            lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name=name), periods_per_week=2)
            lesson.classes.add(SchoolClass.objects.create(school=self.school, name=f"1{name[0]}"))
            lesson.teachers.add(teacher)
            self.cards[name] = [Card.objects.create(timetable=self.tt, lesson=lesson, length=1, day=d, period=0) for d in (0, 1)]
        versions.save_version(self.tt, note="önce")
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:change_report", args=[self.tt.pk])

    def test_version_comparison_kinds(self):
        moved, roomed = self.cards["Fizik"]
        moved.day, moved.period = 2, 3
        moved.save()
        roomed.classroom = self.room
        roomed.save()
        self.cards["Kimya"][0].day = None  # programdan çıkarıldı
        self.cards["Kimya"][0].period = None
        self.cards["Kimya"][0].save()
        key = cr.default_source(self.tt)
        self.assertTrue(key.startswith("v-"))
        label, before = cr.resolve_source(self.tt, key)
        data = cr.describe(self.tt, cr.compare(self.tt, before))
        self.assertEqual((data["lessons"], data["changes"], data["teachers"]), (2, 3, 2))
        ali = next(g for g in data["groups"] if g["teacher"] == self.ali)
        kinds = sorted(i["kind"] for i in ali["items"])
        self.assertEqual(kinds, ["moved", "room"])
        move = next(i for i in ali["items"] if i["kind"] == "moved")
        self.assertEqual((move["before"], move["after"]), ("Pzt 1. saat (08:00–08:40)", "Çar 4. saat (11:00–11:40)"))
        can = next(g for g in data["groups"] if g["teacher"] == self.can)
        self.assertEqual(can["items"][0]["kind"], "removed")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_page_and_emails(self):
        other = Timetable.objects.create(school=self.school, name="Yayındaki", status=Timetable.OK)
        for card in Card.objects.filter(timetable=self.tt):
            Card.objects.create(timetable=other, lesson=card.lesson, length=1, day=card.day, period=card.period)
        self.school.active_timetable = other
        self.school.save()
        Card.objects.filter(pk=self.cards["Fizik"][0].pk).update(day=4, period=2)
        page = self.client.get(self.url)
        self.assertEqual(page.context["source"], f"tt-{other.pk}")
        self.assertContains(page, "Ali Kaya")
        self.assertNotContains(page, "Can Er</h2>")
        self.client.post(self.url, {"kaynak": f"tt-{other.pk}", "ogretmen": [self.ali.pk], "not": "Pazartesiden itibaren"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Fizik", mail.outbox[0].body)
        self.assertIn("Cum 3. saat", mail.outbox[0].body)
        self.assertIn("Pazartesiden itibaren", mail.outbox[0].body)
        # Aynı programla fark yok
        self.assertContains(self.client.get(self.url + f"?kaynak=tt-{self.tt.pk}"), "Fark yok")


class TeacherChangeTests(TestCase):
    """Sürümler öğretmen atamalarını saklar; değişiklik bildirimi öğretmen değişimini gösterir, geri yükleme geri alır."""

    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        Period.objects.create(school=self.school, index=0, name="1", start_time=datetime.time(8), end_time=datetime.time(8, 40))
        self.ali = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya")
        self.can = Teacher.objects.create(school=self.school, first_name="Can", last_name="Er")
        self.lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Fizik"), periods_per_week=1)
        self.lesson.classes.add(SchoolClass.objects.create(school=self.school, name="1A"))
        self.lesson.teachers.add(self.ali)
        self.tt = Timetable.objects.create(school=self.school, name="Yeni", status=Timetable.OK)
        Card.objects.create(timetable=self.tt, lesson=self.lesson, length=1, day=0, period=0)
        self.version = versions.save_version(self.tt, note="önce")

    def test_teacher_change_reported_and_restored(self):
        self.assertEqual(self.version.teachers, {str(self.lesson.pk): [self.ali.pk]})
        self.lesson.teachers.set([self.can])
        self.assertIsNotNone(versions.save_version(self.tt, auto=True))  # yalnızca öğretmen değişti: yine kaydedilir
        label, before = cr.resolve_source(self.tt, f"v-{self.version.pk}")
        data = cr.describe(self.tt, cr.compare(self.tt, before))
        self.assertEqual(sorted(g["name"] for g in data["groups"]), ["Ali Kaya", "Can Er"])
        item = data["groups"][0]["items"][0]
        self.assertEqual((item["kind"], item["before"]), ("teacher", "Öğretmen: Ali Kaya"))
        self.assertTrue(item["after"].startswith("Öğretmen: Can Er · Pzt 1. saat"))
        result = versions.restore(self.tt, self.version)
        self.assertIn("1 dersin öğretmeni geri alındı", result["message"])
        self.assertEqual(list(self.lesson.teachers.all()), [self.ali])
