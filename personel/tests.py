from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Birim, Yetki

from .models import Bolum, Personel, Secenek
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

    def test_duzenleyen_detayda_tam_numarayi_gorur(self):
        self.client.force_login(self.yonetici)
        self.assertNotContains(self.client.get(reverse("personel:liste")), TCKN)
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