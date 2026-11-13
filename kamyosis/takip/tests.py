from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.models import Birim, Yetki
from personel.models import Bolum, Personel
from program.asc import ice_aktar
from program.models import ProgramSurumu
from program.tests import xml_dosyasi

from . import servis
from .models import DersKaydi, DevirTalebi
from .servis import TakipHatasi


class SahteIstek:
    """servis.yetki() için istek benzeri nesne."""

    def __init__(self, user):
        self.user = user


def yetki(user):
    return servis.yetki(SahteIstek(user))


class TakipTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bil = Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        cls.ayse = Personel.objects.create(ad_soyad="Ayşe Yılmaz", bolum=cls.bil)
        cls.mehmet = Personel.objects.create(ad_soyad="Mehmet Demir", bolum=cls.bil)
        cls.ali = Personel.objects.create(ad_soyad="Ali Kaya", bolum=cls.bil)
        cls.surum, _ = ice_aktar(xml_dosyasi(), surum_adi="Güz")
        bugun = timezone.localdate()
        cls.bu_pazartesi = bugun - timedelta(days=bugun.weekday())
        cls.eski_pazartesi = cls.bu_pazartesi - timedelta(days=14)
        ProgramSurumu.objects.filter(pk=cls.surum.pk).update(
            durum="yayinda", baslangic=cls.bu_pazartesi - timedelta(days=21), yayin_zamani=timezone.now())

        def kullanici(ad, slug=None, seviye=None, kapsam=Yetki.TUM, **ek):
            u = User.objects.create_user(ad, password="x-Parola-123", **ek)
            # Ders Planları yetkisi: ders takibi ve devir talepleri artık ayrı satırlar; eski kullanıcılar üçünü de alır
            for s in ([slug, "ders-takibi", "devir-talepleri"] if slug == "ders-planlari" else [slug] if slug else []):
                Yetki.objects.create(kullanici=u, birim=Birim.objects.get(slug=s), seviye=seviye, kapsam=kapsam)
            return u

        cls.ogretmen = kullanici("ayse", personel=cls.ayse)
        cls.bolumcu = kullanici("bolum", "plan-program", Yetki.DUZENLEME, Yetki.BOLUM, bolum=cls.bil)
        cls.ders_yon = kullanici("dersyon", "ders-planlari", Yetki.YONETIM)
        cls.plan_yon = kullanici("planyon", "plan-program", Yetki.YONETIM)

    def satirlar(self, tarih, **filtre):
        return servis.beklenen_dersler(tarih, tarih, **filtre)

    def test_tarihli_dersler_programdan_uretilir(self):
        self.assertEqual(len(self.satirlar(self.bu_pazartesi)), 4)  # 2 saat × 2 öğretmen
        self.assertEqual(len(self.satirlar(self.bu_pazartesi + timedelta(days=2))), 1)
        self.assertEqual(len(self.satirlar(self.bu_pazartesi + timedelta(days=1))), 0)

    def test_tatil_gunu_ders_yok(self):
        from .models import Tatil
        Tatil.objects.create(tarih=self.bu_pazartesi, aciklama="Bayram")
        self.assertEqual(self.satirlar(self.bu_pazartesi), [])

    def test_gecmis_dersler_kendiliginden_yapildi(self):
        bugun = timezone.localdate()
        self.assertTrue(all(s.durum == "yapildi" for s in self.satirlar(self.eski_pazartesi)))
        self.assertTrue(all(s.durum == "gelecek" for s in self.satirlar(self.bu_pazartesi + timedelta(days=7))))
        self.assertTrue(all(s.durum == "gelecek" for s in servis.beklenen_dersler(bugun, bugun)))
        self.assertFalse(DersKaydi.objects.exists())  # yapıldı bilgisi kayıt gerektirmez

    def test_devir_akisi(self):
        carsamba = self.bu_pazartesi - timedelta(days=5)  # geçen Çarşamba: geçmiş derse de devir açılır
        satir = self.satirlar(carsamba)
        self.assertEqual(satir[0].etkin_personel, self.ali)
        blok = servis.devir_talep_et(self.bolumcu, yetki(self.bolumcu), satir, self.ayse, "Görevlendirme")
        self.assertEqual(self.satirlar(carsamba)[0].durum, "devir")
        with self.assertRaises(TakipHatasi):  # onaysız kesinleşmez
            servis.devir_karar(self.plan_yon, yetki(self.plan_yon), blok, "kesinlestir", "tamam")
        with self.assertRaises(TakipHatasi):  # ders planları yöneticisi kesinleştiremez
            servis.devir_karar(self.ders_yon, yetki(self.ders_yon), blok, "onayla", "")
        servis.devir_karar(self.ders_yon, yetki(self.ders_yon), blok, "onayla", "uygun")
        with self.assertRaises(TakipHatasi):
            servis.devir_karar(self.ders_yon, yetki(self.ders_yon), blok, "kesinlestir", "tamam")
        servis.devir_karar(self.plan_yon, yetki(self.plan_yon), blok, "kesinlestir", "tamam")
        s = self.satirlar(carsamba)[0]
        self.assertEqual((s.etkin_personel, s.asil_personel), (self.ayse, self.ali))
        self.assertEqual(s.durum, "yapildi")

    def test_devirde_cakisma_engellenir(self):
        mehmetin = [s for s in self.satirlar(self.bu_pazartesi) if s.etkin_personel == self.mehmet]
        with self.assertRaisesMessage(TakipHatasi, "o saatte dolu"):
            servis.devir_talep_et(self.bolumcu, yetki(self.bolumcu), mehmetin, self.ayse, "deneme")
        self.assertFalse(DevirTalebi.objects.exists())

    def test_baska_bolumun_kullanicisi_yetkisiz(self):
        diger = Bolum.objects.create(ad="Elektrik", kod="ELK")
        u = User.objects.create_user("elk", password="x-Parola-123", bolum=diger)
        Yetki.objects.create(kullanici=u, birim=Birim.objects.get(slug="plan-program"), seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        carsamba = self.bu_pazartesi - timedelta(days=5)
        with self.assertRaisesMessage(TakipHatasi, "talep yetkiniz yok"):
            servis.devir_talep_et(u, yetki(u), self.satirlar(carsamba), self.ayse, "x")

    def test_devirli_gunun_programi_degistirilemez(self):
        gelecek = self.bu_pazartesi + timedelta(days=9)  # gelecek haftanın Çarşambası
        servis.devir_talep_et(self.bolumcu, yetki(self.bolumcu), self.satirlar(gelecek), self.ayse, "Görevlendirme")
        yeni, _ = ice_aktar(xml_dosyasi(), surum_adi="Yeni")
        su = User.objects.create_superuser("su", password="x-Parola-123")
        self.client.force_login(su)
        r = self.client.post(reverse("program:surum", args=[yeni.pk]), {"islem": "yayinla", "baslangic": (self.bu_pazartesi + timedelta(days=7)).isoformat()})
        self.assertContains(r, "devir")
        yeni.refresh_from_db()
        self.assertEqual(yeni.durum, ProgramSurumu.TASLAK)

    def test_rapor_devri_devralana_yazar(self):
        carsamba = self.bu_pazartesi - timedelta(days=5)
        blok = servis.devir_talep_et(self.bolumcu, yetki(self.bolumcu), self.satirlar(carsamba), self.ayse, "Görevlendirme")
        servis.devir_karar(self.ders_yon, yetki(self.ders_yon), blok, "onayla", "uygun")
        servis.devir_karar(self.plan_yon, yetki(self.plan_yon), blok, "kesinlestir", "tamam")
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("takip:rapor"), {"bas": carsamba.isoformat(), "bit": carsamba.isoformat()})
        satirlar = {k["ad"]: k for k in r.context["liste"]}
        self.assertEqual((satirlar["Ayşe Yılmaz"]["yapilan"], satirlar["Ayşe Yılmaz"]["devralinan"]), (1, 1))
        self.assertEqual((satirlar["Ali Kaya"]["yapilan"], satirlar["Ali Kaya"]["devredilen"]), (0, 1))

    def test_ekranlar(self):
        self.client.force_login(self.bolumcu)
        for ad in ("takip:gunluk", "takip:devirler", "takip:rapor"):
            self.assertEqual(self.client.get(reverse(ad)).status_code, 200, ad)
        r = self.client.get(reverse("takip:gunluk"), {"tarih": self.eski_pazartesi.isoformat()})
        self.assertContains(r, "BİL103")
        self.assertContains(r, "Yapıldı")
        self.assertNotContains(r, "Beyan")
        carsamba = self.bu_pazartesi - timedelta(days=5)
        r = self.client.get(reverse("takip:devir_yeni"), {"d": [s.anahtar for s in self.satirlar(carsamba)]})
        self.assertEqual(r.status_code, 200)
        # personel bağlı ama birim yetkisi olmayan öğretmen kendi sayfasına yönlenir
        self.client.force_login(self.ogretmen)
        self.assertRedirects(self.client.get(reverse("takip:gunluk")), reverse("takip:derslerim"))
        self.assertContains(self.client.get(reverse("takip:derslerim"), {"tarih": self.bu_pazartesi.isoformat()}), "BİL103")

    def test_ana_sayfa_gorevleri(self):
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("core:panel"))
        self.assertContains(r, "Yapılan ders")
        self.assertNotContains(r, "Beyan")
        self.assertContains(r, "Bilgisayar Teknolojisi bölümü")
        carsamba = self.bu_pazartesi - timedelta(days=5)
        servis.devir_talep_et(self.bolumcu, yetki(self.bolumcu), self.satirlar(carsamba), self.ayse, "Görevlendirme")
        self.assertContains(self.client.get(reverse("core:panel")), "Sonuç bekleyen devir talebiniz")
        self.client.force_login(self.ders_yon)
        self.assertContains(self.client.get(reverse("core:panel")), "Onayınızı bekleyen devir")


