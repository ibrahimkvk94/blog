"""Kurumsal basılı çıktı: logo, başlık, dönem, imza alanları ve sayfa altı."""

import datetime

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from timetable.models import Card, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


class PrintSettingsTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        Period.objects.create(school=self.school, index=0, name="1", start_time=datetime.time(8), end_time=datetime.time(8, 40))
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Fizik"), periods_per_week=1)
        lesson.classes.add(SchoolClass.objects.create(school=self.school, name="1A"))
        lesson.teachers.add(Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya"))
        self.tt = Timetable.objects.create(school=self.school, name="Güz", status=Timetable.OK)
        Card.objects.create(timetable=self.tt, lesson=lesson, length=1, day=0, period=0)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:print_settings", args=[self.school.pk])

    def test_settings_appear_on_printouts(self):
        version = School.objects.get(pk=self.school.pk).data_version
        response = self.client.post(self.url, {
            "title": "T.C.\nÖRNEK ÜNİVERSİTESİ", "term": "2026-2027 Güz Yarıyılı", "footer": "Kurul kararıyla yürürlüktedir.",
            "role-0": "Müdür", "name-0": "Ayşe Yılmaz", "sign_pages": "1", "show_date": "1",
            "logo": SimpleUploadedFile("logo.png", PNG, content_type="image/png"),
        })
        self.assertRedirects(response, self.url)
        school = School.objects.get(pk=self.school.pk)
        self.assertTrue(school.print_settings["logo"].startswith("data:image/png;base64,"))
        self.assertEqual(school.data_version, version)  # çözücü önbelleği bozulmaz
        page = self.client.get(reverse("timetable:print", args=[self.tt.pk]) + "?tur=sinif")
        for text in ("ÖRNEK ÜNİVERSİTESİ", "2026-2027 Güz Yarıyılı", "Ayşe Yılmaz", "Kurul kararıyla yürürlüktedir.", 'class="pb-logo"'):
            self.assertContains(page, text)
        self.assertContains(self.client.get(reverse("timetable:duties_print", args=[self.school.pk])), "Ayşe Yılmaz")
        # imzasız ve logosuz
        self.client.post(self.url, {"title": "", "logo_clear": "1"})
        page = self.client.get(reverse("timetable:print", args=[self.tt.pk]) + "?tur=sinif")
        self.assertNotContains(page, 'class="pb-logo"')
        self.assertNotContains(page, 'class="pb-sign"')

    def test_rejects_large_or_wrong_logo(self):
        self.client.post(self.url, {"logo": SimpleUploadedFile("x.txt", b"merhaba", content_type="text/plain")})
        self.assertEqual(School.objects.get(pk=self.school.pk).print_settings.get("logo"), "")
