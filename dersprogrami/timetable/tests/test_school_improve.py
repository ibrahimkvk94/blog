"""Okul geneli iyileştirme: arka plan işi, ilerleme, öneri olarak sonuç ve çözüm merkezine aktarım."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from timetable import school_improve
from timetable.models import Card, ImproveJob, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable


@override_settings(TIMETABLE_RUN_IN_BACKGROUND=False)
class SchoolImproveTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Okul", days_per_week=3)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        subject = Subject.objects.create(school=self.school, name="Fizik", short="FİZ")
        # İki öğretmen: biri aynı gün 1. ve 4. saatte (2 boşluk), diğeri iki ayrı günde birer ders (1 gün fazla)
        self.ayse = Teacher.objects.create(school=self.school, first_name="Ayşe", last_name="Er")
        self.can = Teacher.objects.create(school=self.school, first_name="Can", last_name="Ak")
        for n, (teacher, cells) in enumerate(((self.ayse, ((0, 0), (0, 3))), (self.can, ((1, 0), (2, 0)))), 1):
            cls = SchoolClass.objects.create(school=self.school, name=f"{n}.KISIM")  # öğretmen başına bir sınıf
            for day, period in cells:
                lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=1, card_length=1)
                lesson.teachers.add(teacher)
                lesson.classes.add(cls)
                Card.objects.create(timetable=self.timetable, lesson=lesson, length=1, day=day, period=period)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:school_improve", args=[self.timetable.pk])

    def test_job_improves_and_hands_over_to_solution_center(self):
        before = list(self.timetable.cards.values_list("day", "period"))
        self.client.post(self.url, {"action": "start", "dakika": "10"})
        job = ImproveJob.objects.get()
        self.assertEqual(job.status, ImproveJob.DONE)  # iyileşecek şey kalmayınca süre dolmadan biter
        totals = job.result["totals"]
        self.assertEqual((totals["before"]["teacher_days"], totals["after"]["teacher_days"]), (3, 2))
        self.assertLess(totals["after"]["teacher_gaps"], totals["before"]["teacher_gaps"])
        self.assertEqual(job.result["new_violations_hard"], 0)
        self.assertGreaterEqual(job.progress["accepted"], 1)
        # Program değişmedi; sonuç öneri olarak bekliyor
        self.assertEqual(list(self.timetable.cards.values_list("day", "period")), before)
        page = self.client.get(self.url)
        self.assertContains(page, "Çözüm merkezinde incele ve uygula")
        status = self.client.get(self.url + "?durum=1").json()["job"]
        self.assertEqual((status["status"], status["has_result"]), ("done", True))
        # Çözüm merkezine aktarılır ve oradan uygulanır
        response = self.client.post(self.url, {"action": "review", "is": job.pk})
        self.assertRedirects(response, reverse("timetable:solution_center", args=[self.timetable.pk]) + "?goster=1")
        self.assertContains(self.client.get(response.url), school_improve.LABEL)
        self.client.post(reverse("timetable:solution_center", args=[self.timetable.pk]), {"action": "apply", "oneri": "0"})
        self.assertNotEqual(list(self.timetable.cards.values_list("day", "period")), before)

    def test_stop_and_stale_and_access(self):
        job = ImproveJob.objects.create(timetable=self.timetable, status=ImproveJob.RUNNING, heartbeat=timezone.now())
        self.assertEqual(school_improve.active_job(self.timetable), job)
        self.client.post(self.url, {"action": "stop"})
        job.refresh_from_db()
        self.assertTrue(job.stop_requested)
        ImproveJob.objects.filter(pk=job.pk).update(heartbeat=timezone.now() - timedelta(minutes=10))
        self.assertIsNone(school_improve.active_job(self.timetable))
        self.assertEqual(ImproveJob.objects.get(pk=job.pk).status, ImproveJob.FAILED)
        # Sırada bekleyen iş durdurulunca iptal olur; stop isteği varsa çalışma hemen biter
        queued = ImproveJob.objects.create(timetable=self.timetable)
        school_improve.request_stop(queued)
        self.assertEqual(ImproveJob.objects.get(pk=queued.pk).status, ImproveJob.CANCELLED)
        viewer = User.objects.create_user("izleyici", password="pw")
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_already_good_timetable_reports_nothing(self):
        Card.objects.filter(lesson__teachers=self.ayse, period=3).update(period=1)
        Card.objects.filter(lesson__teachers=self.can, day=2).update(day=1, period=1)
        job = school_improve.start(self.timetable, None, 10)
        job.refresh_from_db()
        self.assertEqual((job.status, job.result), (ImproveJob.DONE, None))
        self.assertContains(self.client.get(self.url), "İyileştirme bulunamadı")
