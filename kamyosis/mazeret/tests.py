import datetime
import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Birim, Yetki
from personel.models import Bolum, Personel
from sinav.models import ExamPeriod
from timetable.models import Availability, Period, School, Teacher

from . import servis
from .models import DersMazeretBildirimi, DersMazeretDonemi, DersMazeretGecmisi, SinavMazeretDonemi
from .servis import MazeretHatasi


class SahteIstek:
    def __init__(self, user):
        self.user = user


def yetki(user):
    return servis.yetki(SahteIstek(user))


class DersMazeretiTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bil = Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        cls.elk = Bolum.objects.create(ad="Elektrik", kod="ELK")
        cls.ayse = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=cls.bil)
        cls.ali = Personel.objects.create(ad_soyad="Ali KAYA", bolum=cls.bil)
        cls.veli = Personel.objects.create(ad_soyad="Veli ÇELİK", bolum=cls.elk)
        plan = Birim.objects.get(slug="plan-program")

        def kullanici(ad, seviye=None, kapsam=Yetki.TUM, **ek):
            u = User.objects.create_user(ad, password="x-Parola-123", **ek)
            if seviye:
                Yetki.objects.create(kullanici=u, birim=plan, seviye=seviye, kapsam=kapsam)
            return u

        cls.bilci = kullanici("bil", Yetki.DUZENLEME, Yetki.BOLUM, bolum=cls.bil)
        cls.yonetici = kullanici("yon", Yetki.YONETIM)
        cls.yetkisiz = kullanici("yok")
        cls.donem = DersMazeretDonemi.objects.create(ad="2026-2027 Bahar")

    def test_birimler_plan_programin_altinda(self):
        grup = Birim.objects.get(slug="mazeretler")
        self.assertEqual(grup.ust.slug, "plan-program")
        self.assertEqual(Birim.objects.get(slug="ders-mazeretleri").ust, grup)
        sinav = Birim.objects.get(slug="sinav-mazeretleri")
        self.assertEqual((sinav.ust, sinav.durum, sinav.modul_url), (grup, Birim.KULLANIMDA, "mazeret:sinav"))

    def test_bolum_yalniz_kendi_personelini_gorur(self):
        y = yetki(self.bilci)
        self.assertEqual(set(servis.personeller(y)), {self.ayse, self.ali})
        self.client.force_login(self.bilci)
        r = self.client.get(reverse("mazeret:ders"))
        self.assertContains(r, "Ayşe YILMAZ")
        self.assertNotContains(r, "Veli ÇELİK")
        # adresi elle yazsa da başka bölümün personelini açamaz ve yazamaz
        url = reverse("mazeret:bildirim", args=[self.donem.pk, self.veli.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.post(url, {"hucreler": "{}", "surum": "0"})
        self.assertFalse(DersMazeretBildirimi.objects.filter(personel=self.veli).exists())
        r = self.client.post(reverse("mazeret:toplu", args=[self.donem.pk]), {"p": [self.veli.pk]})
        self.assertEqual(r.status_code, 404)

    def test_yetkisiz_kullanici_giremez(self):
        self.client.force_login(self.yetkisiz)
        self.assertEqual(self.client.get(reverse("mazeret:ders")).status_code, 403)

    def test_kaydetme_ve_hucre_suzme(self):
        b = servis.kaydet(self.bilci, yetki(self.bilci), self.donem, self.ayse,
                          {"0-0": "no", "1-2": "maybe", "4-7": "no", "5-0": "no", "0-8": "no", "2-2": "evet"}, okunan_surum=0)
        self.assertEqual(b.hucreler, {"0-0": "no", "1-2": "maybe", "4-7": "no"})  # 5 gün × 8 saat dışı ve geçersizler atılır
        self.assertEqual((b.yasak_sayisi, b.kosullu_sayisi, b.surum), (2, 1, 1))
        b = servis.kaydet(self.bilci, yetki(self.bilci), self.donem, self.ayse, {}, okunan_surum=1)
        self.assertEqual((b.hucreler, b.surum), ({}, 2))  # boş şablon = mazereti yok
        self.assertEqual(DersMazeretGecmisi.objects.filter(bildirim=b).count(), 2)

    def test_eszamanli_degisiklik_reddedilir(self):
        servis.kaydet(self.bilci, yetki(self.bilci), self.donem, self.ayse, {}, okunan_surum=0)
        with self.assertRaisesMessage(MazeretHatasi, "başka bir kullanıcı"):
            servis.kaydet(self.yonetici, yetki(self.yonetici), self.donem, self.ayse, {"0-0": "no"}, okunan_surum=0)

    def test_kapali_donemde_yalniz_yonetici_yazar(self):
        self.donem.giris_acik = False
        self.donem.save()
        with self.assertRaises(MazeretHatasi):
            servis.kaydet(self.bilci, yetki(self.bilci), self.donem, self.ayse, {}, okunan_surum=0)
        servis.kaydet(self.yonetici, yetki(self.yonetici), self.donem, self.ayse, {}, okunan_surum=0)

    def test_toplu_mazereti_yok_mevcut_bildirime_dokunmaz(self):
        servis.kaydet(self.bilci, yetki(self.bilci), self.donem, self.ayse, {"0-0": "no"}, okunan_surum=0)
        self.client.force_login(self.bilci)
        self.client.post(reverse("mazeret:toplu", args=[self.donem.pk]), {"p": [self.ayse.pk, self.ali.pk]})
        self.assertEqual(DersMazeretBildirimi.objects.get(personel=self.ayse).hucreler, {"0-0": "no"})
        self.assertEqual(DersMazeretBildirimi.objects.get(personel=self.ali).hucreler, {})

    def test_ekrandan_kaydetme_programa_isler(self):
        okul = School.objects.create(name="Bahar programı")
        for i in range(6):
            Period.objects.create(school=okul, index=i, name=f"{i + 1}")
        ogretmen = Teacher.objects.create(school=okul, first_name="Ayşe", last_name="Yılmaz")
        Availability.objects.create(school=okul, teacher=ogretmen, day=3, period=3, state="no")
        self.donem.okul = okul
        self.donem.save()
        self.client.force_login(self.bilci)
        url = reverse("mazeret:bildirim", args=[self.donem.pk, self.ayse.pk])
        r = self.client.get(url)
        self.assertContains(r, "Ders verilemez")
        self.assertContains(r, 'class="mz-hucre"', count=40)  # 5 gün × 8 saat
        self.assertContains(r, "Pazartesi")
        hucreler = {"0-0": "no", "1-1": "maybe", "2-7": "no"}  # 8. saat programda yok
        self.client.post(url, {"hucreler": json.dumps(hucreler), "surum": "0", "aciklama": "Salı lisansüstü"})
        self.assertEqual(
            set(Availability.objects.filter(teacher=ogretmen).values_list("day", "period", "state")),
            {(0, 0, "no"), (1, 1, "maybe")},
        )
        # programda öğretmeni olmayan personel: kayıt yapılır, müsaitliğe yazılmaz
        r = self.client.post(reverse("mazeret:bildirim", args=[self.donem.pk, self.ali.pk]),
                             {"hucreler": "{}", "surum": "0"}, follow=True)
        self.assertContains(r, "eşleşen öğretmen bulunamadı")
        self.assertTrue(DersMazeretBildirimi.objects.filter(personel=self.ali).exists())

    def test_ana_sayfa_eksik_bildirim(self):
        self.client.force_login(self.bilci)
        r = self.client.get(reverse("core:panel"))
        self.assertContains(r, "Ders mazereti bildirilmemiş personel")
        self.assertContains(r, "Ders mazeretleri")  # menü kısayolu
        servis.toplu_mazeretsiz(self.bilci, yetki(self.bilci), self.donem, [self.ayse, self.ali])
        self.assertNotContains(self.client.get(reverse("core:panel")), "Ders mazereti bildirilmemiş personel")


class SinavMazeretiTestleri(TestCase):
    """Oturum bazında sınav mazereti ve Sınav Planlama'ya aktarım."""

    @classmethod
    def setUpTestData(cls):
        cls.bil = Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        cls.elk = Bolum.objects.create(ad="Elektrik", kod="ELK")
        cls.ayse = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=cls.bil, sinav_rolleri="AG")
        cls.ali = Personel.objects.create(ad_soyad="Ali KAYA", bolum=cls.bil)
        cls.veli = Personel.objects.create(ad_soyad="Veli ÇELİK", bolum=cls.elk)
        plan = Birim.objects.get(slug="plan-program")
        cls.bilci = User.objects.create_user("bil", password="x-Parola-123", bolum=cls.bil)
        Yetki.objects.create(kullanici=cls.bilci, birim=plan, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        cls.yonetici = User.objects.create_user("yon", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.yonetici, birim=plan, seviye=Yetki.YONETIM, kapsam=Yetki.TUM)
        cls.okul = School.objects.create(name="Güz programı")
        cls.t_ayse = Teacher.objects.create(school=cls.okul, first_name="Ayşe", last_name="Yılmaz")
        cls.t_ali = Teacher.objects.create(school=cls.okul, first_name="Ali", last_name="Kaya")
        cls.period = ExamPeriod.objects.create(
            school=cls.okul, name="Güz vize", start_date=datetime.date(2026, 11, 2), end_date=datetime.date(2026, 11, 4),
            sessions=["09:30", "13:30"])
        cls.donem = SinavMazeretDonemi.objects.create(ad="Güz vize", sinav_donemi=cls.period)

    def test_izgara_ve_aktarim(self):
        self.client.force_login(self.bilci)
        url = reverse("mazeret:sinav_bildirim", args=[self.donem.pk, self.ayse.pk])
        r = self.client.get(url)
        self.assertContains(r, "Görev verilemez")
        self.assertContains(r, 'class="mz-hucre"', count=6)  # 3 gün × 2 oturum
        self.assertContains(r, "02.11.2026 Pazartesi")
        hucreler = {"2026-11-02 09:30": "no", "2026-11-03 09:30": "no", "2026-11-03 13:30": "no",
                    "2026-11-04 13:30": "maybe", "2026-11-05 09:30": "no"}  # son gün dönemde yok
        r = self.client.post(url, {"hucreler": json.dumps(hucreler), "surum": "0"}, follow=True)
        self.assertContains(r, "gözetmen müsaitliği güncellendi")
        self.period.refresh_from_db()
        k = str(self.t_ayse.pk)
        self.assertEqual(self.period.proctor_blocks[k], ["2026-11-02#0", "2026-11-03"])
        self.assertEqual(self.period.proctor_soft[k], ["2026-11-04#1"])
        # bildirim "mazereti yok" olunca işaretler kalkar
        self.client.post(url, {"hucreler": "{}", "surum": "1"})
        self.period.refresh_from_db()
        self.assertNotIn(k, self.period.proctor_blocks)
        self.assertNotIn(k, self.period.proctor_soft)

    def test_bolum_baska_bolumu_goremez(self):
        self.client.force_login(self.bilci)
        r = self.client.get(reverse("mazeret:sinav"))
        self.assertContains(r, "Ayşe YILMAZ")
        self.assertNotContains(r, "Veli ÇELİK")
        url = reverse("mazeret:sinav_bildirim", args=[self.donem.pk, self.veli.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_tum_donem_aktarimi_bildirimsizi_kapatir_rolleri_yazar(self):
        y = servis.yetki(SahteIstek(self.yonetici), servis.TURLER["sinav"])
        servis.kaydet(self.yonetici, y, self.donem, self.ayse, {}, okunan_surum=0)
        servis.sinav_donemini_esitle(self.period.pk)  # sınav programı oluşturulmadan önce çağrılır
        self.period.refresh_from_db()
        self.assertTrue(self.period.duty_roles)
        self.assertEqual(self.period.proctor_blocks, {str(self.t_ali.pk): ["2026-11-02", "2026-11-03", "2026-11-04"]})
        self.assertEqual(self.period.roles_of(self.t_ayse.pk), "AG")
        self.assertEqual(self.period.roles_of(self.t_ali.pk), "GT")
        # ayar kapalıysa bildirimsize dokunulmaz
        self.donem.bildirimsize_gorev_yok = False
        self.donem.save()
        self.period.proctor_blocks = {}
        self.period.save()
        servis.sinava_aktar(self.donem)
        self.period.refresh_from_db()
        self.assertEqual(self.period.proctor_blocks, {})

    def test_ana_sayfa_eksik_bildirim(self):
        self.client.force_login(self.bilci)
        r = self.client.get(reverse("core:panel"))
        self.assertContains(r, "Sınav mazereti bildirilmemiş personel")
        self.assertContains(r, "Sınav mazeretleri")


class TopluTabloTestleri(SinavMazeretiTestleri):
    """Toplu tablo, yoklamadaki izinlerin ✗ olarak gelmesi ve bölüm teslimi (09.11.2026)."""

    def _izin(self, personel, bas, bit):
        from django.utils import timezone

        from yoklama.models import IzinTuru, YoklamaKaydi

        tur = IzinTuru.objects.get(ad="Yıllık İzin")
        tz = timezone.get_current_timezone()
        return YoklamaKaydi.objects.create(personel=personel, tur=tur, baslangic=timezone.make_aware(bas, tz),
                                           bitis=timezone.make_aware(bit, tz))

    def test_tablo_kaydet_ve_teslim(self):
        from .models import MazeretTeslimi

        self.client.force_login(self.bilci)
        url = reverse("mazeret:sinav_tablo", args=[self.donem.pk])
        r = self.client.get(url)
        self.assertContains(r, "Ayşe YILMAZ")
        self.assertNotContains(r, "Veli ÇELİK")  # başka bölüm
        self.assertContains(r, 'class="mz-hucre"', count=12)  # 2 kişi × 3 gün × 2 oturum
        # eksik varken teslim edilemez
        r = self.client.post(reverse("mazeret:sinav_teslim", args=[self.donem.pk]), follow=True)
        self.assertContains(r, "bildirimi eksik")
        veriler = {str(self.ayse.pk): {"2026-11-02 09:30": "no"}, str(self.ali.pk): {}}
        surumler = {str(self.ayse.pk): 0, str(self.ali.pk): 0}
        r = self.client.post(url, {"veriler": json.dumps(veriler), "surumler": json.dumps(surumler)}, follow=True)
        self.assertContains(r, "2 personelin bildirimi kaydedildi")
        self.assertEqual(self.donem.bildirimler.get(personel=self.ali).hucreler, {})  # boş satır = mazereti yok
        self.period.refresh_from_db()
        self.assertEqual(self.period.proctor_blocks[str(self.t_ayse.pk)], ["2026-11-02#0"])
        # değişmeyen satır yeniden yazılmaz; başka bölümün personeli reddedilir
        surumler = {str(self.ayse.pk): 1, str(self.ali.pk): 1}
        r = self.client.post(url, {"veriler": json.dumps(veriler), "surumler": json.dumps(surumler)}, follow=True)
        self.assertContains(r, "0 personelin bildirimi kaydedildi, 2 personelinki değişmedi")
        r = self.client.post(url, {"veriler": json.dumps({str(self.veli.pk): {}}), "surumler": "{}"}, follow=True)
        self.assertContains(r, "kapsamınız dışında")
        # teslim
        self.client.post(reverse("mazeret:sinav_teslim", args=[self.donem.pk]))
        self.assertTrue(MazeretTeslimi.objects.filter(tur="sinav", donem_id=self.donem.pk, bolum=self.bil).exists())
        r = self.client.get(reverse("mazeret:sinav"))
        self.assertContains(r, "teslim ettiniz")

    def test_yoklamadaki_izin_oturumu_kapatir(self):
        self._izin(self.ali, datetime.datetime(2026, 11, 3), datetime.datetime(2026, 11, 4))  # 3 Kasım tüm gün
        self._izin(self.ayse, datetime.datetime(2026, 11, 4, 13, 0), datetime.datetime(2026, 11, 4, 17, 0))
        izin = servis.izin_isaretleri(self.donem, [self.ali.pk, self.ayse.pk])
        self.assertEqual(izin[self.ali.pk], {"2026-11-03 09:30": "Yıllık İzin", "2026-11-03 13:30": "Yıllık İzin"})
        self.assertEqual(set(izin[self.ayse.pk]), {"2026-11-04 13:30"})
        self.client.force_login(self.bilci)
        r = self.client.get(reverse("mazeret:sinav_tablo", args=[self.donem.pk]))
        self.assertEqual(r.context["izinler_d"][str(self.ali.pk)]["2026-11-03 09:30"], "Yıllık İzin")  # tabloda ✗ (JS)
        # bildirimi olmasa da aktarımda izinli oturum kapalı
        self.donem.bildirimsize_gorev_yok = False
        self.donem.save()
        servis.sinava_aktar(self.donem)
        self.period.refresh_from_db()
        self.assertEqual(self.period.proctor_blocks[str(self.t_ali.pk)], ["2026-11-03"])
        self.assertEqual(self.period.proctor_blocks[str(self.t_ayse.pk)], ["2026-11-04#1"])

    def test_yonetici_panosu_ve_ana_sayfa(self):
        self.client.force_login(self.yonetici)
        r = self.client.get(reverse("mazeret:sinav"))
        self.assertContains(r, "bölüm teslim etti")
        self.assertContains(r, reverse("mazeret:sinav_tablo", args=[self.donem.pk]) + f"?bolum={self.bil.pk}")
        r = self.client.get(reverse("mazeret:sinav_tablo", args=[self.donem.pk]))
        self.assertContains(r, "Tabloyu açmak için bir bölüm seçin")
        Personel.objects.create(ad_soyad="İdari KİŞİ")  # bölümü yok: tabloyu Plan Program doldurur
        r = self.client.get(reverse("mazeret:sinav_tablo", args=[self.donem.pk]), {"bolum": "yok"})
        self.assertContains(r, "İdari KİŞİ")
        self.assertNotContains(r, "Ayşe YILMAZ")
        self.assertNotContains(r, "Bildirimi teslim et")
        # bölüm hesabı: bildirim tamamsa ana sayfada "teslim edin"
        y = servis.yetki(SahteIstek(self.bilci), servis.TURLER["sinav"])
        for p in (self.ayse, self.ali):
            servis.kaydet(self.bilci, y, self.donem, p, {}, okunan_surum=0)
        self.client.force_login(self.bilci)
        self.assertContains(self.client.get(reverse("core:panel")), "Sınav mazereti bildirimini teslim edin")
