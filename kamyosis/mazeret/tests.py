import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Birim, Yetki
from personel.models import Bolum, Personel
from timetable.models import Availability, Period, School, Teacher

from . import servis
from .models import DersMazeretBildirimi, DersMazeretDonemi, DersMazeretGecmisi
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
        self.assertEqual(Birim.objects.get(slug="sinav-mazeretleri").durum, Birim.PLANLANDI)

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
