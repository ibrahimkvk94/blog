from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Birim, Yetki

from .models import Ogrenci

TC = "12345678950"


class OgrenciSayfalari(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.yonetici = User.objects.create_superuser("y", password="x-Parola-123")
        cls.goruntuleyen = User.objects.create_user("g", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.goruntuleyen, birim=Birim.objects.get(slug="ogrenci-kaydi"),
                             seviye=Yetki.GORUNTULEME)
        cls.o = Ogrenci.objects.create(tc=TC, ad="VELİ", soyad="DENEME", numara="2026001")

    def test_birim_kullanimda(self):
        b = Birim.objects.get(slug="ogrenci-kaydi")
        self.assertEqual((b.durum, b.modul_url), ("kullanimda", "ogrenci:liste"))

    def test_goruntuleyen_tc_goremez_duzenleyemez(self):
        self.client.force_login(self.goruntuleyen)
        r = self.client.get(reverse("ogrenci:liste"))
        self.assertContains(r, "DENEME")
        self.assertNotContains(r, TC)
        self.assertEqual(self.client.get(reverse("ogrenci:duzenle", args=[self.o.pk])).status_code, 403)

    def test_yonetici_ekler_tc_denetlenir(self):
        self.client.force_login(self.yonetici)
        self.assertContains(self.client.get(reverse("ogrenci:liste"), {"q": "deneme"}), TC)
        r = self.client.post(reverse("ogrenci:ekle"), {"tc": "12345678900", "ad": "a", "soyad": "b", "aktif": "on"})
        self.assertContains(r, "geçersiz")
        r = self.client.post(reverse("ogrenci:ekle"), {"tc": TC, "ad": "a", "soyad": "b", "aktif": "on"})
        self.assertContains(r, "başka öğrenci")
        self.client.post(reverse("ogrenci:ekle"), {"tc": "", "ad": "ayşe", "soyad": "kaya", "aktif": "on"})
        self.assertTrue(Ogrenci.objects.filter(ad="AYŞE", soyad="KAYA").exists())
        self.assertEqual(self.client.get(reverse("ogrenci:excel")).status_code, 200)
