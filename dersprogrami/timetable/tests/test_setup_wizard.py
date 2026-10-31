"""Kurulum sihirbazı: sıfırdan bir programı adım adım verilerle doldurup üretime hazırlar."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.models import Institution, Lesson, School


class SetupWizardTests(TestCase):
    def setUp(self):
        self.institution = Institution.objects.create(name="Kurum")
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def url(self, step):
        return reverse("timetable:setup_wizard", args=[self.school.pk, step])

    def paste(self, step, text):
        return self.client.post(self.url(step), {"action": "paste", "text": text}, follow=True)

    def test_from_zero_to_generation(self):
        response = self.client.post(reverse("timetable:program_new", args=[self.institution.pk]), {"name": "Güz"})
        self.school = School.objects.get(name="Güz")
        self.assertRedirects(response, reverse("timetable:setup_wizard_start", args=[self.school.pk]))
        self.assertContains(self.client.get(response.url), "Adım adım kur")
        # saatler: 6 ders, 3. dersten sonra öğle
        self.client.post(self.url("saatler"), {"count": "6", "start": "09:00", "length": "45", "break": "15", "lunch_after": "3", "lunch": "60"})
        periods = list(self.school.periods.all())
        self.assertEqual(len(periods), 6)
        self.assertEqual((periods[3].start_time.strftime("%H:%M"), periods[2].long_break_after), ("12:45", True))
        self.paste("ders-adlari", "Ad\tKod (kısa ad)\nMatematik\tMAT101\nFizik\tFİZ101\nFizik (U)\tFİZ101")
        self.paste("siniflar", "Bilgisayar 1.KISIM;1BİL;35\nBilgisayar 2.KISIM;2BİL")
        self.paste("ogretmenler", "Ahmet Can Yılmaz\tAYILMAZ\tahmet@x.tr\t20\nAyşe Demir")
        self.assertEqual(self.school.teachers.get(short="AYILMAZ").first_name, "Ahmet Can")
        page = self.paste("dersler", "MAT101\t1BİL, 2BİL\tAYILMAZ\t4\t2+2\nFİZ101\t1BİL\tAyşe Demir\t2\nFİZ101 (U)\t1BİL\tAyşe Demir\t2")
        self.assertContains(page, "3 kayıt eklendi")
        self.assertEqual(sorted(self.school.lessons.values_list("subject__name", flat=True)), ["Fizik", "Fizik (U)", "Matematik"])
        lesson = Lesson.objects.get(school=self.school, subject__short="MAT101")
        self.assertEqual((lesson.classes.count(), lesson.split, lesson.teachers.get().short), (2, "2+2", "AYILMAZ"))
        page = self.client.get(self.url("uret"))
        self.assertContains(page, "Programı üret")
        self.assertContains(page, "<b>8</b> ders saati")

    def test_lesson_errors_keep_text_and_save_nothing(self):
        self.school = School.objects.create(name="X", institution=self.institution)
        self.paste("ders-adlari", "Matematik;MAT")
        page = self.paste("dersler", "MAT;9Z;;2\nMAT;;;3")
        self.assertContains(page, "“9Z” sınıfı bulunamadı")
        self.assertEqual(self.school.lessons.count(), 0)
        self.assertContains(page, "MAT;9Z;;2")  # yazılan metin kaybolmaz
