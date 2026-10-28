"""Yedekten geri yükleme, başka bilgisayardan yedek yükleme ve otomatik yedek."""

import os
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from timetable import backup
from timetable.models import School, Teacher


class RestoreTests(TransactionTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.override = override_settings(BACKUP_DIR=Path(self.dir.name), BACKUP_KEEP=30)
        self.override.enable()
        self.admin = User.objects.create_superuser("merkez", "a@x.tr", "pw-12345")
        self.school = School.objects.create(name="MYO", days_per_week=5)
        Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya")

    def tearDown(self):
        self.override.disable()
        self.dir.cleanup()

    def test_restore_returns_data_and_keeps_a_safety_copy(self):
        path = backup.create()
        Teacher.objects.create(school=self.school, first_name="Yeni", last_name="Kişi")
        School.objects.create(name="Sonradan eklenen")
        safety = backup.restore(path)
        self.assertEqual(list(Teacher.objects.values_list("first_name", flat=True)), ["Ali"])
        self.assertFalse(School.objects.filter(name="Sonradan eklenen").exists())
        self.assertTrue(User.objects.filter(username="merkez").exists())
        self.assertTrue(safety.exists() and safety != path)

    def test_screen_upload_and_restore_with_confirmation(self):
        self.client.force_login(self.admin)
        url = reverse("timetable:backups")
        bad = SimpleUploadedFile("x.json.gz", b"degil")
        self.client.post(url, {"action": "upload", "dosya": bad})
        self.assertEqual(backup.listing(), [])
        made = backup.create()  # başka bilgisayarda alınmış gibi: dosyayı al, klasörden kaldır
        raw = made.read_bytes()
        made.unlink()
        self.client.post(url, {"action": "upload", "dosya": SimpleUploadedFile("yedek.json.gz", raw)})
        name = backup.listing()[0]["name"]
        Teacher.objects.all().delete()
        response = self.client.post(url, {"action": "restore", "name": name, "onay": "yanlış"})
        self.assertFalse(Teacher.objects.exists())  # onaysız: değişmez
        response = self.client.post(url, {"action": "restore", "name": name, "onay": "GERİ YÜKLE"})
        self.assertTrue(response["Location"].startswith(reverse("timetable:login")))
        self.assertTrue(Teacher.objects.filter(first_name="Ali").exists())


@override_settings(BACKUP_KEEP=30)
class AutoBackupTests(TransactionTestCase):
    def test_ensure_recent(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(BACKUP_DIR=Path(tmp)):
            self.assertIsNotNone(backup.ensure_recent(24))  # hiç yedek yok: alınır
            self.assertIsNone(backup.ensure_recent(24))     # yeni yedek var: alınmaz
            old = backup.directory() / backup.listing()[0]["name"]
            os.utime(old, (old.stat().st_atime - 25 * 3600,) * 2)
            self.assertIsNotNone(backup.ensure_recent(24))  # 25 saatlik: yenisi alınır
