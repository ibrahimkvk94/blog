import datetime
import io
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.models import User
from core.models import Birim, Yetki
from ogrenci.models import Ogrenci
from personel.models import KartAlani, KartDegeri, Personel

from . import aktarim, excel, okuma
from .models import KimlikKaydi
from .okuma import Parca, kontrol_hanesi, tc_gecerli


def tc_uret(ilk9):
    d = [int(c) for c in ilk9]
    d10 = (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10
    return ilk9 + str(d10) + str((sum(d) + d10) % 10)


TC = tc_uret("123456789")
TC2 = tc_uret("234567891")
TC3 = tc_uret("345678912")


def mrz(tc=TC, belge="A12B34567", dogum="900215", son="320101", cins="M", isim="CAGLAR<<SUKRU<ALI"):
    s1 = "I<TUR" + belge + kontrol_hanesi(belge) + tc + "<<<<"
    s2 = dogum + kontrol_hanesi(dogum) + cins + son + kontrol_hanesi(son) + "TUR" + "<" * 11
    s2 += kontrol_hanesi(s1[5:30] + s2[0:7] + s2[8:15] + s2[18:29])
    return [s1, s2, (isim + "<" * 30)[:30]]


ON = [
    Parca("TÜRKİYE CUMHURİYETİ KİMLİK KARTI", 100, 20, 900, 50),
    Parca("T.C. Kimlik No / TR Identity No", 300, 80, 600, 95), Parca(TC, 300, 100, 520, 130),
    Parca("Soyadı / Surname", 300, 150, 500, 165), Parca("ÇAĞLAR", 300, 170, 450, 200),
    Parca("Adı / Given Name(s)", 300, 215, 520, 230), Parca("ŞÜKRÜ ALİ", 300, 235, 480, 265),
    Parca("Doğum Tarihi / Date of Birth", 300, 280, 560, 295), Parca("15.02.1990", 300, 300, 450, 330),
    Parca("Cinsiyeti / Gender", 600, 280, 760, 295), Parca("E/M", 600, 300, 660, 330),
    Parca("Seri No / Document No", 300, 345, 520, 360), Parca("A12B34567", 300, 365, 480, 395),
    Parca("Son Geçerlilik / Valid Until", 600, 345, 860, 360), Parca("01.01.2032", 600, 365, 760, 395),
    Parca("Uyruğu / Nationality", 300, 410, 500, 425), Parca("T.C./TUR", 300, 430, 420, 460),
]
ARKA = [
    Parca("Anne Adı / Mother's Name", 100, 50, 400, 65), Parca("AYŞE", 100, 70, 200, 100),
    Parca("Baba Adı / Father's Name", 100, 115, 400, 130), Parca("HASAN", 100, 135, 250, 165),
    Parca("Veren Makam / Issued By", 100, 180, 400, 195), Parca("T.C. İÇİŞLERİ BAKANLIĞI", 100, 200, 500, 230),
]


class OkumaKurallari(SimpleTestCase):
    def test_tc_algoritmasi(self):
        self.assertTrue(tc_gecerli(TC))
        self.assertFalse(tc_gecerli(TC[:-1] + str((int(TC[-1]) + 1) % 10)))
        self.assertFalse(tc_gecerli("0" + TC[1:]))
        self.assertFalse(tc_gecerli("123"))

    def test_icao_ornegi(self):
        m = okuma.mrz_coz(["I<UTOD231458907<<<<<<<<<<<<<<<", "7408122F1204159UTO<<<<<<<<<<<6",
                           "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"])
        self.assertEqual(m.belge_no, "D23145890")
        self.assertTrue(m.belge_dogru and m.dogum_dogru and m.son_dogru and m.bilesik_dogru)
        self.assertEqual(m.dogum_tarihi, datetime.date(1974, 8, 12))
        self.assertEqual((m.soyad, m.ad, m.cinsiyet), ("ERIKSSON", "ANNA MARIA", "K"))

    def test_mrz_okuma_hatalari_duzeltilir(self):
        s1, s2, s3 = mrz()
        bozuk = [s1.replace("1234", "I234"), s2.replace("9002", "9OO2"), s3.replace("<", "«", 2)]
        m = okuma.mrz_coz(okuma.mrz_bul(["gürültü", "IDENTITY CARD"] + bozuk + ["son"]))
        self.assertEqual(m.tc, TC)
        self.assertEqual(m.dogum_tarihi, datetime.date(1990, 2, 15))
        self.assertTrue(m.dogum_dogru and m.belge_dogru and m.bilesik_dogru)

    def test_iki_yuz_birlesir_turkce_harfler_on_yuzden(self):
        s = okuma.birlestir(ON, ARKA, mrz())
        b = s.bilgiler
        self.assertEqual(b["tc"], TC)
        self.assertEqual((b["soyad"], b["ad"]), ("ÇAĞLAR", "ŞÜKRÜ ALİ"))
        self.assertEqual(b["dogum_tarihi"], datetime.date(1990, 2, 15))
        self.assertEqual(b["son_gecerlilik"], datetime.date(2032, 1, 1))
        self.assertEqual((b["cinsiyet"], b["seri_no"], b["uyruk"]), ("E", "A12B34567", "T.C."))
        self.assertEqual((b["anne_adi"], b["baba_adi"]), ("AYŞE", "HASAN"))
        self.assertEqual(b["veren_makam"], "T.C. İÇİŞLERİ BAKANLIĞI")
        self.assertEqual(s.uyarilar, [])
        self.assertEqual(s.supheli, set())

    def test_on_yuz_ile_kod_satiri_uyusmazsa_uyarir(self):
        on = [p if p.metin != "ÇAĞLAR" else Parca("CAGLAN", p.sol, p.ust, p.sag, p.alt) for p in ON]
        s = okuma.birlestir(on, ARKA, mrz())
        self.assertIn("soyad", s.supheli)
        self.assertEqual(s.bilgiler["soyad"], "CAGLAN")

    def test_yalniz_arka_yuz_ad_kod_satirindan(self):
        s = okuma.birlestir([], ARKA, mrz())
        self.assertEqual((s.bilgiler["ad"], s.bilgiler["soyad"]), ("SUKRU ALI", "CAGLAR"))
        self.assertTrue({"ad", "soyad"} <= s.supheli)
        self.assertEqual(s.bilgiler["tc"], TC)

    def test_yalniz_on_yuz(self):
        s = okuma.birlestir(ON, [], [])
        self.assertEqual(s.bilgiler["tc"], TC)
        self.assertEqual(s.bilgiler["seri_no"], "A12B34567")
        self.assertEqual(s.bilgiler["anne_adi"], "")

    def test_birden_cok_okumadan_kontrol_hanesi_tutan_secilir(self):
        s1, s2, s3 = mrz()
        okumalar = [s1[:20] + s1[21:], "2" + s2[1:], s2[:20] + s2[22:], s3.replace("<ALI", "KALI"), s1, s3]
        m = okuma.mrz_coz(okuma.mrz_bul(okumalar))
        self.assertTrue(m.belge_dogru and m.dogum_dogru and m.son_dogru and m.bilesik_dogru)
        self.assertEqual((m.tc, m.ad), (TC, "SUKRU ALI"))

    def test_deger_alttaki_etiketi_gecmez(self):
        arka = [p for p in ARKA if p.metin != "AYŞE"]  # anne adı okunamamış
        self.assertNotIn("anne_adi", okuma.arka_yuz(arka))
        self.assertEqual(okuma.arka_yuz(arka)["baba_adi"], "HASAN")

    def test_bolge_okumasi_kod_satiriyla_tutani_secer(self):
        s = okuma.birlestir(ON, ARKA, mrz(), {"ad": "ŞUKRU A RİNNİ", "anne_adi": "AYŞE NUR"})
        self.assertEqual(s.bilgiler["ad"], "ŞÜKRÜ ALİ")
        self.assertEqual(s.bilgiler["anne_adi"], "AYŞE NUR")

    def test_ad_bicimi(self):
        k = KimlikKaydi(ad="ŞÜKRÜ ALİ", soyad="IŞIK")
        self.assertEqual(k.ad_soyad, "Şükrü Ali IŞIK")


def kayit(**ek):
    d = dict(tc=TC, soyad="KAYA", ad="ALİ", dogum_tarihi=datetime.date(1990, 2, 15), cinsiyet="E", seri_no="A12B34567",
             uyruk="T.C.", son_gecerlilik=datetime.date(2032, 1, 1), anne_adi="AYŞE", baba_adi="HASAN",
             veren_makam="T.C. İÇİŞLERİ BAKANLIĞI")
    d.update(ek)
    return KimlikKaydi.objects.create(**d)


class ExcelTestleri(TestCase):
    def test_gidis_donus(self):
        k1, k2 = kayit(), kayit(tc=TC2, ad="AYŞE", soyad="KİRAZ", cinsiyet="K")
        wb = load_workbook(io.BytesIO(excel.yaz([k1, k2])))
        ws = wb.active
        self.assertEqual(ws["C2"].value, TC)
        self.assertEqual(ws["C2"].number_format, "@")
        ws["B2"], ws["B3"] = "Personel", "Öğrenci"
        ws["E3"] = "AYŞE NUR"
        ws.append([None, "öğrenci", TC3, "DENEME", "VELİ", "01.03.2001", "Erkek"])
        tampon = io.BytesIO()
        wb.save(tampon)
        tampon.seek(0)
        self.assertEqual(excel.ice_aktar(tampon, None), (2, 1))
        k1.refresh_from_db()
        k2.refresh_from_db()
        self.assertEqual((k1.tur, k2.tur, k2.ad), ("personel", "ogrenci", "AYŞE NUR"))
        yeni = KimlikKaydi.objects.get(tc=TC3)
        self.assertEqual((yeni.tur, yeni.dogum_tarihi, yeni.cinsiyet, yeni.kaynak),
                         ("ogrenci", datetime.date(2001, 3, 1), "E", "excel"))

    def test_hatali_tarih(self):
        wb = load_workbook(io.BytesIO(excel.yaz([])))
        wb.active.append([None, "Personel", TC, "KAYA", "ALİ", "31.02.1990"])
        tampon = io.BytesIO()
        wb.save(tampon)
        tampon.seek(0)
        with self.assertRaises(excel.ExcelHatasi):
            excel.ice_aktar(tampon, None)

    def test_excel_olmayan_dosya(self):
        with self.assertRaises(excel.ExcelHatasi):
            excel.ice_aktar(io.BytesIO(b"duz metin"), None)


class AktarimTestleri(TestCase):
    def test_personel_tc_ile_guncellenir_kimlik_alanlari_yazilir(self):
        p = Personel.objects.create(ad_soyad="Ali KAYA", personel_kodu=TC)
        k = kayit(tur="personel")
        planlar = aktarim.planla([k], personel_yetkisi=True)
        self.assertEqual((planlar[0].islem, planlar[0].hedef), (aktarim.GUNCELLE, p))
        aktarim.uygula(planlar)
        degerler = {d.alan.ad: d.deger for d in KartDegeri.objects.filter(personel=p)}
        self.assertEqual(degerler["Doğum tarihi"], "1990-02-15")
        self.assertEqual(degerler["Cinsiyet"], "Erkek")
        self.assertEqual(degerler["Anne adı"], "AYŞE")
        self.assertEqual(KartAlani.objects.get(ad="Kimlik seri no").grup, "Kimlik")
        k.refresh_from_db()
        self.assertIsNotNone(k.aktarim)
        self.assertEqual(aktarim.planla([k], personel_yetkisi=True)[0].islem, aktarim.ATLA)

    def test_personel_ad_ile_eslesir_tc_yazilir(self):
        p = Personel.objects.create(ad_soyad="Ali KAYA")
        aktarim.uygula(aktarim.planla([kayit(tur="personel")], personel_yetkisi=True))
        p.refresh_from_db()
        self.assertEqual(p.personel_kodu, TC)
        self.assertEqual(Personel.objects.count(), 1)

    def test_ayni_adda_iki_personel_atlanir(self):
        Personel.objects.create(ad_soyad="Ali KAYA")
        Personel.objects.create(ad_soyad="ALİ KAYA", personel_kodu=None, sicil="2")
        self.assertEqual(aktarim.planla([kayit(tur="personel")], personel_yetkisi=True)[0].islem, aktarim.ATLA)

    def test_yeni_personel_ve_ogrenci(self):
        planlar = aktarim.planla([kayit(tur="personel"), kayit(tur="ogrenci", tc=TC2, ad="VELİ", soyad="DENEME")],
                                 personel_yetkisi=True, ogrenci_yetkisi=True)
        self.assertEqual([p.islem for p in planlar], [aktarim.YENI, aktarim.YENI])
        self.assertEqual(aktarim.uygula(planlar), {"personel": 1, "ogrenci": 1, "yeni": 2})
        self.assertEqual(Personel.objects.get(personel_kodu=TC).ad_soyad, "Ali KAYA")
        o = Ogrenci.objects.get(tc=TC2)
        self.assertEqual((o.ad, o.soyad, o.anne_adi), ("VELİ", "DENEME", "AYŞE"))

    def test_ogrenci_guncellenir(self):
        o = Ogrenci.objects.create(tc=TC, ad="ALI", soyad="KAYA", numara="2026001")
        aktarim.uygula(aktarim.planla([kayit(tur="ogrenci")], ogrenci_yetkisi=True))
        o.refresh_from_db()
        self.assertEqual((o.ad, o.numara, o.seri_no), ("ALİ", "2026001", "A12B34567"))

    def test_atlanan_satirlar(self):
        planlar = aktarim.planla([
            kayit(),  # türsüz
            kayit(tur="personel", tc="12345678900"),  # geçersiz T.C.
            kayit(tur="personel", ad=""),
            kayit(tur="ogrenci"),  # yetki yok
        ], personel_yetkisi=True)
        self.assertTrue(all(p.islem == aktarim.ATLA for p in planlar))
        self.assertTrue(all(p.notlar for p in planlar))


class SayfaTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.yonetici = User.objects.create_superuser("y", password="x-Parola-123")
        cls.okuyucu = User.objects.create_user("o", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.okuyucu, birim=Birim.objects.get(slug="kimlik-okuma"),
                             seviye=Yetki.DUZENLEME)

    def test_yetkisiz_giremez(self):
        self.client.force_login(User.objects.create_user("x", password="x-Parola-123"))
        self.assertEqual(self.client.get(reverse("kimlik:liste")).status_code, 403)

    def test_kart_oku_kontrol_sayfasina_gider(self):
        self.client.force_login(self.okuyucu)
        sahte = okuma.birlestir(ON, ARKA, mrz())
        with mock.patch("kimlik.motor.oku", return_value=sahte):
            r = self.client.post(reverse("kimlik:oku"), {"on": io.BytesIO(b"x"), "tur": "personel"})
        k = KimlikKaydi.objects.get()
        self.assertRedirects(r, reverse("kimlik:duzenle", args=[k.pk]) + "?yeni=1")
        self.assertEqual((k.tc, k.soyad, k.tur), (TC, "ÇAĞLAR", "personel"))
        r = self.client.get(reverse("kimlik:duzenle", args=[k.pk]) + "?yeni=1")
        self.assertContains(r, "ŞÜKRÜ ALİ")

    def test_motor_yoksa_hata_mesaji(self):
        self.client.force_login(self.okuyucu)
        with mock.patch("kimlik.motor.oku", side_effect=__import__("kimlik.motor").motor.MotorYok("yok")):
            r = self.client.post(reverse("kimlik:oku"), {"on": io.BytesIO(b"x")}, follow=True)
        self.assertContains(r, "yok")
        self.assertFalse(KimlikKaydi.objects.exists())

    def test_liste_excel_ve_duzelt(self):
        self.client.force_login(self.okuyucu)
        k = kayit()
        with mock.patch("kimlik.motor.durum", return_value=(True, "hazır")):
            self.assertContains(self.client.get(reverse("kimlik:liste")), "Ali KAYA")
        r = self.client.get(reverse("kimlik:excel"))
        self.assertEqual(r.status_code, 200)
        veri = {f: getattr(k, f) or "" for f in ("tc", "soyad", "ad", "seri_no", "uyruk", "anne_adi", "baba_adi",
                                                  "veren_makam", "cinsiyet")}
        veri.update(ad="veli", tur="ogrenci", dogum_tarihi="1990-02-15", son_gecerlilik="2032-01-01")
        self.client.post(reverse("kimlik:duzenle", args=[k.pk]), veri)
        k.refresh_from_db()
        self.assertEqual((k.ad, k.tur), ("VELİ", "ogrenci"))

    def test_aktarim_yetkisi_olmadan_atlanir_yonetici_aktarir(self):
        k = kayit(tur="personel")
        self.client.force_login(self.okuyucu)
        self.client.post(reverse("kimlik:aktar"), {"k": [k.pk]})
        self.assertFalse(Personel.objects.exists())
        self.client.force_login(self.yonetici)
        r = self.client.get(reverse("kimlik:aktar"))
        self.assertContains(r, "Yeni kayıt")
        self.client.post(reverse("kimlik:aktar"), {"k": [k.pk]})
        self.assertTrue(Personel.objects.filter(personel_kodu=TC).exists())

    def test_toplu_tur_ve_sil(self):
        self.client.force_login(self.okuyucu)
        k1, k2 = kayit(), kayit(tc=TC2)
        self.client.post(reverse("kimlik:toplu"), {"k": [k1.pk, k2.pk], "islem": "ogrenci"})
        self.assertEqual(KimlikKaydi.objects.filter(tur="ogrenci").count(), 2)
        self.client.post(reverse("kimlik:toplu"), {"k": [k1.pk], "islem": "sil"})
        self.assertEqual(KimlikKaydi.objects.count(), 1)
