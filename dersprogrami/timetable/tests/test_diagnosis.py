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
        self.lessons = lessons
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

    def test_failure_lists_what_changed_since_last_success(self):
        from timetable.models import AuditLog

        self.rel.active = False
        self.rel.save()
        good = start_generation(self.school, "dün", time_limit=10)
        good.refresh_from_db()
        self.assertEqual(good.status, Timetable.OK)
        self.assertIn("rules", good.inputs)
        AuditLog.objects.create(school=self.school, username="ayse", action="Kart ilişkisi kaydetti", detail="Birlikte", path="/okul/x/veri/kart-iliskileri/1/")
        self.rel.active = True
        self.rel.save()
        self.teacher.max_periods_per_day = 2
        self.teacher.save()
        bad = start_generation(self.school, "bugün", time_limit=10)
        bad.refresh_from_db()
        ch = bad.report["changes"]
        self.assertEqual(ch["previous"]["id"], good.pk)
        kinds = {g["kind"]: g for g in ch["diff"]}
        self.assertEqual([name for name, _ in kinds["rules"]["added"]], ["Birlikte"])
        self.assertEqual(kinds["teachers"]["added"][0][0], "Ali Kaya")
        self.assertEqual([o["action"] for o in ch["operations"]], ["Kart ilişkisi kaydetti"])
        self.client.force_login(User.objects.create_superuser("admin2", "b@x.tr", "pw"))
        page = self.client.get(reverse("timetable:timetable_detail", args=[bad.pk]))
        self.assertContains(page, "Son başarılı üretimden bu yana neler değişti?")
        self.assertContains(page, "+ Birlikte")

    def test_relaxed_mode_explains_its_penalty(self):
        tt = start_generation(self.school, "esnek", time_limit=10, mode=Timetable.RELAXED)
        tt.refresh_from_db()
        self.assertIn("Birlikte", tt.report["diagnosis"]["main"][0]["label"])
        self.client.force_login(User.objects.create_superuser("admin3", "c@x.tr", "pw"))
        self.assertContains(self.client.get(reverse("timetable:timetable_detail", args=[tt.pk])), "Bu taslakta kesin kurallar esnetildi")

    def test_recheck_previous_success_with_today_data(self):
        from timetable import input_diff
        from timetable.models import Availability

        self.rel.active = False
        self.rel.save()
        good = start_generation(self.school, "dün", time_limit=10)
        card = good.cards.filter(lesson__subject__name="Fizik").first()
        Availability.objects.create(school=self.school, teacher=self.teacher, day=card.day, period=card.period, state=Availability.NO)
        result = input_diff.recheck(good)
        self.assertEqual([g["code"] for g in result["groups"]], ["blocked_cell"])
        self.client.force_login(User.objects.create_superuser("admin4", "d@x.tr", "pw"))
        page = self.client.get(reverse("timetable:backup_compare", args=[self.school.pk]) + f"?program={good.pk}")
        self.assertContains(page, "Artık yasak olan saate düşen dersler")

    def test_last_success_is_used_as_hint_unless_from_scratch(self):
        self.rel.active = False
        self.rel.save()
        first = start_generation(self.school, "ilk", time_limit=10)
        second = start_generation(self.school, "ikinci", time_limit=10)
        second.refresh_from_db()
        self.assertEqual(second.report["hint_from"]["id"], first.pk)
        third = start_generation(self.school, "sıfır", time_limit=10, from_scratch=True)
        third.refresh_from_db()
        self.assertNotIn("hint_from", third.report)
