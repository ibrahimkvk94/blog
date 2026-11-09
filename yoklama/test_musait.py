import datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.models import Birim, Yetki
from personel.models import Personel, Secenek

from . import musait
from .models import IzinTuru, YoklamaKaydi


def _an(tarih, s, d=0):
    return timezone.make_aware(datetime.datetime.combine(tarih, datetime.time(s, d)))


class MusaitPersonelTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        r = {m: Secenek.objects.create(tur=Secenek.RUTBE, metin=m) for m in ("Alb.", "Asb.Kd.Bçvş.")}
        u = {m: Secenek.objects.create(tur=Secenek.UNVAN, metin=m) for m in ("Öğt.Gör.", "De.Me.")}
        cls.subay = Personel.objects.create(ad_soyad="Ahmet Subay", personel_kodu="1", rutbe=r["Alb."])
        cls.astsubay = Personel.objects.create(ad_soyad="Bekir Astsubay", personel_kodu="2", rutbe=r["Asb.Kd.Bçvş."])
        cls.akademik = Personel.objects.create(ad_soyad="Ceren Akademik", personel_kodu="3", unvan=u["Öğt.Gör."])
        cls.memur = Personel.objects.create(ad_soyad="Deniz Memur", personel_kodu="4", unvan=u["De.Me."])
        Personel.objects.create(ad_soyad="Eski Personel", personel_kodu="5", aktif=False)
        cls.tarih = datetime.date(2026, 11, 13)  # Cuma
        izin = IzinTuru.objects.create(ad="Yıllık izin (deneme)", kisa="Yİ")
        bilgi = IzinTuru.objects.create(ad="Garnizon terk (deneme)", kisa="GT", mevcut_sayilir=True)
        YoklamaKaydi.objects.create(personel=cls.subay, tur=izin, baslangic=_an(cls.tarih, 9), bitis=_an(cls.tarih, 11))
        YoklamaKaydi.objects.create(personel=cls.memur, tur=bilgi, baslangic=_an(cls.tarih, 0),
                                    bitis=_an(cls.tarih + datetime.timedelta(days=1), 0))
        cls.su = User.objects.create_superuser("su", password="x-Parola-123")
        cls.iiy = User.objects.create_user("iiy", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.iiy, birim=Birim.objects.get(slug="musait-personel"),
                             seviye=Yetki.GORUNTULEME, kapsam=Yetki.TUM)
        cls.yok = User.objects.create_user("yok", password="x-Parola-123")

    def _sorgu(self, bas, bit, **ek):
        class R:  # yetki için en küçük istek
            user = self.su
        with mock.patch.object(musait, "_ders_mesguliyetleri",
                               return_value={self.astsubay.pk: ["3. saat (10:00–10:40) MAT101"]}):
            return {k.personel.pk: k for k in musait.sorgula(musait.yetki(R()), self.tarih, bas, bit, sinav=False, **ek)}

    def test_kategoriler(self):
        self.assertEqual([musait.kategori(p) for p in (self.subay, self.astsubay, self.akademik, self.memur)],
                         ["subay", "astsubay", "akademik", "memur"])

    def test_izin_ve_ders_cakismasi(self):
        k = self._sorgu(datetime.time(10), datetime.time(12))
        self.assertNotIn(Personel.objects.get(personel_kodu="5").pk, k)  # aktif olmayan yok
        self.assertFalse(k[self.subay.pk].musait)  # 09–11 izinli
        self.assertEqual(k[self.subay.pk].nedenler[0][0], "izin")
        self.assertFalse(k[self.astsubay.pk].musait)  # dersi var (sahte)
        self.assertTrue(k[self.akademik.pk].musait)
        self.assertTrue(k[self.memur.pk].musait)  # garnizon terk kaydı "mevcut sayılır"
        k = self._sorgu(datetime.time(11), datetime.time(12))
        self.assertTrue(k[self.subay.pk].musait)  # izin 11:00'de bitti

    def test_kategori_suzgeci_ve_ozet(self):
        k = self._sorgu(datetime.time(10), datetime.time(12), kategoriler=["akademik", "memur"])
        self.assertEqual(set(k), {self.akademik.pk, self.memur.pk})
        o = musait.ozet(list(k.values()))
        self.assertEqual((o["toplam"], o["musait"]), (2, 2))

    def test_ust_uste(self):
        t = datetime.time
        self.assertTrue(musait._ust_uste(t(10), t(12), t(11, 40), t(12, 20)))
        self.assertFalse(musait._ust_uste(t(10), t(12), t(12), t(12, 40)))  # 12:00'de başlayan ders değmez

    def test_sayfa_yetki_ve_excel(self):
        url = reverse("yoklama:musait")
        self.client.force_login(self.yok)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.iiy)
        self.assertContains(self.client.get(url), "Müsait personeli bul")
        q = {"tarih": self.tarih.isoformat(), "bas": "10:00", "bit": "12:00", "k": ["akademik", "subay"]}
        r = self.client.get(url, q)
        self.assertContains(r, "Ceren Akademik")
        self.assertContains(r, "Yıllık izin (deneme)")
        self.assertNotContains(r, "Deniz Memur")
        self.assertContains(self.client.get(url, {**q, "bit": "09:00"}), "Bitiş saati başlangıçtan sonra olmalı")
        x = self.client.get(url, {**q, "excel": "1"})
        self.assertEqual(x["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
