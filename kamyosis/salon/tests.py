import datetime

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Birim, Yetki

from . import servis
from .models import Salon, SalonKaydi
from .servis import SalonHatasi

T = datetime.time
GUN = datetime.date(2027, 8, 18)


class SalonTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ks = Salon.objects.get(ad="Konferans Salonu")
        cls.aa = Salon.objects.get(ad="Atatürk Amfisi")
        cls.alp = Salon.objects.get(ad="Alparslan Amfisi")
        cls.herkes = User.objects.create_user("herkes", password="x-Parola-123")
        cls.yetkili = User.objects.create_user("plan", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.yetkili, birim=Birim.objects.get(slug="plan-program"), seviye=Yetki.DUZENLEME,
                             kapsam=Yetki.TUM)  # üst birimden gelen yetki

    def test_baslangic_verisi(self):
        self.assertEqual([s.ad for s in servis.salonlar()], ["Konferans Salonu", "Atatürk Amfisi", "Alparslan Amfisi"])
        self.assertEqual(Birim.objects.get(slug="salon-durumu").ust.slug, "plan-program")

    def test_cakisma_engellenir(self):
        servis.ekle(self.yetkili, [self.ks], GUN, False, T(8, 30), T(12), "Kısmın dersi")
        with self.assertRaisesMessage(SalonHatasi, "dolu"):
            servis.ekle(self.yetkili, [self.ks], GUN, False, T(11), T(13), "Toplantı")
        servis.ekle(self.yetkili, [self.ks], GUN, False, T(12), T(13), "Toplantı")  # uç uca gelebilir
        servis.ekle(self.yetkili, [self.aa], GUN, False, T(11), T(13), "Toplantı")  # başka salon
        with self.assertRaises(SalonHatasi):  # tüm gün her şeyle çakışır
            servis.ekle(self.yetkili, [self.aa], GUN, True, None, None, "Tören")
        with self.assertRaisesMessage(SalonHatasi, "Bitiş saati"):
            servis.ekle(self.yetkili, [self.alp], GUN, False, T(14), T(13), "Ters")

    def test_haftalik_tekrar_ve_coklu_salon(self):
        kayitlar = servis.ekle(self.yetkili, [self.ks, self.aa], GUN, False, T(9), T(10), "Ders",
                               tekrar_bitis=GUN + datetime.timedelta(days=21))
        self.assertEqual(len(kayitlar), 8)  # 2 salon × 4 hafta
        self.assertEqual(len({k.seri for k in kayitlar}), 1)
        # serinin bir haftası doluysa hiçbiri girilmez
        with self.assertRaisesMessage(SalonHatasi, "Hiçbir kayıt girilmedi"):
            servis.ekle(self.yetkili, [self.alp, self.ks], GUN - datetime.timedelta(days=7), False, T(9, 30), T(11), "X",
                        tekrar_bitis=GUN)
        self.assertFalse(SalonKaydi.objects.filter(salon=self.alp).exists())

    def test_gun_gorunumu_musait_araliklar(self):
        servis.ekle(self.yetkili, [self.ks], GUN, False, T(7), T(12), "Kısmın dersi")
        sutunlar, _saatler = servis.gun(GUN, [self.ks, self.aa])
        ks = sutunlar[0]
        self.assertEqual([(m["bas"], m["bit"]) for m in ks["musait"]], [("12:00", "22:00")])
        self.assertEqual(ks["bloklar"][0]["ust"], 0)
        self.assertEqual([(m["bas"], m["bit"]) for m in sutunlar[1]["musait"]], [("07:00", "22:00")])

    def test_herkes_gorur_yetkili_girer(self):
        servis.ekle(self.yetkili, [self.ks], GUN, False, T(8, 30), T(12), "Kısmın dersi")
        self.client.force_login(self.herkes)
        for url in (reverse("salon:yil") + "?yil=2027", reverse("salon:ay", args=[2027, 8]),
                    reverse("salon:gun", args=[GUN.isoformat()])):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotContains(r, "Kayıt ekle")
        self.assertContains(self.client.get(reverse("salon:gun", args=[GUN.isoformat()])), "Kısmın dersi")
        self.assertContains(self.client.get(reverse("salon:gun", args=[GUN.isoformat()])), "12:00–22:00")
        r = self.client.get(reverse("salon:gun", args=[GUN.isoformat()]))
        self.assertNotRegex(r.content.decode(), r"(top|height): \d+,\d")  # Türkçe ondalık virgül CSS'i bozmasın
        self.assertContains(r, "top: 33.333%")  # 12:00 = 5 saat / 15 saat
        self.assertEqual(self.client.get(reverse("salon:yeni")).status_code, 403)
        k = SalonKaydi.objects.get()
        self.assertEqual(self.client.post(reverse("salon:kayit", args=[k.pk]), {"islem": "sil"}).status_code, 403)
        self.assertContains(self.client.get("/"), f'href="{reverse("salon:yil")}"')  # menüde, yetkisi olmasa da

    def test_yetkili_formdan_girer_ve_siler(self):
        self.client.force_login(self.yetkili)
        r = self.client.post(reverse("salon:yeni"), {"salon": [self.ks.pk, self.alp.pk], "tarih": GUN.isoformat(),
                                                    "bas": "08:30", "bit": "12:00", "baslik": "Kısmın dersi",
                                                    "tekrar": "hafta", "tekrar_bitis": (GUN + datetime.timedelta(days=7)).isoformat()})
        self.assertRedirects(r, reverse("salon:gun", args=[GUN.isoformat()]), fetch_redirect_response=False)
        self.assertEqual(SalonKaydi.objects.count(), 4)
        k = SalonKaydi.objects.filter(salon=self.ks).order_by("tarih").first()
        r = self.client.get(reverse("salon:kayit", args=[k.pk]))
        self.assertContains(r, "Bu ve sonraki haftaları sil")
        self.client.post(reverse("salon:kayit", args=[k.pk]), {"islem": "seri_sil"})
        self.assertEqual(SalonKaydi.objects.count(), 0)  # seri tüm salonlardaki haftaları kapsar
        r = self.client.get(reverse("salon:yil") + "?yil=2027")
        self.assertContains(r, "Kayıt ekle")