class AyriYetkiTestleri(TestCase):
    """Ders takibi ve devir talepleri, Ders Planları'ndan ayrı yetki satırları (09.11.2026)."""

    def test_yalniz_ders_planlari_haftalik_programi_acar(self):
        u = User.objects.create_user("sadece_program", password="x-Parola-123")
        Yetki.objects.create(kullanici=u, birim=Birim.objects.get(slug="ders-planlari"), seviye=Yetki.GORUNTULEME,
                             kapsam=Yetki.TUM)
        self.client.force_login(u)
        r = self.client.get(reverse("core:panel"))
        self.assertContains(r, reverse("program:ana"))  # Ders Planları (haftalık program oradan açılır)
        self.assertIn(self.client.get(reverse("program:tablo")).status_code, (200, 302))  # program yoksa Ders Planları'na
        self.assertNotContains(r, reverse("takip:gunluk"))
        self.assertNotContains(r, reverse("takip:devirler"))
        self.assertEqual(self.client.get(reverse("takip:gunluk")).status_code, 403)
        self.assertEqual(self.client.get(reverse("takip:devirler")).status_code, 403)

    def test_devir_yetkisi_takipten_bagimsiz(self):
        u = User.objects.create_user("devirci", password="x-Parola-123")
        Yetki.objects.create(kullanici=u, birim=Birim.objects.get(slug="devir-talepleri"), seviye=Yetki.GORUNTULEME,
                             kapsam=Yetki.TUM)
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("takip:devirler")).status_code, 200)
        self.assertEqual(self.client.get(reverse("takip:gunluk")).status_code, 403)
