from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from personel.models import Bolum, Personel

from .asc import ders_kodu_parcalari, ice_aktar, kisim_bolum_kodu
from .eslestirme import onerisizleri_toplu_ekle
from .models import Kisim, ProgramHucresi, ProgramOgretmeni, ProgramSurumu

ORNEK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<timetable importtype="database" options="export:idprefix:%CHRID">
  <periods><period name="1" short="1" period="1" starttime="8:20" endtime="9:00"/>
           <period name="2" short="2" period="2" starttime="9:10" endtime="9:50"/></periods>
  <subjects>
    <subject id="S1" name="Algoritma" short="BİL103"/>
    <subject id="S2" name="Ağ Sistemleri" short="BİL201"/>
  </subjects>
  <teachers>
    <teacher id="T1" name="Ayşe YILMAZ" short="AY"/>
    <teacher id="T2" name="Mehmet DEMİR" short="MD"/>
    <teacher id="T3" name="Ali Kaya" short="AK"/>
  </teachers>
  <classrooms><classroom id="R1" name="Lab 1" short="Lab 1" capacity="*"/></classrooms>
  <classes>
    <class id="C1" name="1.KISIM" short="1BİL"/>
    <class id="C2" name="2.KISIM" short="2BİL"/>
  </classes>
  <groups>
    <group id="G1" classid="C1" name="Tüm Sınıf" entireclass="1" divisiontag="0"/>
    <group id="G2" classid="C1" name="Grup 1" entireclass="0" divisiontag="1"/>
  </groups>
  <lessons>
    <lesson id="L1" subjectid="S1" classids="C1" groupids="G2" teacherids="T1,T2" periodspercard="2" periodsperweek="2.0"/>
    <lesson id="L2" subjectid="S2" classids="C2" groupids="" teacherids="T3" periodspercard="1" periodsperweek="1.0"/>
  </lessons>
  <cards>
    <card lessonid="L1" period="1" days="10000" weeks="1" terms="1" classroomids="R1"/>
    <card lessonid="L1" period="2" days="10000" weeks="1" terms="1" classroomids="R1"/>
    <card lessonid="L2" period="1" days="00100" weeks="1" terms="1" classroomids=""/>
  </cards>
