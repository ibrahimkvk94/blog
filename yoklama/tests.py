import datetime
import io
import shutil
import tempfile
import zipfile
from unittest import mock

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


def _an(tarih, saat=8, dakika=0):
    return timezone.make_aware(datetime.datetime.combine(tarih, datetime.time(saat, dakika)))


class SaatSabit:
    """Kilit kuralları saate bağlı: testlerde "şimdi" GUN 08:00 (bölüm o güne de girebilir)."""

    def setUp(self):
        super().setUp()
        self.saat_ayarla(GUN, 8)

    def saat_ayarla(self, tarih, saat, dakika=0):
        yama = mock.patch.object(servis, "_simdi", return_value=timezone.localtime(_an(tarih, saat, dakika)))
        yama.start()  # sonraki çağrı öncekinin üstüne biner; hepsi test sonunda ters sırayla kalkar
        self.addCleanup(yama.stop)


class SahteIstek:
    def __init__(self, user):
        self.user = user


@override_settings(MEDIA_ROOT=MEDYA)
class YoklamaTestleri(SaatSabit, TestCase):
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

    def birim(self, bolum):
        from personel.models import TeskilatBirimi

        return TeskilatBirimi.objects.get(bolum=bolum)

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
        servis.ekle(self.iiy, self.y(self.iiy), self.ali, self.yillik, *self.tam(GUN - datetime.timedelta(days=1), GUN))
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
        servis.onayla(self.askci, y, self.birim(self.ask), GUN)
        o = GunlukOnay.objects.get(birim=self.birim(self.ask), tarih=GUN)
        self.assertIsNone(o.degisti)
        with self.assertRaisesMessage(YoklamaHatasi, "kesinleşti"):  # kesinleşen güne bölüm giremez
            servis.ekle(self.askci, y, self.ali, self.yillik, *self.tam(GUN))
        servis.ekle(self.iiy, self.y(self.iiy), self.ali, self.yillik, *self.tam(GUN))  # idari işler girebilir
        o.refresh_from_db()
        self.assertIsNotNone(o.degisti)
        self.assertTrue(YoklamaGecmisi.objects.get(islem="ekle").onay_sonrasi)
        servis.onayla(self.askci, y, self.birim(self.ask), GUN)  # yeniden verildi
        o.refresh_from_db()
        self.assertIsNone(o.degisti)
        with self.assertRaises(YoklamaHatasi):
            servis.onayla(self.askci, y, self.birim(self.tem), GUN)  # başka bölüm

    def test_zaman_ve_kesinlesme_kilitleri(self):
        y, iiy = self.y(self.askci), self.y(self.iiy)
        yarin, ertesi = GUN + datetime.timedelta(days=1), GUN + datetime.timedelta(days=2)
        # 08:00: bugüne girilir, geçmişe girilemez
        k = servis.ekle(self.askci, y, self.ali, self.yillik, *self.tam(GUN))
        with self.assertRaisesMessage(YoklamaHatasi, "Geçmiş günlerin"):
            servis.ekle(self.askci, y, self.veli, self.rapor, *self.tam(GUN - datetime.timedelta(days=1)))
        self.assertEqual(servis.ilk_giris_tarihi(), GUN)
        # 09:00'dan sonra bugüne değen kayıt eklenemez, değiştirilemez, silinemez; yarından başlayan girilir
        self.saat_ayarla(GUN, 9, 0)
        self.assertEqual(servis.ilk_giris_tarihi(), yarin)
        for islem in (lambda: servis.ekle(self.askci, y, self.veli, self.rapor, *servis.aralik(False, GUN, None, datetime.time(14), datetime.time(16))),
                      lambda: servis.duzenle(self.askci, y, k.pk, 1, self.rapor, *self.tam(GUN)),
                      lambda: servis.sil(self.askci, y, k.pk)):
            with self.assertRaisesMessage(YoklamaHatasi, "09:00"):
                islem()
        with self.assertRaisesMessage(YoklamaHatasi, "09:00"):  # bugünü kapsayan yeni aralığa taşıma da olmaz
            servis.ekle(self.askci, y, self.veli, self.rapor, *self.tam(GUN, yarin))
        servis.ekle(self.askci, y, self.veli, self.rapor, *self.tam(yarin))
        servis.duzenle(self.iiy, iiy, k.pk, 1, self.rapor, *self.tam(GUN), "idari düzeltme")  # idari işler serbest
        # kesinleşen gün: bölüm o güne değen kayda dokunamaz, sonraki güne girebilir
        servis.onayla(self.askci, y, self.birim(self.ask), yarin)
        with self.assertRaisesMessage(YoklamaHatasi, "kesinleşti"):
            servis.ekle(self.askci, y, self.ali, self.yillik, *self.tam(yarin, ertesi))
        servis.ekle(self.askci, y, self.ali, self.yillik, *self.tam(ertesi))
        # ekranlar: kilitli kayıtta düzenleme formu yerine açıklama, günlük listede ekleme düğmesi yok
        self.client.force_login(self.askci)
        r = self.client.get(reverse("yoklama:kayit", args=[k.pk]))
        self.assertContains(r, "yalnız idari işler yetkilisi")
        self.assertNotContains(r, "Değişikliği kaydet")
        r = self.client.get(reverse("yoklama:ana"), {"tarih": GUN.isoformat()})
        self.assertNotContains(r, 'data-bs-target="#ykEkle"')
        r = self.client.get(reverse("yoklama:ana"), {"tarih": ertesi.isoformat()})
        self.assertContains(r, 'data-bs-target="#ykEkle"')
        self.client.force_login(self.iiy)
        self.assertContains(self.client.get(reverse("yoklama:kayit", args=[k.pk])), "Değişikliği kaydet")

    # ---------------------------------------------------------------- ekranlar ve yetki

    def test_bolum_ekrani_ve_hizli_kayit(self):
        self.client.force_login(self.askci)
        url = reverse("yoklama:ana")
        r = self.client.get(url, {"tarih": GUN.isoformat()})
        self.assertContains(r, "Ali KAYA")
        self.assertNotContains(r, "Ayşe YILMAZ")
        self.assertContains(r, "Yoklamayı kesinleştir")
        geri = f"{url}?tarih={GUN.isoformat()}"
        r = self.client.post(reverse("yoklama:kart", args=[self.ali.pk]), {
            "tur": self.yillik.pk, "bicim": "tam", "bas_tarih": GUN.isoformat(), "bit_tarih": GUN.isoformat(),
            "aciklama": "", "geri": geri})
        self.assertRedirects(r, geri, fetch_redirect_response=False)
        r = self.client.get(url, {"tarih": GUN.isoformat(), "durum": "gun_boyu"})
        self.assertContains(r, "Ali KAYA")
        self.assertNotContains(r, "Veli ÇELİK")
        self.client.post(reverse("yoklama:onay"), {"tarih": GUN.isoformat(), "geri": geri})
        self.assertContains(self.client.get(geri), "yoklama kesinleşti")
        # başka bölümün kartı açılmaz, idari sayfalar kapalı
        self.assertEqual(self.client.get(reverse("yoklama:kart", args=[self.ayse.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("yoklama:turler")).status_code, 403)
        self.assertEqual(self.client.get(reverse("yoklama:toplu_fotograf")).status_code, 403)

    def test_idari_isler_ekrani_aralik_ve_rapor(self):
        servis.ekle(self.iiy, self.y(self.iiy), self.ayse, self.rapor, *self.tam(GUN, GUN + datetime.timedelta(days=1)))
        self.client.force_login(self.iiy)
        r = self.client.get(reverse("yoklama:ana"), {"tarih": GUN.isoformat()})
        self.assertContains(r, "tüm okul")          # genel görünüm: birim kutucukları, karışık kişi listesi yok
        self.assertContains(r, "Kesinleşmedi")
        self.assertNotContains(r, "Veli ÇELİK")
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
        from django.core.files.uploadedfile import SimpleUploadedFile

        # bölüm hesabı fotoğraf yükleyemez; yalnız yönetim yetkisi (idari işler yetkilisi, sistem yöneticisi)
        self.client.force_login(self.askci)
        r = self.client.post(reverse("yoklama:fotograf_yukle", args=[self.ali.pk]),
                             {"fotograf": SimpleUploadedFile("a.png", _png(), "image/png")})
        self.assertEqual(r.status_code, 403)
        self.assertNotContains(self.client.get(reverse("yoklama:kart", args=[self.ali.pk])), "fotoFormu")
        self.client.force_login(self.iiy)
        self.assertContains(self.client.get(reverse("yoklama:kart", args=[self.ali.pk])), "fotoFormu")
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

    def test_kart_isaretleri(self):
        from personel.models import Secenek

        from .isaretler import personel_isaretleri

        sec = lambda tur, metin: Secenek.objects.create(tur=tur, metin=metin)
        self.ali.rutbe, self.ali.sinif = sec(Secenek.RUTBE, "Ütğm."), sec(Secenek.SINIF, "Öğ.")
        self.ali.unvan = sec(Secenek.UNVAN, "Doç.Dr.")
        self.ali.save()
        self.assertEqual([e for _, e in personel_isaretleri(self.ali)], ["Üsteğmen", "Öğretmen", "Doçent"])
        self.veli.rutbe = sec(Secenek.RUTBE, "Asb.Kd.Bçvş.")
        self.veli.save()
        self.assertEqual([e for _, e in personel_isaretleri(self.veli)], ["Astsubay Kd. Başçavuş"])
        self.assertEqual(personel_isaretleri(self.ayse), [])  # künyesiz: işaret yok
        self.client.force_login(self.askci)
        r = self.client.get(reverse("yoklama:kart", args=[self.ali.pk]))
        self.assertContains(r, "yk-isaretler")
        self.assertContains(r, "Doçent")

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
        self.assertContains(self.client.get(reverse("core:panel")), "Bugünün personel yoklaması kesinleştirilmedi")
        servis.onayla(self.askci, self.y(self.askci), self.birim(self.ask), timezone.localdate())
        self.assertNotContains(self.client.get(reverse("core:panel")), "Bugünün personel yoklaması kesinleştirilmedi")
        self.client.force_login(self.iiy)
        self.assertContains(self.client.get(reverse("core:panel")), "Yoklamayı kesinleştirmeyen birim")


@override_settings(MEDIA_ROOT=MEDYA)
class YoklamaFormuTestleri(SaatSabit, TestCase):
    """Günlük yoklama formu (resmî biçim): gruplar, sayım, beyan, Excel, yetki."""

    @classmethod
    def setUpTestData(cls):
        from personel.models import Secenek

        R, S, U = Secenek.RUTBE, Secenek.SINIF, Secenek.UNVAN
        sec = lambda tur, metin, sira=0: Secenek.objects.create(tur=tur, metin=metin, sira=sira)
        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        cls.tem = Bolum.objects.create(ad="Temel Bilimler", kod="TEM")
        utgm, alb, bcvs, tugg = sec(R, "Ütğm.", 9), sec(R, "Alb.", 14), sec(R, "Asb.Kd.Bçvş.", 6), sec(R, "Tuğg.", 15)
        og, topcu = sec(S, "Öğ."), sec(S, "Topçu")
        ogtgor = sec(U, "Öğt.Gör.")
        P = Personel.objects.create
        cls.oe_subay = P(ad_soyad="Ali KAYA", bolum=cls.ask, sinif=og, rutbe=utgm)
        cls.oe_alb = P(ad_soyad="Can DEMİR", bolum=cls.ask, sinif=og, rutbe=alb)
        cls.oe_asb = P(ad_soyad="Veli ÇELİK", bolum=cls.ask, sinif=topcu, rutbe=bcvs)
        cls.oe_sivil = P(ad_soyad="Ayşe YILMAZ", bolum=cls.tem, unvan=ogtgor)
        cls.subay = P(ad_soyad="Mert ARSLAN", sinif=topcu, rutbe=utgm)
        cls.asb = P(ad_soyad="Eren KOÇ", rutbe=bcvs)
        cls.memur = P(ad_soyad="Elif ŞAHİN")
        cls.general = P(ad_soyad="Kemal ÖZ", rutbe=tugg)
        birim = Birim.objects.get(slug="personel-yoklamasi")
        cls.askci = User.objects.create_user("ask", password="x-Parola-123", bolum=cls.ask)
        Yetki.objects.create(kullanici=cls.askci, birim=birim, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        cls.iiy = User.objects.create_user("iiy", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.iiy, birim=birim, seviye=Yetki.YONETIM, kapsam=Yetki.TUM)
        cls.yillik = IzinTuru.objects.get(ad="Yıllık izin")
        cls.rapor = IzinTuru.objects.get(ad="Raporlu")

    def y(self, user):
        return servis.yetki(SahteIstek(user))

    def birim(self, bolum):
        from personel.models import TeskilatBirimi

        return TeskilatBirimi.objects.get(bolum=bolum)

    def test_otomatik_gruplar(self):
        from . import form
        from .models import PersonelGrubu as G

        beklenen = {self.oe_subay: G.OE_SUBAY, self.oe_alb: G.OE_SUBAY, self.oe_asb: G.OE_ASTSUBAY,
                    self.oe_sivil: G.OE_SIVIL, self.subay: G.SUBAY, self.asb: G.ASTSUBAY,
                    self.memur: G.SIVIL_MEMUR, self.general: G.GENERAL}
        for p, g in beklenen.items():
            self.assertEqual(form.otomatik_grup(p), g, p.ad_soyad)
        self.assertEqual(form.otomatik_gorev(self.oe_subay, G.OE_SUBAY), "Öğretim Elemanı (ASK)")

    def test_sayim_ve_beyan(self):
        from . import form

        iiy = self.y(self.iiy)
        servis.ekle(self.iiy, iiy, self.oe_subay, self.yillik, *servis.aralik(True, GUN, GUN + datetime.timedelta(days=2)))
        servis.ekle(self.iiy, iiy, self.oe_alb, self.rapor, *servis.aralik(True, GUN))
        servis.ekle(self.iiy, iiy, self.memur, self.rapor, *servis.aralik(False, GUN, None, datetime.time(13), datetime.time(15)))
        f = form.gunluk(GUN, list(servis.personeller(iiy)))
        genel, gayri, hazir = (s["degerler"] for s in f["sayim"])
        # sütunlar: general, öe sivil, öe subay, öe astsubay, subay, astsubay, sivil memur, toplam
        self.assertEqual(genel, [1, 1, 2, 1, 1, 1, 1, 8])
        self.assertEqual(gayri, [0, 0, 2, 0, 0, 0, 0, 2])   # saatlik izin gayri mevcut sayılmaz
        self.assertEqual(hazir, [1, 1, 0, 1, 1, 1, 1, 6])
        self.assertEqual([b["personel"] for b in f["beyan"]], [self.oe_alb, self.oe_subay])  # kıdem sırası
        b = f["beyan"][1]
        self.assertEqual((b["sebep"], b["ayrilis"], b["katilis"]), ("Yıllık izin", "10.11.2026", "13.11.2026"))
        self.assertEqual(len(f["saatlik"]), 1)
        self.assertIn("PERSONEL YOKLAMASI (GÜNLÜK)", f["baslik"])
        self.assertIn("MÜDÜRLÜĞÜ", f["baslik"])

    def test_elle_grup_ve_gorev(self):
        from . import form
        from .models import PersonelGrubu

        self.client.force_login(self.iiy)
        r = self.client.get(reverse("yoklama:gruplar"))
        self.assertEqual(r.status_code, 200)
        veri = {f"grup-{p.pk}": form.otomatik_grup(p) for p in Personel.objects.all()}
        veri[f"grup-{self.subay.pk}"] = PersonelGrubu.OE_SUBAY
        veri[f"gorev-{self.memur.pk}"] = "Müdürlük Sekreteri"
        self.client.post(reverse("yoklama:gruplar"), veri)
        self.assertEqual(PersonelGrubu.objects.count(), 2)
        self.assertEqual(form.grup_ve_gorev(self.subay, PersonelGrubu.objects.get(personel=self.subay))[0],
                         PersonelGrubu.OE_SUBAY)
        # otomatiğe geri alınca atama silinir; formda olmayan kişiye dokunulmaz
        veri[f"grup-{self.subay.pk}"] = PersonelGrubu.SUBAY
        veri.pop(f"grup-{self.memur.pk}")
        veri.pop(f"gorev-{self.memur.pk}")
        self.client.post(reverse("yoklama:gruplar"), veri)
        self.assertEqual(list(PersonelGrubu.objects.values_list("personel", flat=True)), [self.memur.pk])

    def test_ekran_excel_ve_yetki(self):
        from openpyxl import load_workbook

        servis.ekle(self.iiy, self.y(self.iiy), self.oe_sivil, self.yillik, *servis.aralik(True, GUN))
        servis.ekle(self.iiy, self.y(self.iiy), self.oe_subay, self.rapor, *servis.aralik(True, GUN))
        self.client.force_login(self.iiy)
        r = self.client.get(reverse("yoklama:form"), {"tarih": GUN.isoformat()})
        self.assertContains(r, "GAYRİ MEVCUT BEYANI")
        self.assertContains(r, "Ayşe YILMAZ")
        r = self.client.get(reverse("yoklama:form"), {"tarih": GUN.isoformat(), "bit": "2026-11-12", "excel": "1"})
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ["10.11.2026", "11.11.2026", "12.11.2026"])
        ws = wb["10.11.2026"]
        self.assertEqual(ws["I2"].value, "10.11.2026")
        self.assertEqual([ws.cell(row=r_, column=10).value for r_ in (5, 6, 7)], [8, 2, 6])
        self.assertIn("Ayşe YILMAZ", ws["C11"].value)   # sütun sırası: öğretim elemanı (sivil) önce
        self.assertIn("Ali KAYA", ws["C12"].value)
        self.assertEqual((ws["E12"].value, ws["G12"].value), ("Öğretim Elemanı (ASK)", "Raporlu"))
        self.assertEqual(ws["B30"].value, 20)  # en az 20 beyan satırı (boş form gibi)
        # bölüm hesabı: yalnız kendi bölümü, grupları düzenleyemez
        self.client.force_login(self.askci)
        r = self.client.get(reverse("yoklama:form"), {"tarih": GUN.isoformat(), "bolum": self.tem.pk})
        self.assertNotContains(r, "Ayşe YILMAZ")
        self.assertContains(r, "ASKERİ BİLİMLER BÖLÜMÜ")
        self.assertEqual(r.context["f"]["sayim"][0]["degerler"][-1], 3)
        self.assertEqual(self.client.get(reverse("yoklama:gruplar")).status_code, 403)


@override_settings(MEDIA_ROOT=MEDYA)
class BirimKapsamiTestleri(SaatSabit, TestCase):
    """Teşkilat birimleri: herkes kendi birimini ve alt birimlerini görür; tüm okulu yalnız yönetim görür."""

    @classmethod
    def setUpTestData(cls):
        from personel.models import TeskilatBirimi as T

        cls.kok = T.objects.create(ad="Müdürlük", tur=T.MUDURLUK)
        cls.sube = T.objects.create(ad="İdari İşler Şube Müdürlüğü", tur=T.SUBE, ust=cls.kok)
        cls.kisim = T.objects.create(ad="Personel Kısmı", tur=T.KISIM, ust=cls.sube)
        cls.diger = T.objects.create(ad="Evrak Kayıt Kısmı", tur=T.KISIM, ust=cls.sube)
        cls.bas = T.objects.create(ad="Bölüm Başkanlıkları", tur=T.BASKANLIKLAR, ust=cls.kok)
        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")  # birimi kendiliğinden açılır
        T.objects.filter(bolum=cls.ask).update(ust=cls.bas)
        cls.sube_p = Personel.objects.create(ad_soyad="Ali KAYA", teskilat_birimi=cls.sube)
        cls.kisim_p = Personel.objects.create(ad_soyad="Veli ÇELİK", teskilat_birimi=cls.kisim)
        cls.diger_p = Personel.objects.create(ad_soyad="Can DEMİR", teskilat_birimi=cls.diger)
        cls.ask_p = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=cls.ask)
        birim = Birim.objects.get(slug="personel-yoklamasi")

        def hesap(ad, **k):
            u = User.objects.create_user(ad, password="x-Parola-123", **k)
            Yetki.objects.create(kullanici=u, birim=birim, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
            return u
        cls.subeci = hesap("sube", teskilat_birimi=cls.sube)
        cls.kisimci = hesap("kisim", teskilat_birimi=cls.kisim)
        cls.askci = hesap("ask", bolum=cls.ask)
        cls.iiy = User.objects.create_user("iiy", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.iiy, birim=birim, seviye=Yetki.YONETIM, kapsam=Yetki.TUM)
        cls.yillik = IzinTuru.objects.get(ad="Yıllık izin")

    def y(self, user):
        return servis.yetki(SahteIstek(user))

    def test_ust_birim_alt_birimi_gorur_baskasini_goremez(self):
        isim = lambda u: {p.ad_soyad for p in servis.personeller(self.y(u))}
        self.assertEqual(isim(self.subeci), {"Ali KAYA", "Veli ÇELİK", "Can DEMİR"})   # şube + kısımları
        self.assertEqual(isim(self.kisimci), {"Veli ÇELİK"})
        self.assertEqual(isim(self.askci), {"Ayşe YILMAZ"})
        self.assertEqual(len(isim(self.iiy)), 4)                                       # tüm okul
        # kısım hesabı şubenin ya da başka kısmın kartını, raporunu, formunu açamaz
        self.client.force_login(self.kisimci)
        self.assertEqual(self.client.get(reverse("yoklama:kart", args=[self.sube_p.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("yoklama:kart", args=[self.diger_p.pk])).status_code, 404)
        r = self.client.get(reverse("yoklama:form"), {"tarih": GUN.isoformat(), "birim": self.sube.pk})
        self.assertContains(r, "PERSONEL KISMI")       # başka birim istense de kendi birimi
        self.assertNotContains(r, "Ali KAYA")
        r = self.client.get(reverse("yoklama:ana"), {"tarih": GUN.isoformat(), "birim": self.diger.pk})
        self.assertContains(r, "Veli ÇELİK")
        self.assertNotContains(r, "Can DEMİR")
        with self.assertRaises(YoklamaHatasi):
            servis.onayla(self.kisimci, self.y(self.kisimci), self.sube, GUN)
        # şube hesabı kısmını açar ve kısmın yoklamasını kesinleştirebilir
        self.client.force_login(self.subeci)
        r = self.client.get(reverse("yoklama:ana"), {"tarih": GUN.isoformat()})
        self.assertContains(r, "Personel Kısmı")       # alt birim kutucuğu
        self.assertContains(r, "Ali KAYA")
        self.assertNotContains(r, "Ayşe YILMAZ")
        servis.onayla(self.subeci, self.y(self.subeci), self.kisim, GUN)

    def test_genel_gorunum_ve_kayittan_sonra_donus(self):
        self.client.force_login(self.iiy)
        r = self.client.get(reverse("yoklama:ana"), {"tarih": GUN.isoformat()})
        self.assertTemplateUsed(r, "yoklama/gun_genel.html")
        self.assertContains(r, "İdari İşler Şube Müdürlüğü")
        self.assertContains(r, "Bölüm Başkanlıkları")
        self.assertNotContains(r, "Veli ÇELİK")        # kişi listesi yok, yalnız birimler
        self.assertContains(self.client.get(reverse("yoklama:ana"), {"tarih": GUN.isoformat(), "q": "veli"}), "Veli ÇELİK")
        # kayıttan sonra geldiği listeye döner
        liste = f"{reverse('yoklama:ana')}?tarih={GUN.isoformat()}&birim={self.kisim.pk}"
        r = self.client.post(reverse("yoklama:kart", args=[self.kisim_p.pk]), {
            "tur": self.yillik.pk, "bicim": "tam", "bas_tarih": GUN.isoformat(), "bit_tarih": GUN.isoformat(),
            "aciklama": "", "geri": liste})
        self.assertRedirects(r, liste, fetch_redirect_response=False)
        # dönüş adresi yoksa personelin birim sayfasına
        r = self.client.post(reverse("yoklama:kart", args=[self.ask_p.pk]), {
            "tur": self.yillik.pk, "bicim": "tam", "bas_tarih": GUN.isoformat(), "bit_tarih": GUN.isoformat()})
        from personel.models import TeskilatBirimi
        self.assertRedirects(r, f"{reverse('yoklama:ana')}?tarih={GUN.isoformat()}&birim="
                                f"{TeskilatBirimi.objects.get(bolum=self.ask).pk}", fetch_redirect_response=False)
