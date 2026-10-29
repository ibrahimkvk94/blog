"""Sistem güncelleme sayfası: yalnızca merkez yöneticisi; başlatıcı yoksa yeniden başlatmaz; güncelleme önce yedek alır."""

from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable import updater


@override_settings(AUTO_BACKUP=False)
class SystemUpdateTests(TestCase):
    def setUp(self):
        self.url = reverse("timetable:system_update")
        self.admin = User.objects.create_superuser("admin", "a@x.tr", "pw")

    def test_only_central_admin(self):
        User.objects.create_user("normal", password="pw")
        self.client.login(username="normal", password="pw")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_page_and_status_json(self):
        self.client.force_login(self.admin)
        with mock.patch.object(updater, "supervised", return_value=""):
            page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Sistem güncelleme")
        status = self.client.get(self.url + "?durum=1").json()
        self.assertIn("head", status)

    def test_without_launcher_no_restart(self):
        self.client.force_login(self.admin)
        with mock.patch.object(updater, "supervised", return_value=""), mock.patch.object(updater, "request_restart") as restart:
            response = self.client.post(self.url, {"action": "guncelle"}, follow=True)
        restart.assert_not_called()
        self.assertContains(response, "sayfadan yeniden başlatılamıyor")

    def test_update_takes_backup_then_restarts(self):
        self.client.force_login(self.admin)
        heads = iter([{"hash": "aaa"}, {"hash": "bbb"}])
        with mock.patch.object(updater, "supervised", return_value="yerel"), \
                mock.patch.object(updater, "current", side_effect=lambda: next(heads)), \
                mock.patch.object(updater, "pull", return_value=(True, "ok")) as pull, \
                mock.patch("timetable.backup.create") as create, \
                mock.patch.object(updater, "request_restart") as restart:
            response = self.client.post(self.url, {"action": "guncelle"})
        create.assert_called_once()
        pull.assert_called_once()
        restart.assert_called_once_with("aaa")
        self.assertContains(response, "Yeniden başlatılıyor")

    def test_failed_backup_stops_update(self):
        self.client.force_login(self.admin)
        with mock.patch.object(updater, "supervised", return_value="yerel"), \
                mock.patch("timetable.backup.create", side_effect=OSError("disk dolu")), \
                mock.patch.object(updater, "pull") as pull, mock.patch.object(updater, "request_restart") as restart:
            response = self.client.post(self.url, {"action": "guncelle"}, follow=True)
        pull.assert_not_called()
        restart.assert_not_called()
        self.assertContains(response, "Önce yedek alınamadı")
