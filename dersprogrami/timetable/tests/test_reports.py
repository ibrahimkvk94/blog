"""Esnek raporlar: tüm rapor türleri, seçenekler ve kayıtlı şablonlar."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import duty
from timetable.models import DutyPlace, ReportPreset, SchoolClass
from timetable.services import generate_timetable
from timetable.tests.test_operations import build_school


class ReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = build_school()
        cls.timetable = generate_timetable(cls.school, "ilk", time_limit=10)
        DutyPlace.objects.create(school=cls.school, name="Bahçe")
        duty.generate(cls.school, cls.timetable)
        cls.user = User.objects.create_superuser("rapor", password="parola-123456")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("timetable:report_render", args=[self.timetable.pk])

    def get(self, query):
        response = self.client.get(self.url + "?" + query)
        self.assertEqual(response.status_code, 200, query)
        return response

    def test_all_report_types_render(self):
        self.assertContains(self.get("tur=bireysel&varlik=sinif"), "9-A")
        self.assertContains(self.get("tur=bireysel&varlik=ogretmen&gunler=satir&sayfa=4"), "per-4")
        self.assertContains(self.get("tur=carsaf&varlik=ogretmen"), "Öğretmenler")
        self.assertContains(self.get("tur=carsaf_gun&varlik=sinif&gun=2"), "Çarşamba")
        self.assertContains(self.get("tur=yuk"), "Matematik")
        self.assertContains(self.get("tur=sinif_dersleri"), "Türkçe")
        self.assertContains(self.get("tur=bos_derslik"), "Boş derslikler")
        self.assertContains(self.get("tur=bos_ogretmen"), "Boş öğretmenler")
        self.assertContains(self.get("tur=nobet"), "Bahçe")

    def test_selection_content_and_options(self):
        cls = SchoolClass.objects.get(school=self.school, name="9-B")
        page = self.get(f"tur=bireysel&varlik=sinif&secim={cls.pk}&ders_adi=kisa&icerik_set=1&yon=dikey&alt=Okul+M%C3%BCd%C3%BCr%C3%BC")
        html = page.content.decode()
        self.assertIn("<h1>9-B</h1>", html)
        self.assertNotIn("<h1>9-A</h1>", html)
        self.assertIn("portrait", html)
        self.assertIn("Okul Müdürü", html)
        self.assertNotIn("Derslik 9-B</span>", html)  # içerik seçilmedi
        self.assertIn(' bw"', self.get("tur=bireysel&icerik_set=1").content.decode())  # renk işaretsiz → siyah-beyaz

    def test_page_and_presets(self):
        page = self.client.get(reverse("timetable:reports", args=[self.timetable.pk]) + "?tur=carsaf&varlik=ogretmen")
        self.assertContains(page, "report-frame")
        self.client.post(reverse("timetable:reports", args=[self.timetable.pk]), {"name": "Öğretmen çarşafı", "tur": "carsaf", "varlik": "ogretmen", "icerik": ["sinif"]})
        preset = ReportPreset.objects.get(school=self.school)
        self.assertEqual(preset.params["tur"], "carsaf")
        self.assertEqual(preset.params["icerik"], ["sinif"])
        page = self.client.get(reverse("timetable:reports", args=[self.timetable.pk]))
        self.assertContains(page, "Öğretmen çarşafı")
        self.assertContains(page, "tur=carsaf")
        self.client.post(reverse("timetable:reports", args=[self.timetable.pk]), {"action": "delete_preset", "preset": preset.pk})
        self.assertFalse(ReportPreset.objects.exists())
