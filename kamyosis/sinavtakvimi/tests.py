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
        self.assertContains(r, "Malzeme ve Süre")
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


class SureTestleri(MalzemeTestleri):
    def test_sure_girilir_ve_iki_alan_dolunca_tamam(self):
        self.client.force_login(self.bil_hesap)
        self.assertEqual(self._kaydet(kod="BİL221", bolum="BİL", sure=400).status_code, 400)
        j = self._kaydet(kod="BİL221", bolum="BİL", sure="60").json()
        self.assertEqual(j["satirlar"][0]["sure"], 60)
        satir = next(r for r in servis.malzeme_satirlari(self.t) if r["kod"] == "BİL221")
        self.assertFalse(satir["girildi"])  # malzeme yok
        self.assertEqual(satir["oturum_dk"], 75)
        self._kaydet(kod="BİL221", bolum="BİL", sure="60", secimler=["hesap"])
        satir = next(r for r in servis.malzeme_satirlari(self.t) if r["kod"] == "BİL221")
        self.assertTrue(satir["girildi"])
        r = self.client.get(reverse("sinavtakvimi:malzemeler"))
        self.assertContains(r, 'value="60"')


class MalzemeSifirlamaTestleri(MalzemeTestleri):
    def test_yonetici_kapsamli_sifirlar(self):
        self.client.force_login(self.ydl_hesap)
        self._kaydet(kod="YDL201", bolum="BİL", yok=True, hepsi=True, sure=60)
        self.client.force_login(self.bil_hesap)
        self._kaydet(kod="BİL221", bolum="BİL", secimler=["hesap"], sure=60)
        url = reverse("sinavtakvimi:malzeme_sifirla", args=[self.t.pk])
        self.assertEqual(self.client.post(url, {"kapsam": "tumu"}).status_code, 403)  # bölüm hesabı yönetici değil
        self.assertNotContains(self.client.get(reverse("sinavtakvimi:malzemeler")), 'id="mzSifirla"')
        yon = User.objects.create_user("styon", password="x-Parola-123")
        Yetki.objects.create(kullanici=yon, birim=Birim.objects.get(slug="sinav-icrasi"), seviye=Yetki.YONETIM,
                             kapsam=Yetki.TUM)
        self.client.force_login(yon)
        self.assertContains(self.client.get(reverse("sinavtakvimi:malzemeler")), 'id="mzSifirla"')
        self.client.post(url, {"kapsam": "program", "program": "ELK"})
        self.assertEqual(self.t.malzemeler.count(), 2)
        self.client.post(url, {"kapsam": "ders_bolumu", "ders_bolumu": "BİL"})
        self.assertEqual(list(self.t.malzemeler.values_list("kod", flat=True)), ["YDL201"])
        self.client.post(url, {"kapsam": "kod", "kod": "YDL201"})
        self.assertEqual(self.t.malzemeler.count(), 0)
        self._kaydet(kod="BİL221", bolum="BİL", sure=50)
        self.client.post(url, {"kapsam": "tumu"})
        self.assertEqual(self.t.malzemeler.count(), 0)


