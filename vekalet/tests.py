import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.models import Birim, Yetki
from personel.models import Bolum, Personel

from . import servis
from .models import Vekalet

GUN = datetime.timedelta(days=1)


class VekaletTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bil = Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        cls.ayse = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=cls.bil)
        cls.ali = Personel.objects.create(ad_soyad="Ali KAYA", bolum=cls.bil)
        cls.veli = Personel.objects.create(ad_soyad="Veli ÇELİK", gorev_unvani="Personel Şube Müdürü")
        cls.bil.baskan = cls.ayse
        cls.bil.save()
        idari = Birim.objects.get(slug="idari-isler")
        vekalet = Birim.objects.get(slug="vekalet")
        cls.idareci = User.objects.create_user("iiy", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.idareci, birim=idari, seviye=Yetki.DUZENLEME)
        cls.bolumcu = User.objects.create_user("bil", password="x-Parola-123", bolum=cls.bil)
        Yetki.objects.create(kullanici=cls.bolumcu, birim=vekalet, seviye=Yetki.GORUNTULEME, kapsam=Yetki.BOLUM)
        cls.yetkisiz = User.objects.create_user("yok", password="x-Parola-123")

    def _veri(self, **ek):
        bugun = timezone.localdate()
        veri = {"veren": self.ayse.pk, "vekil": self.ali.pk, "gorev": "Bilgisayar Teknolojisi Bölüm Başkanı",
                "neden": "rapor", "baslangic": bugun.isoformat(), "bitis": (bugun + 4 * GUN).isoformat(),
                "aciklama": ""}
        veri.update(ek)
        return veri

    def test_birim_idari_islerin_altinda(self):
        b = Birim.objects.get(slug="vekalet")
        self.assertEqual((b.ust.slug, b.modul_url), ("idari-isler", "vekalet:liste"))

    def test_sekmeler_ve_yetkiler(self):
        self.client.force_login(self.yetkisiz)
        self.assertEqual(self.client.get(reverse("vekalet:liste")).status_code, 403)
        # görüntüleme: vekâletler sekmesi var, işlemler yok
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("vekalet:liste"))
        self.assertContains(r, "Vekâletler")
        self.assertNotContains(r, "Vekâlet işlemleri")
        self.assertEqual(self.client.get(reverse("vekalet:islemler")).status_code, 403)
        self.assertEqual(self.client.post(reverse("vekalet:islemler"), self._veri()).status_code, 403)
        self.assertFalse(Vekalet.objects.exists())
        # İdari İşler yetkilisi iki sekmeyi de görür
        self.client.force_login(self.idareci)
        self.assertContains(self.client.get(reverse("vekalet:liste")), "Vekâlet işlemleri")

    def test_kaydet_ve_listede_gor(self):
        self.client.force_login(self.idareci)
        r = self.client.post(reverse("vekalet:islemler"), self._veri(), follow=True)
        self.assertContains(r, "Vekâlet kaydedildi")
        v = Vekalet.objects.get()
        self.assertEqual((v.durum, v.kalan_gun, v.gun_sayisi, v.olusturan), ("yururlukte", 5, 5, self.idareci))
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("vekalet:liste"))
        self.assertContains(r, "Ali KAYA")
        self.assertContains(r, "5 gün kaldı")
        self.assertEqual(r.context["yururlukte"], [v])

    def test_hatalar_ve_uyarilar(self):
        self.client.force_login(self.idareci)
        r = self.client.post(reverse("vekalet:islemler"), self._veri(vekil=self.ayse.pk))
        self.assertContains(r, "kendisine vekâlet veremez")
        bugun = timezone.localdate()
        r = self.client.post(reverse("vekalet:islemler"), self._veri(bitis=(bugun - GUN).isoformat()))
        self.assertFalse(Vekalet.objects.exists())  # bitiş başlangıçtan önce
        self.client.post(reverse("vekalet:islemler"), self._veri())
        # aynı görev, çakışan tarih: hata
        r = self.client.post(reverse("vekalet:islemler"), self._veri(vekil=self.veli.pk))
        self.assertContains(r, "zaten vekâlet vermiş")
        self.assertEqual(Vekalet.objects.count(), 1)
        # vekil (Ali) aynı tarihlerde kendisi vekâlet vermiş: uyarı, onaylanınca kaydedilir
        veri = self._veri(veren=self.veli.pk, vekil=self.ayse.pk, gorev="Personel Şube Müdürü")
        Vekalet.objects.create(veren=self.ayse, vekil=self.veli, gorev="Başka görev", baslangic=bugun, bitis=bugun)
        r = self.client.post(reverse("vekalet:islemler"), veri)
        self.assertContains(r, "kendisi de")
        self.assertContains(r, "Yine de kaydet")
        self.assertEqual(Vekalet.objects.count(), 2)
        self.client.post(reverse("vekalet:islemler"), {**veri, "onay": "1"})
        self.assertEqual(Vekalet.objects.count(), 3)

    def test_vekil_izinliyse_uyarir_ve_izinler_formda(self):
        from yoklama.models import IzinTuru, YoklamaKaydi

        bugun = timezone.localdate()
        tz = timezone.get_current_timezone()
        tur = IzinTuru.objects.get(ad="İstirahat")
        YoklamaKaydi.objects.create(
            personel=self.ali, tur=tur,
            baslangic=timezone.make_aware(datetime.datetime.combine(bugun + GUN, datetime.time(0)), tz),
            bitis=timezone.make_aware(datetime.datetime.combine(bugun + 3 * GUN, datetime.time(0)), tz))
        hatalar, uyarilar = servis.kontrol(Vekalet(veren=self.ayse, vekil=self.ali, gorev="X", baslangic=bugun,
                                                   bitis=bugun + 4 * GUN))
        self.assertEqual(hatalar, [])
        self.assertIn("İstirahat", uyarilar[0])
        izin = servis.yaklasan_izinler()[self.ali.pk][0]
        self.assertEqual((izin["bas"], izin["bit"], izin["neden"]),
                         ((bugun + GUN).isoformat(), (bugun + 2 * GUN).isoformat(), "rapor"))

    def test_gorev_onerisi(self):
        g = servis.gorev_onerileri()
        self.assertEqual(g[self.ayse.pk], "Bilgisayar Teknolojisi Bölüm Başkanı")
        self.assertEqual(g[self.veli.pk], "Personel Şube Müdürü")
        self.assertNotIn(self.ali.pk, g)

    def test_erken_sonlandir_ve_sil(self):
        bugun = timezone.localdate()
        v = Vekalet.objects.create(veren=self.ayse, vekil=self.ali, gorev="X", baslangic=bugun, bitis=bugun + GUN)
        self.client.force_login(self.idareci)
        self.client.post(reverse("vekalet:sonlandir", args=[v.pk]))
        v.refresh_from_db()
        self.assertEqual(v.durum, "sonlandirildi")
        yururlukte, _, gecmis = servis.gruplar()
        self.assertEqual((yururlukte, gecmis), ([], [v]))
        self.client.post(reverse("vekalet:sonlandir", args=[v.pk]))  # geri al
        v.refresh_from_db()
        self.assertEqual(v.durum, "yururlukte")
        self.client.post(reverse("vekalet:sil", args=[v.pk]))
        self.assertFalse(Vekalet.objects.exists())

    def _izin(self, personel, gun_bas, gun_bit, ad="İstirahat"):
        from yoklama.models import IzinTuru, YoklamaKaydi

        tz = timezone.get_current_timezone()
        bugun = timezone.localdate()
        return YoklamaKaydi.objects.create(
            personel=personel, tur=IzinTuru.objects.get(ad=ad),
            baslangic=timezone.make_aware(datetime.datetime.combine(bugun + gun_bas * GUN, datetime.time(0)), tz),
            bitis=timezone.make_aware(datetime.datetime.combine(bugun + gun_bit * GUN, datetime.time(0)), tz))

    def test_vekaleti_girilmemis_yonetici(self):
        self._izin(self.ayse, 1, 3)   # bölüm başkanı, 2 gün istirahat
        self._izin(self.ali, 1, 3)    # yönetici değil: sayılmaz
        e = servis.eksik_vekaletler()
        self.assertEqual([(x["personel"], x["gorev"], x["neden"]) for x in e],
                         [(self.ayse, "Bilgisayar Teknolojisi Bölüm Başkanı", "rapor")])
        self.client.force_login(self.idareci)
        self.assertContains(self.client.get(reverse("core:panel")), "Vekâleti girilmemiş yönetici")
        r = self.client.get(reverse("vekalet:islemler"))
        self.assertContains(r, "Vekâlet gir")
        # kutudaki bağlantı formu doldurur
        bugun = timezone.localdate()
        r = self.client.get(reverse("vekalet:islemler"), {"veren": self.ayse.pk, "bas": (bugun + GUN).isoformat(),
                                                          "bit": (bugun + 2 * GUN).isoformat(), "neden": "rapor"})
        self.assertEqual(r.context["form"].initial["gorev"], "Bilgisayar Teknolojisi Bölüm Başkanı")
        # vekâlet girilince uyarı kalkar
        Vekalet.objects.create(veren=self.ayse, vekil=self.ali, gorev="X", baslangic=bugun + GUN, bitis=bugun + 2 * GUN)
        self.assertEqual(servis.eksik_vekaletler(), [])

    def test_teskilat_ve_kartta_vekil_notu(self):
        from personel.models import TeskilatBirimi

        bugun = timezone.localdate()
        Vekalet.objects.create(veren=self.ayse, vekil=self.ali, gorev="Bilgisayar Teknolojisi Bölüm Başkanı",
                               baslangic=bugun, bitis=bugun + GUN)
        self.client.force_login(User.objects.create_superuser("su", password="x-Parola-123"))
        r = self.client.get(reverse("personel:detay", args=[self.ayse.pk]))
        self.assertContains(r, "Vekili: <b>Ali KAYA</b>")
        r = self.client.get(reverse("personel:detay", args=[self.ali.pk]))
        self.assertContains(r, "Vekâleten: <b>Bilgisayar Teknolojisi Bölüm Başkanı</b>")
        self.assertTrue(TeskilatBirimi.objects.filter(bolum=self.bil).exists())  # bölümle birlikte açılır
        self.assertContains(self.client.get(reverse("personel:teskilat")), "Vekili: <b>Ali KAYA</b>")
        # ana sayfada yürürlükteki vekâlet
        self.client.force_login(self.bolumcu)
        self.assertContains(self.client.get(reverse("core:panel")), "Yürürlükte vekâlet")

    def test_kendi_birimi_kapsami(self):
        """Bölüm başkanı hesabı (kendi birimi): yalnız bölümünün personeli ve başkanı vekâlet verir; başkan başka
        bölümün kadrosunda olsa da (iki bölümün başkanı) seçilebilir."""
        elk = Bolum.objects.create(ad="Elektrik", kod="ELK")
        elk.baskan = self.ayse  # Ayşe hem Bilgisayar hem Elektrik başkanı (kadrosu Bilgisayar'da)
        elk.save()
        elkci = Personel.objects.create(ad_soyad="Can DEMİR", bolum=elk)
        hesap = User.objects.create_user("bb.elk", password="x-Parola-123", bolum=elk)
        Yetki.objects.create(kullanici=hesap, birim=Birim.objects.get(slug="vekalet"), seviye=Yetki.DUZENLEME,
                             kapsam=Yetki.BOLUM)
        bugun = timezone.localdate()
        baska = Vekalet.objects.create(veren=self.ali, vekil=self.veli, gorev="X", baslangic=bugun, bitis=bugun)
        self.client.force_login(hesap)
        r = self.client.get(reverse("vekalet:islemler"))
        self.assertEqual(set(r.context["form"].fields["veren"].queryset), {self.ayse, elkci})
        self.assertEqual(r.context["form"].initial["veren"], self.ayse.pk)  # hazır seçili: bölümün başkanı
        self.assertEqual(r.context["form"].initial["gorev"], "Elektrik Bölüm Başkanı")
        self.assertEqual(r.context["kayitlar"], [])  # başka bölümün kaydı görünmez
        self.assertContains(r, "Elektrik için")
        # kapsam dışı veren reddedilir; başka bölümün kaydına dokunamaz
        self.client.post(reverse("vekalet:islemler"), self._veri(veren=self.ali.pk, vekil=self.veli.pk, gorev="Y"))
        self.assertEqual(Vekalet.objects.count(), 1)
        self.assertEqual(self.client.post(reverse("vekalet:sil", args=[baska.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("vekalet:duzenle", args=[baska.pk])).status_code, 403)
        # kendi başkanı için girer; vekil herhangi biri olabilir
        r = self.client.post(reverse("vekalet:islemler"), self._veri(gorev="Elektrik Bölüm Başkanı", vekil=self.veli.pk),
                             follow=True)
        self.assertContains(r, "Vekâlet kaydedildi")
        # tüm okul kapsamlı İdari İşler hesabı her şeyi görür
        self.client.force_login(self.idareci)
        self.assertEqual(len(self.client.get(reverse("vekalet:islemler")).context["kayitlar"]), 2)
