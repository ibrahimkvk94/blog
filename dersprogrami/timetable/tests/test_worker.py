"""Çalışan süreç kipi (TIMETABLE_JOB_BACKEND=worker): kuyruk, nabız, ilerleme, durdurma."""

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings

from timetable import jobs
from timetable.demo import create_demo_school
from timetable.models import Timetable
from timetable.services import refresh_stale, request_stop, start_generation


@override_settings(TIMETABLE_JOB_BACKEND="worker")
class WorkerTests(TransactionTestCase):
    def setUp(self):
        self.school = create_demo_school()

    def test_jobs_are_queued_and_run_by_worker(self):
        first = start_generation(self.school, "A", time_limit=15)
        second = start_generation(self.school, "B", time_limit=15)
        for t in (first, second):
            t.refresh_from_db()
            self.assertEqual((t.status, t.job_state), (Timetable.RUNNING, "queued"))
            self.assertEqual(refresh_stale(t).status, Timetable.RUNNING)  # sırada: bayat sayılmaz
        call_command("calisan", "--bir-kez", "--paralel", "2", stdout=open("/dev/null", "w"))
        for t in (first, second):
            t.refresh_from_db()
            self.assertEqual(t.status, Timetable.OK, t.report)
            self.assertEqual(t.job_state, "")
            self.assertEqual(t.cards.filter(day__isnull=True).count(), 0)

    def test_stop_queued_job(self):
        t = start_generation(self.school, "C", time_limit=15)
        request_stop(t)
        t.refresh_from_db()
        self.assertEqual(t.status, Timetable.FAILED)
        self.assertIn("iptal", t.report["error"])
        self.assertIsNone(jobs.claim_next())

    def test_dead_worker_is_detected(self):
        from datetime import timedelta

        from django.utils import timezone

        t = start_generation(self.school, "D", time_limit=15)
        Timetable.objects.filter(pk=t.pk).update(job_state="running", heartbeat=timezone.now() - timedelta(minutes=10),
                                                 started_at=timezone.now() - timedelta(minutes=10))
        t.refresh_from_db()
        self.assertEqual(refresh_stale(t).status, Timetable.FAILED)
