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


class KareKodluBilgiFormu(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.goruntuleyen = User.objects.create_user("g", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.goruntuleyen, birim=Birim.objects.get(slug="ogrenci-kaydi"),
                             seviye=Yetki.GORUNTULEME)
        cls.yetkisiz = User.objects.create_user("z", password="x-Parola-123")

    def test_form_giris_gerektirmez_ve_veri_gondermez(self):
        r = self.client.get(reverse("ogrenci:bilgi_formu"))
        self.assertEqual(r.status_code, 200)
        for metin in ("Kişisel bilgiler", "Aile bilgileri", "İletişim", "ÖSYM ve lise", 'const BASLIK = "5201"'):
            self.assertContains(r, metin)
        icerik = r.content.decode()
        self.assertNotIn('method="post"', icerik.lower())
        self.assertNotIn("fetch(", icerik)
        self.assertNotIn("XMLHttpRequest", icerik)

    def test_personel_sayfasi_yetki_ister(self):
        url = reverse("ogrenci:karekod")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.yetkisiz)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("ogrenci:okuyucu")).status_code, 403)

    def test_personel_sayfasi_baglanti_ve_kare_kod(self):
        self.client.force_login(self.goruntuleyen)
        with self.settings(DIS_ADRESLER=["https://okul.example.ts.net"]):
            r = self.client.get(reverse("ogrenci:karekod"))
        self.assertContains(r, "https://okul.example.ts.net/ogrenci/bilgi-formu/")
        self.assertContains(r, "<svg")
        self.assertContains(self.client.get(reverse("ogrenci:liste")), reverse("ogrenci:karekod"))

    def test_okuyucu_indirilir(self):
        from . import views

        self.client.force_login(self.goruntuleyen)
        r = self.client.get(reverse("ogrenci:okuyucu"))
        if views.OKUYUCU.exists():
            self.assertEqual(r.status_code, 200)
            self.assertIn("Ogrenci_KareKod_Okuyucu.xlsm", r["Content-Disposition"])
            r.close()
        else:
            self.assertEqual(r.status_code, 404)
