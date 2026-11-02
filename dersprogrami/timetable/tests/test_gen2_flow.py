"""Gen2 seçimi arayüzden, kuyruktan ve komut satırı servisinden katı çözücüye ulaşır."""

from unittest import mock
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from timetable import services
from timetable.models import Timetable
from timetable.solver import cpsat
from timetable.solver.builder import build_problem
from timetable.tests.test_generation_flow import _school


@override_settings(AUTO_BACKUP=False, TIMETABLE_RUN_IN_BACKGROUND=False, TIMETABLE_JOB_BACKEND="thread")
class Gen2FlowTests(TestCase):
    def setUp(self):
        self.school, _ = _school()

    def test_web_selection_survives_queue_and_reaches_strict_solver(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        with override_settings(TIMETABLE_JOB_BACKEND="worker"):
            response = self.client.post(reverse("timetable:generate", args=[self.school.pk]),
                                        {"mode": "gen2", "name": "Gen2 deneme", "base": "sifir", "time_limit": 5})
        self.assertEqual(response.status_code, 302)
        tt = self.school.timetables.get()
        self.assertEqual(tt.job_state, "queued")
        self.assertEqual(tt.mode, Timetable.STRICT)
        self.assertEqual(tt.report["algorithm"], "gen2")
        self.assertTrue(tt.report["from_scratch"])
        with mock.patch.object(services.cpsat, "solve", wraps=cpsat.solve) as solve:
            services.run_generation(tt.pk)
        self.assertEqual(solve.call_args.kwargs["algorithm"], "gen2")
        self.assertEqual(solve.call_args.kwargs["mode"], "strict")
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.OK)
        self.assertEqual(tt.hard_violations, 0)
        self.assertEqual(tt.generation_label, "Gen2")

    def test_synchronous_generation_and_legacy_route(self):
        for mode in (Timetable.GEN2, Timetable.STRICT):
            with self.subTest(mode=mode), mock.patch.object(services.cpsat, "solve", wraps=cpsat.solve) as solve:
                tt = services.generate_timetable(self.school, mode, time_limit=5, mode=mode)
                self.assertEqual(tt.status, Timetable.OK)
                self.assertEqual(solve.call_args.kwargs.get("algorithm"), "gen2" if mode == Timetable.GEN2 else None)

    def test_partial_result_retains_gen2_label_and_validation(self):
        problem = build_problem(self.school)
        draft = cpsat.solve(problem, mode=cpsat.RELAXED, place_all=True, time_limit=2)
        # Aynı öğretmenin iki dersini aynı saate koy: bağımsız denetim bunu yakalamalı.
        positions = list(draft.placements.values())
        positions[1].day, positions[1].period = positions[0].day, positions[0].period
        unknown = cpsat.Solution(status="unknown", draft_solution=draft, stats={"draft_violations": 1})
        with mock.patch.object(services.cpsat, "solve", return_value=unknown) as solve:
            tt = services.start_generation(self.school, "Gen2 taslak", mode=Timetable.GEN2, time_limit=5)
        solve.assert_called_once()
        tt.refresh_from_db()
        self.assertEqual(tt.mode, Timetable.RELAXED)
        self.assertEqual(tt.status, Timetable.PARTIAL)
        self.assertGreater(tt.hard_violations, 0)
        self.assertEqual(tt.generation_label, "Gen2")

    def test_creation_pages_offer_strict_and_relaxed_only(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        for url in (reverse("timetable:school_detail", args=[self.school.pk]),
                    reverse("timetable:setup_wizard", args=[self.school.pk, "uret"])):
            response = self.client.get(url)
            for mode in ("strict", "relaxed"):
                self.assertContains(response, f'name="mode" value="{mode}"')
            self.assertNotContains(response, 'name="mode" value="gen2"')

    def test_gen2_defaults_to_thirty_minutes_in_web_and_services(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        with override_settings(TIMETABLE_JOB_BACKEND="worker"):
            self.client.post(reverse("timetable:generate", args=[self.school.pk]), {"mode": "gen2"})
            queued = services.start_generation(self.school, "varsayılan", mode=Timetable.GEN2)
        self.assertTrue(all(t.time_limit == 1800 for t in self.school.timetables.all()))
        with mock.patch.object(services, "run_generation"):
            sync = services.generate_timetable(self.school, "komut", mode=Timetable.GEN2)
        self.assertEqual(sync.time_limit, 1800)
        self.assertEqual(queued.report["algorithm"], "gen2")

    def test_live_overtime_is_not_marked_stale_and_progress_is_available(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        tt = Timetable.objects.create(school=self.school, name="uzatma", mode=Timetable.STRICT,
                                      status=Timetable.RUNNING, time_limit=1800,
                                      started_at=timezone.now() - timedelta(minutes=33),
                                      report={"algorithm": "gen2", "progress": {"budget_seconds": 2040, "extensions": 4}})
        with mock.patch.object(services.jobs, "is_alive", return_value=True):
            data = self.client.get(reverse("timetable:api_status", args=[tt.pk])).json()
        self.assertEqual(data["status"], Timetable.RUNNING)
        self.assertEqual(data["progress"]["budget_seconds"], 2040)

    def test_stop_saves_best_draft_and_does_not_start_another_search(self):
        draft = cpsat.solve(build_problem(self.school), mode=cpsat.RELAXED, place_all=True, time_limit=2)
        unknown = cpsat.Solution(status="unknown", draft_solution=draft,
                                 stats={"draft_violations": 0, "stopped": True})
        with mock.patch.object(services.cpsat, "solve", return_value=unknown) as solve:
            tt = services.start_generation(self.school, "durdur", mode=Timetable.GEN2, time_limit=5)
        solve.assert_called_once()
        tt.refresh_from_db()
        self.assertEqual(tt.cards.count(), 2)
        self.assertEqual(tt.generation_label, "Gen2")

    def test_expired_gen2_without_draft_does_not_start_diagnosis_search(self):
        with mock.patch.object(services.cpsat, "solve", return_value=cpsat.Solution(status="unknown")) as solve:
            tt = services.start_generation(self.school, "süre bitti", mode=Timetable.GEN2, time_limit=5)
        solve.assert_called_once()
        tt.refresh_from_db()
        self.assertEqual(tt.status, Timetable.FAILED)