class EtutTestleri(MalzemeTestleri):
    def _etut(self, **veri):
        return self.client.post(reverse("sinavtakvimi:etut_kaydet", args=[self.t.pk]), data=veri,
                                content_type="application/json")

    def test_etut_gunu_secim_kopyalama_ve_yetki(self):
        from personel.models import Personel

        a = Personel.objects.create(ad_soyad="Ali KAYA", bolum=self.ydl)
        b = Personel.objects.create(ad_soyad="Deneme KİRAZ", bolum=self.bil)
        pasif = Personel.objects.create(ad_soyad="Eski HOCA", bolum=self.bil, derse_girebilir=False)
        self.client.force_login(self.herkes)
        r = self.client.get(reverse("sinavtakvimi:etutler"))
        self.assertContains(r, "Etüt Görevlendirmeleri")
        self.assertContains(r, 'data-gun="2026-11-29"', count=3)  # 30 Kasım sınavı → 29 Kasım Pazar etüdü
        self.assertEqual(self._etut(kod="BİL221", bolum="BİL", ogretmen1=a.pk).status_code, 403)

        self.client.force_login(self.ydl_hesap)
        self.assertEqual(self._etut(kod="YDL201", bolum="BİL", ogretmen1=pasif.pk).status_code, 400)
        j = self._etut(kod="YDL201", bolum="BİL", ogretmen1=a.pk, ogretmen2=b.pk, hepsi=True).json()
        self.assertEqual({s["bolum"] for s in j["satirlar"]}, {"BİL", "ELK"})  # aynı derse kopyalandı
        self.assertEqual(j["satirlar"][0]["o2"]["id"], b.pk)
        j = self._etut(kod="YDL201", bolum="ELK", ogretmen1=None, ogretmen2=b.pk).json()  # yalnız ikinci → birinci
        self.assertEqual((j["satirlar"][0]["o1"]["id"], j["satirlar"][0]["o2"]), (b.pk, None))
        self._etut(kod="YDL201", bolum="ELK")
        self.assertEqual(self.t.etutler.count(), 1)
        r = self.client.get(reverse("sinavtakvimi:etut_excel", args=[self.t.pk]))
        self.assertTrue(r.content.startswith(b"PK"))


class ResmiExcelTestleri(MalzemeTestleri):
    def test_okulun_liste_bicimi(self):
        from openpyxl import load_workbook

        from personel.models import Personel

        self.t.ad = "2026-2027 1. Yarıyıl Ara Sınav Planı"
        self.t.save()
        self.client.force_login(self.ydl_hesap)
        self._kaydet(kod="YDL201", bolum="BİL", secimler=["hesap", "cizim"], sure=60)
        self._kaydet(kod="YDL201", bolum="ELK", yok=True, sure=45)
        p = Personel.objects.create(ad_soyad="Ali KAYA", bolum=self.ydl)
        self.client.post(reverse("sinavtakvimi:etut_kaydet", args=[self.t.pk]),
                         data={"kod": "YDL201", "bolum": "BİL", "ogretmen1": p.pk}, content_type="application/json")
        ws = load_workbook(io.BytesIO(self.client.get(reverse("sinavtakvimi:malzeme_excel", args=[self.t.pk])).content)).active
        self.assertEqual(ws["A1"].value, "2026-2027 EĞİTİM VE ÖĞRETİM YILI\n1'İNCİ YARIYIL (GÜZ DÖNEMİ) ARA SINAVINDA "
                                         "KULLANILACAK MALZEME LİSTESİ")
        self.assertEqual([c.value for c in ws[2]], ["S.NO", "SINIF", "DERS KODU", "DERS ADI", "SINAVIN YAPILACAĞI PROGRAM",
                                                    "SINAV SÜRESİ (DK)", "KULLANILACAK MALZEME"])
        self.assertEqual([c.value for c in ws[3]], [1, 2, "YDL201", "İNGİLİZCE 3", "BİLGİSAYAR TEKNOLOJİSİ", 60,
                                                    "*Hesap Makinesi ve Çizim Araç Gereçleri"])
        self.assertEqual((ws["F4"].value, ws["G4"].value), (45, "-"))
        self.assertEqual(ws["A1"].font.name, "Times New Roman")
        ws = load_workbook(io.BytesIO(self.client.get(reverse("sinavtakvimi:etut_excel", args=[self.t.pk])).content)).active
        self.assertIn("ARA SINAVI AKŞAM ETÜTLERİNDE GÖREVLİ PERSONEL LİSTESİ", ws["A1"].value)
        self.assertEqual(ws["H2"].value, "ETÜT TARİHİ")
        self.assertEqual(ws["F3"].value, "Ali KAYA")
        self.assertEqual((ws["G3"].value, ws["H3"].value), ("30 Kasım 2026\nPazartesi", "29 Kasım 2026\nPazar"))
        self.assertIn("G3:G5", [str(r) for r in ws.merged_cells.ranges])  # aynı gün birleşik
