"""Program versiyonları: otomatik/elle kayıt, ön izleme, geri dönme ve ayrı program olarak açma."""

import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from timetable import editing, versions
from timetable.models import Timetable, TimetableVersion
from timetable.services import generate_timetable
from timetable.tests.test_operations import build_school


class VersionTests(TestCase):
    def setUp(self):
        self.school = build_school()
        self.timetable = generate_timetable(self.school, "ilk", time_limit=10)
        self.user = User.objects.create_superuser("versiyon", password="parola-123456")
        self.client.force_login(self.user)

    def positions(self):
        return {c.id: (c.day, c.period) for c in self.timetable.cards.all()}

    def test_generation_creates_first_version_and_open_autosaves_only_changes(self):
        self.assertEqual(list(self.timetable.versions.values_list("number", "auto")), [(1, True)])
        self.client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk]))
        self.assertEqual(self.timetable.versions.count(), 1)  # değişiklik yok → yeni versiyon yok
        editing.bulk_action(self.timetable, "swap_days", 0, 1)
        self.client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk]))
        latest = versions.latest(self.timetable)
        self.assertEqual(latest.number, 2)
        self.assertEqual(latest.user, self.user)
        self.assertGreater(latest.changes, 0)

    def test_edits_autosave_after_interval(self):
        editing.bulk_action(self.timetable, "swap_days", 0, 1)  # son versiyon yeni: otomatik kayıt yok
        self.assertEqual(self.timetable.versions.count(), 1)
        TimetableVersion.objects.filter(timetable=self.timetable).update(created_at=timezone.now() - timedelta(hours=1))
        before = self.positions()
        editing.bulk_action(self.timetable, "swap_days", 0, 2)
        latest = versions.latest(self.timetable)
        self.assertEqual(latest.number, 2)
        self.assertTrue(latest.auto)
        self.assertEqual({row[0]: (row[1], row[2]) for row in latest.cards}, before)

    def test_manual_save_restore_and_open(self):
        first = versions.latest(self.timetable)
        original = self.positions()
        editing.bulk_action(self.timetable, "swap_days", 0, 4)
        response = self.client.post(reverse("timetable:api_versions", args=[self.timetable.pk]), json.dumps({"note": "Cuma değişti"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        listing = self.client.get(reverse("timetable:api_versions", args=[self.timetable.pk]) + "?oto=0").json()["versions"]
        self.assertEqual([v["note"] for v in listing], ["Cuma değişti"])

        preview = self.client.get(reverse("timetable:api_version", args=[first.pk])).json()
        self.assertEqual(len(preview["rows"]), 2)
        self.assertEqual(sum(1 for c in preview["rows"][0]["cells"] if c), 10)

        editing.bulk_action(self.timetable, "swap_days", 1, 2)  # kaydedilmemiş değişiklik
        response = self.client.post(reverse("timetable:api_version", args=[first.pk]), json.dumps({"action": "restore"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.positions(), original)
        self.assertTrue(self.timetable.versions.filter(note__contains="geri yüklenmeden önce").exists())
        self.timetable.refresh_from_db()
        self.assertIn("geri yüklendi", editing.history_info(self.timetable)["undo"])

        response = self.client.post(reverse("timetable:api_version", args=[first.pk]), json.dumps({"action": "open"}), content_type="application/json")
        copy = Timetable.objects.exclude(pk=self.timetable.pk).get(school=self.school)
        self.assertEqual(response.json()["url"], reverse("timetable:timetable_detail", args=[copy.pk]))
        self.assertEqual(copy.cards.count(), self.timetable.cards.count())
        self.assertEqual(copy.versions.count(), 1)