</timetable>
"""


def xml_dosyasi():
    from io import BytesIO
    return BytesIO(ORNEK_XML.encode("utf-8"))


class AscTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bil = Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        cls.ayse = Personel.objects.create(ad_soyad="Ayşe Yılmaz", personel_kodu="P1", bolum=cls.bil)
        Personel.objects.create(ad_soyad="Mehmet Demirci", personel_kodu="P2", bolum=cls.bil)

    def test_kisim_turu_ve_ek_onekler(self):
        from .asc import _bolum_onekleri, kisim_turu
        self.assertEqual(kisim_turu("Kr.Tm.İşl."), Kisim.KREDI)
        self.assertEqual(kisim_turu("Hazırlık 1"), Kisim.HAZIRLIK)
        self.assertEqual(kisim_turu("1SVN", "1.KISIM"), Kisim.NORMAL)
        # 0005 göçüyle gelen bölüm: TBE ve SBE dersleri Beden Eğitimi ve Spor'a sayılır
        onekler = _bolum_onekleri()
        self.assertEqual(onekler["TBE"].ad, "Beden Eğitimi ve Spor")
        self.assertEqual(onekler["SBE"], onekler["TBE"])
        self.assertEqual(onekler["BİL"], self.bil)

    def test_kod_ayristirma(self):
        self.assertEqual(ders_kodu_parcalari("BİL103"), ("BİL", 1))
        self.assertEqual(ders_kodu_parcalari("UÇT215"), ("UÇT", 2))
        self.assertEqual(kisim_bolum_kodu("13İNŞ"), "İNŞ")

    def test_ice_aktarim(self):
        surum, rapor = ice_aktar(xml_dosyasi(), surum_adi="Deneme")
        self.assertEqual(surum.durum, ProgramSurumu.TASLAK)
        self.assertEqual(surum.hucreler.count(), 3)
        self.assertEqual(ProgramHucresi.objects.get(surum=surum, saat=1, gun=1).derslik.ad, "Lab 1")
        k1 = Kisim.objects.get(kod="1BİL")
        self.assertEqual((k1.bolum, k1.sinif), (self.bil, 1))
        self.assertEqual(Kisim.objects.get(kod="2BİL").sinif, 2)
        # "Ayşe YILMAZ" ↔ "Ayşe Yılmaz": büyük/küçük harf farkına rağmen otomatik eşleşir
        ayse = ProgramOgretmeni.objects.get(asc_id="T1")
        self.assertEqual((ayse.personel, ayse.durum), (self.ayse, ProgramOgretmeni.OTOMATIK))
        self.assertEqual(ayse.tahmini_bolum, self.bil)
        self.assertEqual(rapor.sayilar["Eşleştirme bekleyen öğretmen"], 2)

    def test_tekrar_yukleme_tanimlari_cogaltmaz(self):
        ice_aktar(xml_dosyasi(), surum_adi="1")
        ice_aktar(xml_dosyasi(), surum_adi="2")
        self.assertEqual(ProgramSurumu.objects.count(), 2)
        self.assertEqual(Kisim.objects.count(), 2)
        self.assertEqual(ProgramOgretmeni.objects.count(), 3)

    def test_toplu_ekleme_benzer_olani_bekletir(self):
        ice_aktar(xml_dosyasi(), surum_adi="1")
        bekleyen = list(ProgramOgretmeni.objects.filter(durum=ProgramOgretmeni.BEKLIYOR))
        eklenen, onerili = onerisizleri_toplu_ekle(bekleyen)
        # "Mehmet DEMİR" ~ "Mehmet Demirci" benzer → bekler; "Ali Kaya" yeni eklenir
        self.assertEqual((eklenen, onerili), (1, 1))
        ali = ProgramOgretmeni.objects.get(asc_id="T3")
        self.assertEqual((ali.durum, ali.personel.bolum), (ProgramOgretmeni.YENI, self.bil))

    def test_gecerli_surum_en_son_yayinlanan(self):
        bugun = date.today()
        eski, _ = ice_aktar(xml_dosyasi(), surum_adi="eski")
        yeni, _ = ice_aktar(xml_dosyasi(), surum_adi="yeni")
        from django.utils import timezone
        ProgramSurumu.objects.filter(pk=eski.pk).update(durum="yayinda", baslangic=bugun - timedelta(days=30), yayin_zamani=timezone.now() - timedelta(days=30))
        self.assertEqual(ProgramSurumu.objects.gecerli(), eski)
        ProgramSurumu.objects.filter(pk=yeni.pk).update(durum="yayinda", baslangic=bugun, yayin_zamani=timezone.now())
        self.assertEqual(ProgramSurumu.objects.gecerli(), yeni)
        self.assertEqual(ProgramSurumu.objects.gecerli(bugun - timedelta(days=1)), eski)


class EkranTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        cls.yonetici = User.objects.create_superuser("y", password="x-Parola-123")
        cls.kullanici = User.objects.create_user("k", password="x-Parola-123")
        from core.models import Birim, Yetki
        Yetki.objects.create(kullanici=cls.kullanici, birim=Birim.objects.get(slug="plan-program"), seviye=Yetki.DUZENLEME)

    def test_yukleme_ve_ekranlar(self):
        self.client.force_login(self.yonetici)
        f = xml_dosyasi()
        f.name = "asctt2012.xml"
        r = self.client.post(reverse("program:surumler"), {"ad": "Güz", "dosya": f})
        surum = ProgramSurumu.objects.get()
        self.assertRedirects(r, reverse("program:surum", args=[surum.pk]))
        r = self.client.post(reverse("program:surum", args=[surum.pk]), {"islem": "yayinla", "baslangic": date.today().isoformat()})
        surum.refresh_from_db()
        self.assertEqual(surum.durum, ProgramSurumu.YAYINDA)
        for tur in ("kisim", "ogretmen", "derslik"):
            r = self.client.get(reverse("program:tablo"), {"tur": tur})
            self.assertContains(r, "BİL")
        self.assertContains(self.client.get(reverse("program:ogretmenler")), "Mehmet DEMİR")

    def test_duzenleme_yetkisi_yuklemeyi_goremez(self):
        self.client.force_login(self.kullanici)
        self.assertEqual(self.client.get(reverse("program:ana")).status_code, 200)
        self.assertEqual(self.client.get(reverse("program:surumler")).status_code, 403)
        self.assertEqual(self.client.get(reverse("program:ogretmenler")).status_code, 403)
