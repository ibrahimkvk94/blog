from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable import services
from timetable.models import Timetable
from timetable.solver import cpsat
from timetable.tests.test_generation_flow import _school


@override_settings(AUTO_BACKUP=False, TIMETABLE_RUN_IN_BACKGROUND=False, TIMETABLE_JOB_BACKEND="thread")
class Gen3FlowTests(TestCase):
    def setUp(self):
        self.school, _ = _school()

    def test_web_queue_preserves_algorithm_and_starts_without_automatic_hint(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        with override_settings(TIMETABLE_JOB_BACKEND="worker"):
            response = self.client.post(reverse("timetable:generate", args=[self.school.pk]), {"mode": "gen3"})
        self.assertEqual(response.status_code, 302)
        tt = self.school.timetables.get()
        self.assertEqual(tt.mode, Timetable.STRICT)
        self.assertEqual(tt.time_limit, 1800)
        self.assertTrue(tt.report["from_scratch"])
        with mock.patch.object(services.input_diff, "best_hint") as hint, \
                mock.patch.object(services.cpsat, "solve", wraps=cpsat.solve) as solve:
            services.run_generation(tt.pk)
        hint.assert_not_called()
        self.assertEqual(solve.call_args.kwargs["algorithm"], "gen3")
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.OK)
        self.assertEqual(tt.hard_violations, 0)
        self.assertEqual(tt.generation_label, "Gen3 (Blok)")

    def test_timeout_does_not_launch_relaxed_search_or_claim_impossibility(self):
        with mock.patch.object(services.cpsat, "solve", return_value=cpsat.Solution(status="unknown")) as solve:
            tt = services.generate_timetable(self.school, "Blok", mode=Timetable.GEN3, time_limit=5)
        solve.assert_called_once()
        self.assertEqual(tt.status, Timetable.FAILED)
        self.assertIn("çözüm olmadığı anlamına gelmez", tt.report["error"])
        self.assertFalse(tt.cards.exists())

    def test_creation_pages_offer_gen3(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        for url in (reverse("timetable:school_detail", args=[self.school.pk]),
                    reverse("timetable:setup_wizard", args=[self.school.pk, "uret"])):
            self.assertContains(self.client.get(url), 'name="mode" value="gen3"')
