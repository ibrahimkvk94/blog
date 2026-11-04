import datetime
import io
import shutil
import tempfile
import zipfile

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.models import Birim, Yetki
from personel.models import Bolum, Personel

from . import servis
from .models import GunlukOnay, IzinTuru, YoklamaGecmisi, YoklamaKaydi
from .servis import YoklamaHatasi

GUN = datetime.date(2026, 11, 10)
MEDYA = tempfile.mkdtemp(prefix="yoklama_test_")


def _png(renk=(200, 30, 30), boyut=(1200, 900)):
    from PIL import Image

    cikti = io.BytesIO()
    Image.new("RGB", boyut, renk).save(cikti, "PNG")
    return cikti.getvalue()


class SahteIstek:
    def __init__(self, user):
        self.user = user


@override_settings(MEDIA_ROOT=MEDYA)
class YoklamaTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        cls.tem = Bolum.objects.create(ad="Temel Bilimler", kod="TEM")
        cls.ali = Personel.objects.create(ad_soyad="Ali KAYA", bolum=cls.ask, sicil="2015-0412")
        cls.veli = Personel.objects.create(ad_soyad="Veli ÇELİK", bolum=cls.ask, sicil="2016-0001")
        cls.ayse = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=cls.tem, sicil="2017-0002")
        birim = Birim.objects.get(slug="personel-yoklamasi")
        cls.askci = User.objects.create_user("ask", password="x-Parola-123", bolum=cls.ask)
        Yetki.objects.create(kullanici=cls.askci, birim=birim, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        cls.iiy = User.objects.create_user("iiy", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.iiy, birim=birim, seviye=Yetki.YONETIM, kapsam=Yetki.TUM)
        cls.yetkisiz = User.objects.create_user("yok", password="x-Parola-123")
        cls.yillik = IzinTuru.objects.get(ad="Yıllık izin")
        cls.rapor = IzinTuru.objects.get(ad="Raporlu")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDYA, ignore_errors=True)

    def y(self, user):
        return servis.yetki(SahteIstek(user))

    def tam(self, bas, bit=None):
        return servis.aralik(True, bas, bit)

    # ---------------------------------------------------------------- iş kuralları

    def test_aralik_ve_metin(self):
        bas, bit = self.tam(GUN, GUN + datetime.timedelta(days=2))
        k = servis.ekle(self.askci, self.y(self.askci), self.ali, self.yillik, bas, bit)
        self.assertTrue(k.tam_gun)
        self.assertEqual(k.gun_sayisi, 3)
        self.assertEqual(k.aralik_metni, "10.11.2026 – 12.11.2026 (3 gün)")
        bas, bit = servis.aralik(False, GUN + datetime.timedelta(days=5), None, datetime.time(13), datetime.time(17, 30))
        k2 = servis.ekle(self.askci, self.y(self.askci), self.ali, self.rapor, bas, bit)
        self.assertFalse(k2.tam_gun)
        self.assertEqual(k2.aralik_metni, "15.11.2026 13:00–17:30")
        with self.assertRaises(YoklamaHatasi):
            servis.aralik(False, GUN, None, datetime.time(14), datetime.time(9))
        with self.assertRaises(YoklamaHatasi):
            servis.aralik(True, GUN, GUN - datetime.timedelta(days=1))

    def test_cakisma_reddedilir(self):
        y = self.y(self.askci)
        servis.ekle(self.askci, y, self.ali, self.yillik, *self.tam(GUN, GUN + datetime.timedelta(days=4)))
        with self.assertRaisesMessage(YoklamaHatasi, "Bu aralıkta zaten bir kayıt var"):
            servis.ekle(self.askci, y, self.ali, self.rapor,
                        *servis.aralik(False, GUN + datetime.timedelta(days=2), None, datetime.time(9), datetime.time(10)))
        # bitişik kayıt çakışma sayılmaz
        servis.ekle(self.askci, y, self.ali, self.rapor, *self.tam(GUN + datetime.timedelta(days=5)))
        self.assertEqual(YoklamaKaydi.objects.filter(personel=self.ali).count(), 2)

    def test_bolum_kapsami(self):
        with self.assertRaises(YoklamaHatasi):
            servis.ekle(self.askci, self.y(self.askci), self.ayse, self.yillik, *self.tam(GUN))
        servis.ekle(self.iiy, self.y(self.iiy), self.ayse, self.yillik, *self.tam(GUN))
        with self.assertRaises(YoklamaHatasi):  # kapalı tür seçilemez
            IzinTuru.objects.filter(pk=self.rapor.pk).update(aktif=False)
            self.rapor.refresh_from_db()
            servis.ekle(self.iiy, self.y(self.iiy), self.ali, self.rapor, *self.tam(GUN))

    def test_gun_durumu_ve_ozet(self):
        y = self.y(self.askci)
        servis.ekle(self.askci, y, self.ali, self.yillik, *self.tam(GUN - datetime.timedelta(days=1), GUN))
        servis.ekle(self.askci, y, self.veli, self.rapor, *servis.aralik(False, GUN, None, datetime.time(8), datetime.time(12)))
        durum = {d.personel.pk: d for d in servis.gun_durumu(GUN, [self.ali, self.veli, self.ayse])}
        self.assertTrue(durum[self.ali.pk].gun_boyu)
        self.assertTrue(durum[self.veli.pk].kismi)
        self.assertTrue(durum[self.ayse.pk].mevcut)
        o = servis.ozet(list(durum.values()))
        self.assertEqual((o["toplam"], o["mevcut"], o["gun_boyu"], o["kismi"]), (3, 1, 1, 1))
        ertesi = {d.personel.pk: d for d in servis.gun_durumu(GUN + datetime.timedelta(days=1), [self.ali, self.veli])}
        self.assertTrue(ertesi[self.ali.pk].mevcut)  # tam gün kaydı bitiş günü dahil, ertesi gün mevcut

    def test_iyimser_kilit(self):
        y = self.y(self.askci)
        k = servis.ekle(self.askci, y, self.ali, self.yillik, *self.tam(GUN))
        servis.duzenle(self.askci, y, k.pk, 1, self.rapor, *self.tam(GUN), "rapor geldi")
        with self.assertRaisesMessage(YoklamaHatasi, "başka bir kullanıcı"):
            servis.duzenle(self.iiy, self.y(self.iiy), k.pk, 1, self.yillik, *self.tam(GUN))  # eski sürümle
        k.refresh_from_db()
        self.assertEqual((k.tur, k.surum, k.aciklama), (self.rapor, 2, "rapor geldi"))

    def test_onay_ve_onay_sonrasi_degisiklik(self):
        y = self.y(self.askci)
        servis.onayla(self.askci, y, self.ask, GUN)
        o = GunlukOnay.objects.get(bolum=self.ask, tarih=GUN)
        self.assertIsNone(o.degisti)
        servis.ekle(self.askci, y, self.ali, self.yillik, *self.tam(GUN))
        o.refresh_from_db()
        self.assertIsNotNone(o.degisti)
        self.assertTrue(YoklamaGecmisi.objects.get(islem="ekle").onay_sonrasi)
        servis.onayla(self.askci, y, self.ask, GUN)  # yeniden verildi
        o.refresh_from_db()
        self.assertIsNone(o.degisti)
        with self.assertRaises(YoklamaHatasi):
            servis.onayla(self.askci, y, self.tem, GUN)  # başka bölüm

    # ---------------------------------------------------------------- ekranlar ve yetki

    def test_bolum_ekrani_ve_hizli_kayit(self):
        self.client.force_login(self.askci)
        url = reverse("yoklama:ana")
        r = self.client.get(url, {"tarih": GUN.isoformat()})
        self.assertContains(r, "Ali KAYA")
        self.assertNotContains(r, "Ayşe YILMAZ")
        self.assertContains(r, "Yoklamayı verdim")
        geri = f"{url}?tarih={GUN.isoformat()}"
        r = self.client.post(reverse("yoklama:kart", args=[self.ali.pk]), {
            "tur": self.yillik.pk, "bicim": "tam", "bas_tarih": GUN.isoformat(), "bit_tarih": GUN.isoformat(),
            "aciklama": "", "geri": geri})
        self.assertRedirects(r, geri, fetch_redirect_response=False)
        r = self.client.get(url, {"tarih": GUN.isoformat(), "durum": "gun_boyu"})
        self.assertContains(r, "Ali KAYA")
        self.assertNotContains(r, "Veli ÇELİK")
        self.client.post(reverse("yoklama:onay"), {"tarih": GUN.isoformat(), "geri": geri})
        self.assertContains(self.client.get(geri), "yoklama verildi")
        # başka bölümün kartı açılmaz, idari sayfalar kapalı
        self.assertEqual(self.client.get(reverse("yoklama:kart", args=[self.ayse.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("yoklama:turler")).status_code, 403)
        self.assertEqual(self.client.get(reverse("yoklama:toplu_fotograf")).status_code, 403)

    def test_idari_isler_ekrani_aralik_ve_rapor(self):
        servis.ekle(self.iiy, self.y(self.iiy), self.ayse, self.rapor, *self.tam(GUN, GUN + datetime.timedelta(days=1)))
        self.client.force_login(self.iiy)
        r = self.client.get(reverse("yoklama:ana"), {"tarih": GUN.isoformat()})
        self.assertContains(r, "Bölümlerin 10.11.2026 yoklaması")
        self.assertContains(r, "Verilmedi")
        r = self.client.get(reverse("yoklama:ana"), {"bas": GUN.isoformat(), "bit": (GUN + datetime.timedelta(days=6)).isoformat()})
        self.assertContains(r, "Ayşe YILMAZ")
        self.assertContains(r, ">RP<")
        r = self.client.get(reverse("yoklama:rapor"), {"bas": GUN.isoformat(), "bit": GUN.isoformat()})
        self.assertEqual(r["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(self.client.get(reverse("yoklama:kart", args=[self.ayse.pk])).status_code, 200)
        self.client.force_login(self.yetkisiz)
        self.assertEqual(self.client.get(reverse("yoklama:ana")).status_code, 403)

    def test_kayit_duzenle_ve_sil_ekrani(self):
        k = servis.ekle(self.askci, self.y(self.askci), self.ali, self.yillik, *self.tam(GUN))
        self.client.force_login(self.askci)
        url = reverse("yoklama:kayit", args=[k.pk])
        self.assertContains(self.client.get(url), "Değişikliği kaydet")
        self.client.post(url, {"islem": "kaydet", "surum": "1", "tur": self.rapor.pk, "bicim": "saat",
                               "bas_tarih": GUN.isoformat(), "bas_saat": "09:00", "bit_saat": "11:00", "aciklama": "x"})
        k.refresh_from_db()
        self.assertEqual((k.tur, k.yerel_bas.hour, k.yerel_bit.hour), (self.rapor, 9, 11))
        self.client.post(url, {"islem": "sil"})
        self.assertFalse(YoklamaKaydi.objects.filter(pk=k.pk).exists())
        self.assertEqual(list(YoklamaGecmisi.objects.values_list("islem", flat=True)), ["sil", "duzenle", "ekle"])

    def test_izin_turleri(self):
        self.client.force_login(self.iiy)
        url = reverse("yoklama:turler")
        self.client.post(url, {"ad": "Babalık izni", "kisa": "Bİ", "renk": "#0e7490", "sira": 25, "aktif": "on"})
        t = IzinTuru.objects.get(ad="Babalık izni")
        self.client.post(url, {"islem": "sil", "pk": t.pk})
        self.assertFalse(IzinTuru.objects.filter(pk=t.pk).exists())
        servis.ekle(self.iiy, self.y(self.iiy), self.ali, self.yillik, *self.tam(GUN))
        r = self.client.post(url, {"islem": "sil", "pk": self.yillik.pk}, follow=True)
        self.assertContains(r, "silinemez")
        self.assertTrue(IzinTuru.objects.filter(pk=self.yillik.pk).exists())

    def test_fotograf(self):
        self.client.force_login(self.askci)
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post(reverse("yoklama:fotograf_yukle", args=[self.ali.pk]),
                             {"fotograf": SimpleUploadedFile("a.png", _png(), "image/png")})
        self.ali.refresh_from_db()
        self.assertTrue(self.ali.fotograf.name.endswith(".jpg"))
        from PIL import Image

        with Image.open(self.ali.fotograf.path) as im:
            self.assertEqual(max(im.size), 600)
        r = self.client.get(reverse("yoklama:fotograf", args=[self.ali.pk]))
        self.assertEqual(r["Content-Type"], "image/jpeg")
        r = self.client.post(reverse("yoklama:fotograf_yukle", args=[self.ali.pk]),
                             {"fotograf": SimpleUploadedFile("a.png", b"resim degil", "image/png")}, follow=True)
        self.assertContains(r, "okunabilir bir resim değil")
        # başka bölüm fotoğrafı göremez
        self.client.force_login(User.objects.create_user("tem", password="x-Parola-123", bolum=self.tem))
        Yetki.objects.create(kullanici=User.objects.get(username="tem"), birim=Birim.objects.get(slug="personel-yoklamasi"),
                             seviye=Yetki.GORUNTULEME, kapsam=Yetki.BOLUM)
        self.assertEqual(self.client.get(reverse("yoklama:fotograf", args=[self.ali.pk])).status_code, 404)

    def test_toplu_fotograf(self):
        arsiv = io.BytesIO()
        with zipfile.ZipFile(arsiv, "w") as z:
            z.writestr("2015-0412.png", _png())
            z.writestr("klasor/2017 0002.jpg", _png((0, 0, 200)))
            z.writestr("9999.jpg", _png())
            z.writestr("2016-0001.jpg", b"bozuk")
        arsiv.seek(0)
        arsiv.name = "foto.zip"
        self.client.force_login(self.iiy)
        r = self.client.post(reverse("yoklama:toplu_fotograf"), {"dosya": arsiv})
        self.assertContains(r, "2 yüklendi")
        self.assertContains(r, "9999.jpg")
        self.assertContains(r, "1 hatalı")
        self.ayse.refresh_from_db()
        self.assertTrue(self.ayse.fotograf)

    def test_ana_sayfa_karti(self):
        self.client.force_login(self.askci)
        self.assertContains(self.client.get(reverse("core:panel")), "Bugünün personel yoklaması verilmedi")
        servis.onayla(self.askci, self.y(self.askci), self.ask, timezone.localdate())
        self.assertNotContains(self.client.get(reverse("core:panel")), "Bugünün personel yoklaması verilmedi")
        self.client.force_login(self.iiy)
        self.assertContains(self.client.get(reverse("core:panel")), "Yoklama vermeyen bölüm")
