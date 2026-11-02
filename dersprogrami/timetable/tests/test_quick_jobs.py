"""Ana görünümdeki "İhlalleri çöz" / "Cezayı düşür" arka plan işi (quick_jobs.py)."""

from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable import quick_jobs, school_improve
from timetable.demo import create_demo_school
from timetable.models import ImproveJob
from timetable.services import generate_timetable, verify_timetable


def hard(tt):
    return sum(1 for v in verify_timetable(tt)[0] if v.level == "hard")


@override_settings(TIMETABLE_RUN_IN_BACKGROUND=False)
class QuickJobTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.timetable = generate_timetable(cls.school, "t", time_limit=20)

    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def test_penalty_job_applies_and_reports(self):
        before = {c.id: (c.day, c.period) for c in self.timetable.cards.all()}
        hard_before = hard(self.timetable)  # örnek okulun üretimi süreye bağlı: 0 olmayabilir
        job = quick_jobs.start(self.timetable, None, ImproveJob.PENALTY, 60)
        job.refresh_from_db()
        self.assertEqual(job.status, ImproveJob.DONE, job.error)
        self.assertLessEqual(job.result["after"], job.result["before"])
        self.assertLessEqual(hard(self.timetable), hard_before)
        if job.result["moved"]:
            self.assertNotEqual({c.id: (c.day, c.period) for c in self.timetable.cards.all()}, before)

    def test_manual_edit_during_job_is_not_overwritten(self):
        card = self.timetable.cards.filter(day__isnull=False, locked=False).first()
        real = quick_jobs.services.penalty_search

        def search(timetable, *args, **kwargs):
            found = real(timetable, *args, **kwargs)
            card.locked = True  # iş sürerken kullanıcı bir kartı oynatır
            card.day = (card.day + 1) % 5
            card.save(update_fields=["day", "locked"])
            return {**found, "result": found["result"] or {}}

        with mock.patch.object(quick_jobs.services, "penalty_search", side_effect=search):
            job = quick_jobs.start(self.timetable, None, ImproveJob.PENALTY, 60)
        job.refresh_from_db()
        self.assertEqual(job.status, ImproveJob.FAILED)
        self.assertIn("elle değiştirildi", job.error)

    def test_one_job_at_a_time_and_stop(self):
        running = ImproveJob.objects.create(timetable=self.timetable, kind=ImproveJob.RESOLVE,
                                            status=ImproveJob.RUNNING, time_limit=600)
        response = self.client.post(reverse("timetable:api_penalty", args=[self.timetable.pk]),
                                    data='{"sure": 60}', content_type="application/json").json()
        self.assertFalse(response["ok"])
        self.assertIn("İhlalleri çöz", response["message"])
        state = self.client.post(reverse("timetable:api_quick_job", args=[self.timetable.pk])).json()["job"]
        self.assertTrue(state["stop_requested"])
        running.refresh_from_db()
        self.assertTrue(running.stop_requested)

    def test_school_improve_page_ignores_quick_jobs(self):
        ImproveJob.objects.create(timetable=self.timetable, kind=ImproveJob.PENALTY, status=ImproveJob.DONE,
                                  result={"message": "x"})
        self.assertIsNone(school_improve.active_job(self.timetable, ImproveJob.SCHOOL))
        page = self.client.get(reverse("timetable:school_improve", args=[self.timetable.pk]))
        self.assertIsNone(page.context["latest"])

    def test_detail_page_resumes_running_job(self):
        ImproveJob.objects.create(timetable=self.timetable, kind=ImproveJob.PENALTY, status=ImproveJob.RUNNING,
                                  time_limit=300, progress={"unit": "ceza", "now": 10})
        page = self.client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk]))
        self.assertEqual(page.context["config"]["quickJob"]["kind"], "penalty")

    def test_deep_resolve_falls_back_to_day_neighbourhood(self):
        """Kural ihlali (çakışma değil): iki farklı sınıfın tek saatlik dersleri kesin "aynı gün" olmalı ama farklı
        günlerde. Az değişiklikle onarım bir şey bulamazsa gün komşuluğu devralır."""
        from timetable import services
        from timetable.models import CardRelationship

        cards = list(self.timetable.cards.filter(day__isnull=False, locked=False, lesson__periods_per_week=1)
                     .select_related("lesson").prefetch_related("lesson__classes"))
        a = cards[0]
        b = next(c for c in cards if c.day != a.day and not set(c.lesson.classes.all()) & set(a.lesson.classes.all()))
        rel = CardRelationship.objects.create(school=self.school, name="Aynı gün", condition=CardRelationship.SAME_DAY,
                                              importance=CardRelationship.STRICT)
        rel.lessons.set([a.lesson, b.lesson])
        self.assertGreater(hard(self.timetable), 0)
        stages = []
        with mock.patch.object(services.cpsat, "minimal_repair", return_value=(None, None)):
            found = services.resolve_search(self.timetable, time_limit=services.DEEP_RESOLVE,
                                            on_progress=lambda p: stages.append(p["stage"]))
        self.assertIn("days", stages)
        self.assertEqual(found["after"], 0)
        self.assertEqual(len(found["result"]), len(found["problem"].cards))
