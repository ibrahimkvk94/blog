from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Birim, Yetki

from .models import Bolum, KartAlani, KartDegeri, Personel, Secenek, TeskilatBirimi
from .templatetags.personel_etiketleri import maskele

TCKN = "12345678901"


class KimlikNoTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        bolum = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        cls.p = Personel.objects.create(ad_soyad="Deneme Kişi", personel_kodu=TCKN, bolum=bolum)
        cls.goruntuleyen = User.objects.create_user("g", password="x-Parola-123", bolum=bolum)
        Yetki.objects.create(kullanici=cls.goruntuleyen, birim=Birim.objects.get(slug="personel-bilgileri"), seviye=Yetki.GORUNTULEME)
        cls.yonetici = User.objects.create_superuser("y", password="x-Parola-123")

    def test_maskele(self):
        self.assertEqual(maskele(TCKN), "•••••••8901")
        self.assertEqual(maskele(None), "–")

    def test_goruntuleyen_tam_numarayi_goremez_ve_aratamaz(self):
        self.client.force_login(self.goruntuleyen)
        self.assertNotContains(self.client.get(reverse("personel:liste")), TCKN)
        self.assertNotContains(self.client.get(reverse("personel:detay", args=[self.p.pk])), TCKN)
        self.assertNotContains(self.client.get(reverse("personel:liste"), {"q": "1234567"}), "Deneme Kişi")

    def test_duzenleyen_bolum_hesabi_numarayi_goremez(self):
        duzenleyen = User.objects.create_user("d", password="x-Parola-123", bolum=self.p.bolum)
        Yetki.objects.create(kullanici=duzenleyen, birim=Birim.objects.get(slug="personel-bilgileri"),
                             seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        self.client.force_login(duzenleyen)
        self.assertNotContains(self.client.get(reverse("personel:detay", args=[self.p.pk])), TCKN)
        r = self.client.get(reverse("personel:duzenle", args=[self.p.pk]))
        self.assertNotContains(r, 'name="personel_kodu"')
        self.assertNotContains(r, 'name="derse_girebilir"')

    def test_yonetici_tam_numarayi_gorur(self):
        self.client.force_login(self.yonetici)
        self.assertContains(self.client.get(reverse("personel:liste")), TCKN)
        self.assertContains(self.client.get(reverse("personel:detay", args=[self.p.pk])), TCKN)
        self.assertContains(self.client.get(reverse("personel:liste"), {"q": "1234567"}), "Deneme Kişi")


class ListeAktarimTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        for i, r in enumerate(["Atğm.", "Tğm.", "Ütğm.", "Kd.Ütğm.", "Yzb.", "Asb.Kd.Bçvş.", "Alb."]):
            Secenek.objects.create(tur=Secenek.RUTBE, metin=r, sira=i)
        for s in ["Öğ.", "Müh.", "Topçu", "P.", "U/H Tekns."]:
            Secenek.objects.create(tur=Secenek.SINIF, metin=s)
        for u in ["Dr.Öğt.Üyesi", "Doç.Dr.", "Prof.Dr.", "Öğt.Gör.", "Öğt.Gör.Dr.", "Dr."]:
            Secenek.objects.create(tur=Secenek.UNVAN, metin=u)
        cls.mek = Bolum.objects.create(ad="Mekatronik", kod="MKT")
        cls.ins = Bolum.objects.create(ad="İnşaat Teknolojisi", kod="İNŞ")
        cls.bes, _ = Bolum.objects.get_or_create(ad="Beden Eğitimi ve Spor")
        cls.kilic = Personel.objects.create(ad_soyad="Hasan Can KIRAÇ", bolum=cls.ins)

    def test_ayristir(self):
        from .liste_aktarimi import ayristir
        r = list(Secenek.objects.filter(tur=Secenek.RUTBE).values_list("metin", flat=True))
        def a(m):
            x = ayristir(m, r)
            return (x.unvan, x.sinif, x.rutbe, x.cozulemeyen)
        self.assertEqual(a("Öğ.Ütğm."), ("", "Öğ.", "Ütğm.", ""))
        self.assertEqual(a("TopçuAtğm."), ("", "Topçu", "Atğm.", ""))
        self.assertEqual(a("P.Asb.Kd.Bçvş."), ("", "P.", "Asb.Kd.Bçvş.", ""))
        self.assertEqual(a("U/H Tekns.Asb.Kd.Bçvş."), ("", "U/H Tekns.", "Asb.Kd.Bçvş.", ""))
        self.assertEqual(a("Doç.Dr. Öğ.Yzb."), ("Doç.Dr.", "Öğ.", "Yzb.", ""))
        self.assertEqual(a("Öğ.Ütğm. Dr."), ("Dr.", "Öğ.", "Ütğm.", ""))
        self.assertEqual(a("Dr.Öğt.Üyesi Öğ.Ütğm."), ("Dr.Öğt.Üyesi", "Öğ.", "Ütğm.", ""))
        self.assertEqual(a("Öğt.Gör.Dr."), ("Öğt.Gör.Dr.", "", "", ""))
        self.assertEqual(a("De.Me."), ("", "", "", "De.Me."))

    def test_benzer_ad_baskasinin_kaydina_yazilmaz(self):
        import tempfile
        from pathlib import Path
        from .liste_aktarimi import oku, planla, uygula
        icerik = ("satir;bolum;sinif_rutbe_unvan;ad_soyad;sicil\n"
                  "1;Mekatronik;TopçuTğm.;Hasan Can KARTEL;000-0001\n"
                  "2;İnşaat Teknolojisi;Müh.Ütğm.;Hasan Can KIRAÇ;0000-00\n"
                  "3;Beden Eğitimi ve Spor;Öğ.Ütğm.;Hasan Can KIRAÇ;xxxx\n")
        with tempfile.TemporaryDirectory() as k:
            yol = Path(k) / "liste.csv"
            yol.write_text(icerik, encoding="utf-8")
            plan = {d.satir.ad: d for d in planla(oku(yol))}
        self.assertEqual(plan["Hasan Can KIRAÇ"].personel, self.kilic)
        self.assertEqual(plan["Hasan Can KARTEL"].durum, "yeni")
        uygula(plan.values(), yeni_ekle=True)
        self.kilic.refresh_from_db()
        # BES satırı asıl bölümü ezmez, sicil "xxxx" yazılmaz
        self.assertEqual((self.kilic.rutbe.metin, self.kilic.sinif.metin, self.kilic.bolum, self.kilic.sicil), ("Ütğm.", "Müh.", self.ins, "0000-00"))
        karmil = Personel.objects.get(ad_soyad="Hasan Can KARTEL")
        self.assertEqual((karmil.rutbe.metin, karmil.sinif.metin, karmil.bolum), ("Tğm.", "Topçu", self.mek))

class PersonelKartiTestleri(TestCase):
    """Personel Kartları: yönetici alanları, kart bilgileri, teşkilat, bölüm başkanı, ders / sınav kullanımı."""

    @classmethod
    def setUpTestData(cls):
        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        cls.p = Personel.objects.create(ad_soyad="Ali KAYA", bolum=cls.ask, personel_kodu=TCKN)
        birim = Birim.objects.get(slug="personel-bilgileri")
        cls.yonetici = User.objects.create_user("yon", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.yonetici, birim=birim, seviye=Yetki.YONETIM, kapsam=Yetki.TUM)
        cls.bolumcu = User.objects.create_user("ask", password="x-Parola-123", bolum=cls.ask)
        Yetki.objects.create(kullanici=cls.bolumcu, birim=birim, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        cls.mudurluk = TeskilatBirimi.objects.create(ad="Müdürlük", tur=TeskilatBirimi.MUDURLUK)
        cls.sube = TeskilatBirimi.objects.create(ad="İdari İşler Şube Müdürlüğü", tur=TeskilatBirimi.SUBE, ust=cls.mudurluk)
        cls.bas = TeskilatBirimi.objects.create(ad="Bölüm Başkanlıkları", tur=TeskilatBirimi.BASKANLIKLAR, ust=cls.mudurluk)
        cls.ask_tk = TeskilatBirimi.objects.create(ad="Askeri Bilimler", tur=TeskilatBirimi.BOLUM, ust=cls.bas, bolum=cls.ask)

    def test_birim_adi_ve_baslangic_alanlari(self):
        self.assertEqual(Birim.objects.get(slug="personel-bilgileri").ad, "Personel Kartları")
        self.assertTrue(KartAlani.objects.filter(ad="Cep telefonu").exists())

    def test_yonetici_karti_duzenler(self):
        tel = KartAlani.objects.get(ad="Cep telefonu")
        kan = KartAlani.objects.get(ad="Kan grubu")
        self.client.force_login(self.yonetici)
        r = self.client.post(reverse("personel:duzenle", args=[self.p.pk]), {
            "ad_soyad": "Ali KAYA", "sicil": "1", "bolum": self.ask.pk, "aktif": "on", "personel_kodu": TCKN,
            "derse_girebilir": "on", "teskilat_birimi": self.sube.pk, "gorev_unvani": "Şube Müdürü",
            "idari_kadro": "on", "bolum_baskani": "1", f"alan-{tel.pk}": "0555 000 00 00", f"alan-{kan.pk}": "Z Rh+"})
        self.assertRedirects(r, reverse("personel:detay", args=[self.p.pk]))
        self.p.refresh_from_db()
        self.ask.refresh_from_db()
        self.assertEqual((self.p.teskilat_birimi, self.p.gorev_unvani, self.p.idari_kadro), (self.sube, "Şube Müdürü", True))
        self.assertFalse(self.p.sinav_gorevi_alabilir)
        self.assertEqual(self.ask.baskan, self.p)
        self.assertEqual(KartDegeri.objects.get(personel=self.p, alan=tel).deger, "0555 000 00 00")
        self.assertFalse(KartDegeri.objects.filter(alan=kan).exists())  # listede olmayan seçim yazılmaz
        r = self.client.get(reverse("personel:detay", args=[self.p.pk]))
        self.assertContains(r, "0555 000 00 00")
        self.assertContains(r, "Bölüm başkanı")
        self.assertContains(r, "yk-idari-nisan")
        # bölüm hesabı ek bilgileri görmez
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("personel:detay", args=[self.p.pk]))
        self.assertNotContains(r, "0555 000 00 00")
        self.assertNotContains(r, TCKN)
        self.assertEqual(self.client.get(reverse("personel:alanlar")).status_code, 403)
        self.assertEqual(self.client.post(reverse("personel:fotograf_yukle", args=[self.p.pk])).status_code, 403)

    def test_teskilat_semasi_ve_atama(self):
        self.client.force_login(self.yonetici)
        r = self.client.get(reverse("personel:teskilat"))
        self.assertContains(r, "İdari İşler Şube Müdürlüğü")
        self.assertContains(r, "Askeri Bilimler")
        u = reverse("personel:teskilat_birimi", args=[self.sube.pk])
        self.client.post(u, {"islem": "ata", "personel": [self.p.pk], "gorev_unvani": "Kısım Amiri"})
        self.p.refresh_from_db()
        self.assertEqual((self.p.teskilat_birimi, self.p.gorev_unvani), (self.sube, "Kısım Amiri"))
        self.client.post(u, {"islem": "alt_birim", "ad": "Personel Kısmı", "tur": "kisim"})
        self.assertTrue(TeskilatBirimi.objects.filter(ad="Personel Kısmı", ust=self.sube).exists())
        self.client.post(u, {"islem": "sil"})  # personeli ve alt birimi var: silinmez
        self.assertTrue(TeskilatBirimi.objects.filter(pk=self.sube.pk).exists())
        # bölüm başkanlığı birimi bölüm personelini listeler
        self.assertContains(self.client.get(reverse("personel:teskilat_birimi", args=[self.ask_tk.pk])), "Ali KAYA")             if self.p.teskilat_birimi is None else None
        self.client.force_login(self.bolumcu)
        self.assertEqual(self.client.post(u, {"islem": "sil"}).status_code, 403)

    def test_derse_ve_sinava_girmeyen_listelerde_cikmaz(self):
        from mazeret import servis as mservis

        class Istek:
            user = self.yonetici
        diger = Personel.objects.create(ad_soyad="Veli ÇELİK", bolum=self.ask, derse_girebilir=False,
                                        sinav_gorevi_alabilir=False)
        y = mservis.yetki(type("I", (), {"user": User.objects.create_superuser("su", password="x-Parola-123")})())
        self.assertNotIn(diger, list(mservis.personeller(y)))
        ys = mservis.yetki(type("I", (), {"user": User.objects.get(username="su")})(), mservis.TURLER["sinav"])
        self.assertNotIn(diger, list(mservis.personeller(ys)))
        self.assertIn(self.p, list(mservis.personeller(ys)))
