import datetime
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from bildirim.models import Bildirim
from core.models import Birim, Yetki

from . import servis
from .models import Takvim

D, T = datetime.date, datetime.time


def ornek_excel():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws["A1"] = "KARA ÖRNEK MESLEK YÜKSEKOKULU"
    ws["A2"] = "2026-2027 EĞİTİM VE ÖĞRETİM YILI 1'İNCİ YARIYIL ARA SINAV PLANI"
    ws.append(["SINAV TARİHİ", "SINAV SAATİ", "SINIF", "DERS ADI", "ÖLÇME SİSTEMİ KODLARI", "BÖLÜM/ PROGRAM", "SINAV TÜRÜ"])
    ws.append(["30 Kasım 2026\nPazartesi", "08.45-10.00", 2, "İNGİLİZCE 3", "YDL201", "BİL", "%100 MT"])
    ws.append([None, None, 2, "İNGİLİZCE 3", "YDL201", "ELK", "%100 MT"])
    ws.append([None, "10.30-11.45", 1, "MATEMATİK 1", "TEM101", "BİL", "%100 ÇS"])
    ws.append([datetime.datetime(2026, 12, 1), "14.15-15.30", 2, "HİDROLİK VE PNÖMATİK", "UÇT215", "UÇT", "%40 MT+%60 UYG"])
    ws.append([None, None, 2, "İSTATİSTİK", "İŞL201", "BİL", "%100 MT"])  # BİL 2 aynı oturumda ikinci sınav
    ws.append([None, None, 2, "BİLGİSAYAR AĞLARI", "BİL205", "BİL", "%100 MT"])
    ws.merge_cells("A4:A6")
    ws.merge_cells("B4:B5")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class SinavTakvimiTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.herkes = User.objects.create_user("herkes", password="x-Parola-123")
        cls.yetkili = User.objects.create_user("olcme", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.yetkili, birim=Birim.objects.get(slug="olcme-degerlendirme"),
                             seviye=Yetki.DUZENLEME, kapsam=Yetki.TUM)

    def _yukle(self):
        self.client.force_login(self.yetkili)
        r = self.client.post(reverse("sinavtakvimi:yukle"), {
            "dosya": SimpleUploadedFile("plan.xlsx", ornek_excel())})
        return Takvim.objects.get(), r

    def test_sinav_icrasi_kullanimda_ve_herkese_acik(self):
        b = Birim.objects.get(slug="sinav-icrasi")
        self.assertEqual(b.ust.slug, "olcme-degerlendirme")
        self.client.force_login(self.herkes)
        r = self.client.get(reverse("core:panel"))
        self.assertContains(r, f'href="{reverse("sinavtakvimi:liste")}"')

    def test_excel_okuma(self):
        t, r = self._yukle()
        self.assertRedirects(r, reverse("sinavtakvimi:takvim", args=[t.pk]))
        self.assertIn("ARA SINAV PLANI", t.ad)
        satirlar = list(t.satirlar.all())
        self.assertEqual(len(satirlar), 6)
        self.assertEqual([(s.tarih, s.baslangic, s.bitis) for s in satirlar[:3]], [
            (D(2026, 11, 30), T(8, 45), T(10)), (D(2026, 11, 30), T(8, 45), T(10)), (D(2026, 11, 30), T(10, 30), T(11, 45))])
        self.assertEqual(satirlar[3].tarih, D(2026, 12, 1))
        self.assertEqual(satirlar[3].tur, "%40 MT + %60 UYG")
        self.assertEqual(servis.tur_sinifi(satirlar[3].tur), "uyg")
        self.assertEqual(servis.tur_sinifi("%100 ÇS"), "cs")
        self.assertEqual(len(servis.cakismalar(satirlar)), 1)

    def test_yayin_ve_gorunurluk(self):
        t, _ = self._yukle()
        url = reverse("sinavtakvimi:takvim", args=[t.pk])
        self.client.force_login(self.herkes)
        self.assertEqual(self.client.get(url).status_code, 404)  # önizleme yalnız yetkiliye
        self.assertEqual(self.client.post(reverse("sinavtakvimi:yayin", args=[t.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("sinavtakvimi:yukle")).status_code, 403)

        self.client.force_login(self.yetkili)
        self.client.post(reverse("sinavtakvimi:yayin", args=[t.pk]), {"islem": "yayinla", "bildir": "1"})
        t.refresh_from_db()
        self.assertTrue(t.yayinda)
        self.assertTrue(Bildirim.objects.filter(kullanici=self.herkes, tur="sinav_takvimi").exists())
        self.assertFalse(Bildirim.objects.filter(kullanici=self.yetkili, tur="sinav_takvimi").exists())

        self.client.force_login(self.herkes)
        self.assertRedirects(self.client.get(reverse("sinavtakvimi:liste")), url)  # tek plan → doğrudan açılır
        r = self.client.get(url)
        self.assertContains(r, "İngilizce 3")
        self.assertContains(r, 'data-bolumler=" BİL ELK "')
        self.assertContains(r, "Program tablosu")
        r = self.client.get(reverse("sinavtakvimi:excel", args=[t.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"PK"))

        self.client.force_login(self.yetkili)
        self.client.post(reverse("sinavtakvimi:sil", args=[t.pk]))
        self.assertTrue(Takvim.objects.filter(pk=t.pk).exists())  # yayındaki silinmez

    def test_turkce_baslik(self):
        self.assertEqual(servis.tr_baslik("İNGİLİZCE 3"), "İngilizce 3")
        self.assertEqual(servis.tr_baslik("TAKTİK HAREKÂTIN UNSURLARI VE YÖNETİMİ 3"),
                         "Taktik Harekâtın Unsurları ve Yönetimi 3")
        self.assertEqual(servis.tr_baslik("ISITMA TESİSAT"), "Isıtma Tesisat")


class MalzemeTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        from personel.models import Bolum

        cls.bil, _ = Bolum.objects.get_or_create(kod="BİL", defaults={"ad": "Bilgisayar Teknolojisi"})
        cls.ydl, _ = Bolum.objects.get_or_create(kod="YDL", defaults={"ad": "Yabancı Diller"})
        cls.elk, _ = Bolum.objects.get_or_create(kod="ELK", defaults={"ad": "Elektrik"})
        cls.bil_hesap = User.objects.create_user("bilhesap", password="x-Parola-123", bolum=cls.bil)
        cls.ydl_hesap = User.objects.create_user("ydlhesap", password="x-Parola-123", bolum=cls.ydl)
        cls.herkes = User.objects.create_user("herkes2", password="x-Parola-123")
        cls.t = Takvim.objects.create(ad="Deneme planı", yayinda=True)
        servis.satirlari_yaz(cls.t, [
            {"tarih": D(2026, 11, 30), "baslangic": T(8, 45), "bitis": T(10), "sinif": 2, "ders": "İNGİLİZCE 3",
             "kod": "YDL201", "bolum": b, "tur": "%100 MT"} for b in ("BİL", "ELK")] + [
            {"tarih": D(2026, 11, 30), "baslangic": T(14, 15), "bitis": T(15, 30), "sinif": 2, "ders": "SUNUCU",
             "kod": "BİL221", "bolum": "BİL", "tur": "%100 MT"}])

    def _kaydet(self, **veri):
        return self.client.post(reverse("sinavtakvimi:malzeme_kaydet", args=[self.t.pk]), data=veri,
                                content_type="application/json")

    def test_herkes_gorur_girebilen_bolumdur(self):
        self.client.force_login(self.herkes)
        r = self.client.get(reverse("sinavtakvimi:malzemeler"))
        self.assertContains(r, "Sınav Malzemeleri")
        self.assertContains(r, 'data-girebilir="0"', count=3)
        self.assertEqual(self._kaydet(kod="BİL221", bolum="BİL", secimler=["hesap"]).status_code, 403)

        self.client.force_login(self.bil_hesap)  # program BİL: YDL201/BİL ve BİL221; ELK satırı değil
        r = self.client.get(reverse("sinavtakvimi:malzemeler"))
        self.assertContains(r, 'data-girebilir="1"', count=2)
        self.assertEqual(self._kaydet(kod="YDL201", bolum="ELK", secimler=["hesap"]).status_code, 403)
        j = self._kaydet(kod="BİL221", bolum="BİL", secimler=["hesap", "cizim", "uydurma"]).json()
        self.assertEqual(j["satirlar"][0]["metin"], "Hesap makinesi, Çizim araç gereçleri")

    def test_dersi_veren_bolum_tum_programlara_uygular_ve_yok(self):
        self.client.force_login(self.ydl_hesap)  # YDL201'i veren bölüm: her iki programı da girebilir
        j = self._kaydet(kod="YDL201", bolum="BİL", yok=True, hepsi=True).json()
        self.assertEqual({s["bolum"] for s in j["satirlar"]}, {"BİL", "ELK"})
        self.assertEqual(j["satirlar"][0]["metin"], "Malzeme yok")
        self.assertEqual(self.t.malzemeler.count(), 2)
        self._kaydet(kod="YDL201", bolum="ELK")  # hepsi boş → girilmemişe döner
        self.assertEqual(self.t.malzemeler.count(), 1)
        self.client.force_login(self.herkes)
        r = self.client.get(reverse("sinavtakvimi:malzeme_excel", args=[self.t.pk]) + "?program=BİL")
        self.assertTrue(r.content.startswith(b"PK"))
