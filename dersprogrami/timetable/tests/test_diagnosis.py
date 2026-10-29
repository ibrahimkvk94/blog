"""Katı modda program bulunamazsa: kurallar esnetilerek en yakın taslak üretilir ve neden raporu verilir."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable.models import CardRelationship, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable
from timetable.services import start_generation


@override_settings(TIMETABLE_RUN_IN_BACKGROUND=False)
class DiagnosisTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=2)
        for i in range(3):
            Period.objects.create(school=self.school, index=i, name=str(i + 1), start_time=datetime.time(8 + i), end_time=datetime.time(8 + i, 40))
        # Aynı öğretmenin iki dersi "aynı anda" olsun (kesin): öğretmen iki yerde olamaz, katı modda imkânsız.
        # Ön denetim bunu göremez; üretim imkânsızlığı bulur.
        self.teacher = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya")
        lessons = []
        for name, cls in (("Fizik", "1A"), ("Kimya", "1B")):
            lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name=name), periods_per_week=1)
            lesson.classes.add(SchoolClass.objects.create(school=self.school, name=cls))
            lesson.teachers.add(self.teacher)
            lessons.append(lesson)
        self.rel = CardRelationship.objects.create(school=self.school, name="Birlikte", condition=CardRelationship.SAME_TIME,
                                                   importance=CardRelationship.STRICT)
        self.rel.lessons.set(lessons)

    def test_strict_failure_gives_draft_and_reasons(self):
        tt = start_generation(self.school, "deneme", time_limit=10)
        tt.refresh_from_db()
        self.assertEqual(tt.mode, Timetable.RELAXED)  # en yakın taslak kaydedildi
        self.assertTrue(tt.has_grid)
        self.assertEqual(tt.report["strict_failed"]["status"], "infeasible")
        d = tt.report["diagnosis"]
        self.assertTrue(d["found"])
        self.assertIn("Birlikte", d["main"][0]["label"])
        self.assertEqual(d["main"][0]["url"], reverse("timetable:data_edit", args=[self.school.pk, "kart-iliskileri", self.rel.pk]))
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        page = self.client.get(reverse("timetable:timetable_detail", args=[tt.pk]))
        self.assertContains(page, "Katı modda program bulunamadı")
        self.assertContains(page, "Asıl neden")
        self.assertContains(page, "Birlikte")
