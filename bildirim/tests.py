import datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.models import Birim, Yetki
from personel.models import Bolum, Personel

from . import servis
from .models import Bildirim, BildirimTercihi, ZamanliIs
from .turler import TURLER, yetkililer


def _yetki(u, slug, seviye=Yetki.GORUNTULEME, kapsam=Yetki.TUM):
    return Yetki.objects.create(kullanici=u, birim=Birim.objects.get(slug=slug), seviye=seviye, kapsam=kapsam)


class BildirimTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.su = User.objects.create_superuser("su", password="x-Parola-123")
        cls.iiy = User.objects.create_user("iiy", password="x-Parola-123")
        cls.bolumcu = User.objects.create_user("bol", password="x-Parola-123")
        cls.yok = User.objects.create_user("yok", password="x-Parola-123")
        _yetki(cls.iiy, "idari-isler", Yetki.YONETIM)
        _yetki(cls.bolumcu, "nobet-gruplari")
        _yetki(cls.bolumcu, "personel-yoklamasi", Yetki.DUZENLEME, Yetki.BOLUM)

    def _gonder(self, kime, tur="nobet", url="/nobet/"):
        servis.gonder(tur, [kime.pk], "Başlık", "metin", url)
        return Bildirim.objects.filter(kullanici=kime).first()

    def test_alicilar_yetkiden(self):
        nobet = yetkililer("nobet-gruplari")
        self.assertIn(self.bolumcu.pk, nobet)
        self.assertIn(self.iiy.pk, nobet)       # üst birimden (İdari İşler) gelir
        self.assertIn(self.su.pk, nobet)        # sistem yöneticisi hepsini alır
        self.assertNotIn(self.yok.pk, nobet)
        ozet = yetkililer("personel-yoklamasi", Yetki.YONETIM, tum_okul=True)
        self.assertIn(self.iiy.pk, ozet)
        self.assertNotIn(self.bolumcu.pk, ozet)  # kendi birimi kapsamlı hesap özeti almaz

    def test_kapali_ve_islemi_yapan_almaz(self):
        BildirimTercihi.objects.create(kullanici=self.iiy, tur="nobet", mod=BildirimTercihi.KAPALI)
        n = servis.gonder("nobet", [self.su.pk, self.iiy.pk, self.bolumcu.pk], "B", haric=self.su)
        self.assertEqual(n, 1)
        self.assertEqual(list(Bildirim.objects.values_list("kullanici_id", flat=True)), [self.bolumcu.pk])

    def test_nobet_kesinlesince(self):
        from nobet.models import NobetDonemi

        d = NobetDonemi.objects.create(yil=2026, ay=12)
        self.client.force_login(self.su)
        self.client.post(reverse("nobet:islem", args=[2026, 12]), {"islem": "kesinlestir"})
        b = Bildirim.objects.get(kullanici=self.bolumcu)
        self.assertEqual((b.tur, b.baslik), ("nobet", "Nöbet grupları kesinleşti"))
        self.assertEqual(b.url, reverse("nobet:donem", args=[2026, 12]))
        self.assertFalse(Bildirim.objects.filter(kullanici=self.su).exists())  # kesinleştiren almaz
        d.refresh_from_db()
        self.assertEqual(d.durum, NobetDonemi.KESIN)

    def test_vekalet_kendi_birimi(self):
        from vekalet.models import Vekalet

        bil = Bolum.objects.create(ad="Bilgisayar", kod="BİL")
        elk = Bolum.objects.create(ad="Elektrik", kod="ELK")
        bb = User.objects.create_user("bb", password="x-Parola-123", bolum=bil)
        eb = User.objects.create_user("eb", password="x-Parola-123", bolum=elk)
        for u in (bb, eb):
            _yetki(u, "vekalet", Yetki.DUZENLEME, Yetki.BOLUM)
        a = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=bil)
        b = Personel.objects.create(ad_soyad="Ali KAYA", bolum=bil)
        v = Vekalet.objects.create(veren=a, vekil=b, gorev="Bölüm Başkanı", baslangic=timezone.localdate())
        servis.vekalet(v, self.su)
        alanlar = set(Bildirim.objects.values_list("kullanici_id", flat=True))
        self.assertIn(self.iiy.pk, alanlar)
        self.assertIn(bb.pk, alanlar)
        self.assertNotIn(eb.pk, alanlar)  # başka bölüm görmez
        self.assertIn("Ayşe YILMAZ → vekili Ali KAYA", Bildirim.objects.filter(kullanici=bb).get().metin)

    def test_olay_hatasi_islemi_bozmaz(self):
        with mock.patch.object(servis, "gonder", side_effect=RuntimeError("bozuk")), \
                self.assertLogs("bildirim.servis", "ERROR"):
            self.assertEqual(servis.nobet(mock.Mock(yil=2026, ay=1), self.su), 0)

    def test_durum_yeni_ve_sessiz(self):
        ilk = self._gonder(self.bolumcu)
        BildirimTercihi.objects.create(kullanici=self.bolumcu, tur="nobet", mod=BildirimTercihi.SESSIZ)
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("bildirim:durum")).json()
        self.assertEqual((r["okunmamis"], r["son"], r["yeni"]), (1, ilk.pk, []))
        r = self.client.get(reverse("bildirim:durum"), {"son": ilk.pk - 1}).json()
        self.assertEqual(len(r["yeni"]), 1)
        self.assertTrue(r["yeni"][0]["sessiz"])
        self.assertEqual(r["yeni"][0]["url"], reverse("bildirim:ac", args=[ilk.pk]))
        Bildirim.objects.filter(pk=ilk.pk).update(olusturma=timezone.now() - datetime.timedelta(hours=1))
        r = self.client.get(reverse("bildirim:durum"), {"son": ilk.pk - 1}).json()
        self.assertEqual(r["yeni"], [])  # eski bildirim pencere olmaz, yalnız zilde

    def test_ac_okundu_ve_yonlendirir(self):
        b = self._gonder(self.bolumcu)
        dis = self._gonder(self.bolumcu, url="https://ornek.com/")
        self.client.force_login(self.yok)
        self.assertEqual(self.client.get(reverse("bildirim:ac", args=[b.pk])).status_code, 404)
        self.client.force_login(self.bolumcu)
        self.assertRedirects(self.client.get(reverse("bildirim:ac", args=[b.pk])), "/nobet/", fetch_redirect_response=False)
        b.refresh_from_db()
        self.assertIsNotNone(b.okundu)
        self.assertRedirects(self.client.get(reverse("bildirim:ac", args=[dis.pk])), reverse("core:panel"),
                             fetch_redirect_response=False)
        self._gonder(self.bolumcu)
        self.assertEqual(self.client.post(reverse("bildirim:okundu")).json()["okunmamis"], 0)

    def test_liste_ayarlar_tercih(self):
        self._gonder(self.bolumcu)
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("bildirim:liste"))
        self.assertContains(r, "Başlık")
        self.assertContains(r, "Tümünü okundu say")
        r = self.client.get(reverse("bildirim:ayarlar"))
        self.assertContains(r, TURLER["nobet"].ad)
        self.assertNotContains(r, TURLER["yoklama_ozeti"].ad)  # alamayacağı tür listelenmez
        self.assertEqual(self.client.post(reverse("bildirim:tercih"), {"tur": "x", "mod": "sessiz"}).status_code, 404)
        self.client.post(reverse("bildirim:tercih"), {"tur": "nobet", "mod": "kapali"})
        self.assertEqual(BildirimTercihi.objects.get(kullanici=self.bolumcu).mod, "kapali")

    def test_zil_her_sayfada(self):
        self._gonder(self.bolumcu)
        self.client.force_login(self.bolumcu)
        r = self.client.get("/")
        self.assertContains(r, 'id="bildirimZili"')
        self.assertContains(r, '<span class="bildirim-rozet">1</span>', html=False)
        self.assertContains(r, "js/bildirim.js")


class YoklamaOzetiTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.iiy = User.objects.create_user("iiy", password="x-Parola-123")
        _yetki(cls.iiy, "personel-yoklamasi", Yetki.YONETIM)

    def setUp(self):
        servis._yapilanlar.clear()

    def _an(self, gun, saat, dakika=0):
        return timezone.make_aware(datetime.datetime(2026, 11, gun, saat, dakika))  # 9 Kasım 2026 pazartesi

    def test_sabah_ve_ogle_birer_kez(self):
        servis.zamanli_isler(self._an(9, 9, 0))
        self.assertFalse(Bildirim.objects.exists())
        servis.zamanli_isler(self._an(9, 9, 31))
        servis._yapilanlar.clear()
        servis.zamanli_isler(self._an(9, 9, 45))  # ikinci kez yazılmaz (veritabanı işareti)
        self.assertEqual(list(Bildirim.objects.values_list("baslik", flat=True)), ["Yoklama özeti · sabah"])
        servis.zamanli_isler(self._an(9, 14, 5))
        self.assertEqual(Bildirim.objects.count(), 2)
        self.assertIn("birim kesinleştirdi", Bildirim.objects.first().metin)

    def test_gec_acilista_yalniz_son_ozet_ve_hafta_sonu_yok(self):
        servis.zamanli_isler(self._an(9, 15))
        self.assertEqual(list(Bildirim.objects.values_list("baslik", flat=True)), ["Yoklama özeti · öğleden sonra"])
        servis.zamanli_isler(self._an(14, 10))  # cumartesi
        self.assertEqual(Bildirim.objects.count(), 1)

    def test_eski_bildirimler_temizlenir(self):
        b = Bildirim.objects.create(kullanici=self.iiy, tur="nobet", baslik="eski")
        Bildirim.objects.filter(pk=b.pk).update(olusturma=self._an(1, 8) - datetime.timedelta(days=40))
        servis.zamanli_isler(self._an(1, 8))
        self.assertFalse(Bildirim.objects.filter(pk=b.pk).exists())
        self.assertTrue(ZamanliIs.objects.filter(anahtar__startswith="temizlik").exists())
