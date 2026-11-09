import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from personel.models import Bolum, Personel, Secenek

from . import excel, kurallar, servis
from .models import Brans, BransAyari, Ders, KisiAyari, KodBransi, Program, Yil

User = get_user_model()


def _ders(p, yy, kod, ds, u=0, **ek):
    return Ders.objects.create(program=p, yariyil=yy, kod=kod, ad=kod, ds=ds, t=ds - u, u=u, **ek)


class KuralTestleri(TestCase):
    def test_ders_kodundan_brans(self):
        self.assertEqual(kurallar.kod_bransi("TEM100"), "FİZİK")
        self.assertEqual(kurallar.kod_bransi("tem101"), "MATEMATİK")
        self.assertEqual(kurallar.kod_bransi("BSB110"), "HUKUK")
        self.assertEqual(kurallar.kod_bransi("ELN205"), "ELEKTRONİK")
        self.assertIsNone(kurallar.kod_bransi("XYZ100"))

    def test_otomatik_kadro(self):
        rutbe = {m: Secenek.objects.create(tur=Secenek.RUTBE, metin=m) for m in ("Alb.", "Asb.Kd.Bçvş.", "Atğm.")}
        b = Personel.objects.create(ad_soyad="Başkan", personel_kodu="1", rutbe=rutbe["Alb."])
        s = Personel.objects.create(ad_soyad="Subay", personel_kodu="2", rutbe=rutbe["Alb."])
        a = Personel.objects.create(ad_soyad="Astsubay", personel_kodu="3", rutbe=rutbe["Asb.Kd.Bçvş."])
        y = Personel.objects.create(ad_soyad="Yedek", personel_kodu="4", rutbe=rutbe["Atğm."])
        v = Personel.objects.create(ad_soyad="Sivil", personel_kodu="5")
        bas = {b.pk}
        self.assertEqual([kurallar.otomatik_kadro(x, bas) for x in (b, s, a, y, v)],
                         [KisiAyari.BB, KisiAyari.SB, KisiAyari.ASB, KisiAyari.YEDEK, KisiAyari.SIVIL])

    def test_brans_onerisi(self):
        bil = Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        tem = Bolum.objects.create(ad="Temel Bilimler", kod="TEM")
        p1 = Personel.objects.create(ad_soyad="A", personel_kodu="1", bolum=bil)
        p2 = Personel.objects.create(ad_soyad="B", personel_kodu="2", bolum=tem)
        p3 = Personel.objects.create(ad_soyad="C", personel_kodu="3", bolum=tem, brans="Edebiyat")
        p4 = Personel.objects.create(ad_soyad="D", personel_kodu="4", bolum=bil, derse_girebilir=False)
        self.assertEqual([kurallar.brans_oneri_adi(p) for p in (p1, p2, p3, p4)],
                         ["BİLGİSAYAR", None, "TÜRK DİLİ", None])

    def test_hesap_yardimcilari(self):
        self.assertEqual(servis.yuvarla(13.5), 14)
        self.assertEqual(servis.yuvarla(13.27), 13)
        # Fizik (Excel): (44 − 5 − 8) ÷ (2 − 1) = 31
        self.assertEqual(servis.ortalama(44, 1, 2, 8, 5), 31)
        self.assertEqual(servis.ortalama(24, 0, 0, 0, 5), 24)  # kimse yoksa saatin kendisi
        # Elektronik: 308 ÷ 15 → 21 kişi − 15 = 6
        self.assertEqual(servis.ihtiyac(250, 308, 0, 0, 15, 15), 6)
        self.assertEqual(servis.ihtiyac(10, 10, 0, 0, 5, 20), 0)


class HesapTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.yil = Yil.objects.create(ad="2026-2027")
        cls.fizik = Brans.objects.get(ad="FİZİK")
        cls.oto = Brans.objects.get(ad="OTOMOTİV")
        cls.ott = Program.objects.create(yil=cls.yil, kod="OTT", ad="Otomotiv Teknolojisi", kisim1=4, kisim2=3)
        cls.eln = Program.objects.create(yil=cls.yil, kod="ELN", ad="Elektronik", kisim1=7, kisim2=5)
        _ders(cls.ott, 1, "TEM100", 2)  # Güz, 4 kısım → 8
        cls.fiz_eln = _ders(cls.eln, 2, "TEM100", 2)  # Bahar, 7 kısım → 14
        _ders(cls.ott, 1, "OTT101", 5, u=3, ikinci_eleman=True)  # yük 8 × 4 = 32 (Güz)
        _ders(cls.ott, 4, "OTT204", 5, u=3)  # yük 5 × 3 = 15 (Bahar)
        servis.kod_branslarini_tamamla(cls.yil)
        ott_b = Bolum.objects.create(ad="Otomotiv Teknolojisi", kod="OTT")
        alb = Secenek.objects.create(tur=Secenek.RUTBE, metin="Alb.")
        cls.baskan = Personel.objects.create(ad_soyad="Başkan", personel_kodu="1", bolum=ott_b, rutbe=alb)
        ott_b.baskan = cls.baskan
        ott_b.save()
        for i in range(3):
            Personel.objects.create(ad_soyad=f"Öğr {i}", personel_kodu=f"o{i}", bolum=ott_b, rutbe=alb)

    def _satir(self, brans):
        h = servis.Hesap(self.yil)
        return next(s for s in h.satirlar() if s.brans == brans), h

    def test_saatler_ve_ikinci_eleman(self):
        s, _ = self._satir(self.oto)
        self.assertEqual((s.guz, s.bahar), (32, 15))
        f, _ = self._satir(self.fizik)
        self.assertEqual((f.guz, f.bahar), (8, 14))

    def test_kisimlari_donemlere_dagitma(self):
        self.fiz_eln.guz_kisim, self.fiz_eln.bahar_kisim = 3, 4
        self.fiz_eln.save()
        f, _ = self._satir(self.fizik)
        self.assertEqual((f.guz, f.bahar), (8 + 6, 8))

    def test_mevcut_ortalama_ihtiyac(self):
        s, h = self._satir(self.oto)
        self.assertEqual((s.bb, s.sb, s.toplam), (1, 3, 4))
        # Güz: (32 − 5) ÷ 3 = 9; Bahar: (15 − 5) ÷ 3 = 3,33
        self.assertEqual((s.ort_guz_g, s.ort_bahar_g), (9, 3))
        self.assertFalse(s.guz_uyari)
        # dışarıdan 6 saat yalnız Güz'de destek
        BransAyari.objects.create(yil=self.yil, brans=self.oto, dis_saat=6, destek=BransAyari.DESTEK_GUZ, dis_sayi=1)
        s, _ = self._satir(self.oto)
        self.assertEqual((s.ort_guz, s.dis, s.dis_bahar), (7, 1, 0))
        self.assertEqual(h.kisim_toplami(), (11, 8, 0))

    def test_kisi_ayari_onerinin_yerine_gecer(self):
        ogr = Personel.objects.get(personel_kodu="o0")
        KisiAyari.objects.create(yil=self.yil, personel=ogr, brans=self.fizik, kadro=KisiAyari.SIVIL)
        KisiAyari.objects.create(yil=self.yil, personel=Personel.objects.get(personel_kodu="o1"), brans_yok=True)
        s, h = self._satir(self.oto)
        f = next(x for x in h.satirlar() if x.brans == self.fizik)
        self.assertEqual((s.toplam, f.sivil), (2, 1))

    def test_yil_kopyalama(self):
        KodBransi.objects.filter(yil=self.yil, kod="OTT204").update(brans=self.fizik)
        y = servis.yil_kopyala(self.yil, "2027-2028")
        self.assertEqual(Ders.objects.filter(program__yil=y).count(), 4)
        self.assertEqual(KodBransi.objects.get(yil=y, kod="OTT204").brans, self.fizik)
        self.assertEqual(Program.objects.get(yil=y, kod="OTT").kisim1, 4)


def _excel(sayfalar):
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for ad, program_adi, bloklar in sayfalar:
        ws = wb.create_sheet(ad)
        ws["C2"] = f"PROGRAM ADI : {program_adi}"
        for (r, c), yariyil, dersler in bloklar:
            ws.cell(r, c, "DERS\nKODU")
            ws.cell(r, c + 1, yariyil)
            for i, h in enumerate(["DS", "T", "U", "L", "KR", "AKTS"]):
                ws.cell(r, c + 2 + i, h)
            for j, (kod, ad_, *sayilar) in enumerate(dersler, 1):
                ws.cell(r + j, c, kod)
                ws.cell(r + j, c + 1, ad_)
                for i, v in enumerate(sayilar):
                    ws.cell(r + j, c + 2 + i, v)
            ws.cell(r + len(dersler) + 1, c + 1, "TOPLAM")
    f = io.BytesIO()
    wb.save(f)
    return f.getvalue()


class ExcelTestleri(TestCase):
    def test_yariyil_no(self):
        self.assertEqual([excel.yariyil_no(m) for m in ("1'İNCİ YARIYIL", "II.YARIYIL", "III. YARIYIL",
                                                         "4'ÜNCÜ YARIYIL", "TOPLAM")], [1, 2, 3, 4, None])

    def test_oku_ve_eslestir(self):
        veri = _excel([("Bilgisayar Teknolojisi", "BİLGİSAYAR TEKNOLOJİSİ", [
            ((3, 1), "1'İNCİ YARIYIL", [("TEM101", "MATEMATİK 1", 2, 2, 0, 0, 2, 2), ("BİL103", "ALGORİTMA", 3, 1, 2, 0, 2, 5)]),
            ((3, 10), "2'NCİ YARIYIL", [("TEM100", "FİZİK", 2, 2, 0, 0, 2, 2)]),
            ((18, 1), "III. YARIYIL", [("BİL221", "SUNUCU", 4, 2, 2, 0, 3, 5)]),
        ]), ("Birleştirilmiş", "", [])])
        sayfalar = excel.oku(io.BytesIO(veri))
        self.assertEqual(len(sayfalar), 1)
        sf = sayfalar[0]
        self.assertEqual(sf["program_adi"], "BİLGİSAYAR TEKNOLOJİSİ")
        self.assertEqual([(d["yariyil"], d["kod"], d["ds"], d["u"]) for d in sf["dersler"]],
                         [(1, "TEM101", 2, 0), (1, "BİL103", 3, 2), (2, "TEM100", 2, 0), (3, "BİL221", 4, 2)])
        y = Yil.objects.create(ad="2026-2027")
        bil = Program.objects.create(yil=y, kod="BİL", ad="Bilgisayar Teknolojisi")
        Program.objects.create(yil=y, kod="ELK", ad="Elektrik")
        self.assertEqual(excel.eslestir(sf, list(Program.objects.all())), bil)

    def test_excel_olmayan_dosya(self):
        with self.assertRaises(excel.ExcelHatasi):
            excel.oku(io.BytesIO(b"bu bir excel degil"))


class GorunumTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import Birim, Yetki

        cls.yil = Yil.objects.create(ad="2026-2027", varsayilan=True)
        cls.bil = Program.objects.create(yil=cls.yil, kod="BİL", ad="Bilgisayar Teknolojisi", kisim1=1, kisim2=1)
        cls.d = _ders(cls.bil, 1, "BİL103", 3, u=2)
        servis.kod_branslarini_tamamla(cls.yil)
        cls.su = User.objects.create_superuser("su", password="x-Parola-123")
        cls.bakan = User.objects.create_user("bakan", password="x-Parola-123")
        cls.yok = User.objects.create_user("yok", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.bakan, birim=Birim.objects.get(slug="dozajmatik"), seviye=Yetki.GORUNTULEME)

    def test_birim_ve_yetki(self):
        url = reverse("dozaj:tablo")
        self.client.force_login(self.yok)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.bakan)
        r = self.client.get(url)
        self.assertContains(r, "BİLGİSAYAR")
        self.assertNotContains(r, "Hesap ayarları")
        self.assertEqual(self.client.post(reverse("dozaj:programlar"), {"islem": "kisimlar"}).status_code, 403)

    def test_butun_sayfalar_acilir(self):
        self.client.force_login(self.su)
        b = Brans.objects.get(ad="BİLGİSAYAR")
        for url in (reverse("dozaj:tablo"), reverse("dozaj:brans", args=[b.pk]), reverse("dozaj:programlar"),
                    reverse("dozaj:program", args=[self.bil.pk]), reverse("dozaj:branslar"),
                    reverse("dozaj:personel"), reverse("dozaj:personel") + "?durum=branssiz"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_program_kaydet(self):
        self.client.force_login(self.su)
        on = f"d{self.d.pk}-"
        r = self.client.post(reverse("dozaj:program", args=[self.bil.pk]), {
            "islem": "kaydet", on + "kod": "BİL103", on + "ad": "ALGORİTMA", on + "ds": "4", on + "t": "2", on + "u": "2",
            on + "l": "0", on + "kr": "3", on + "akts": "5", on + "ikinci": "1", on + "guz": "1", on + "bahar": ""})
        self.assertEqual(r.status_code, 302)
        self.d.refresh_from_db()
        self.assertEqual((self.d.ds, self.d.ikinci_eleman, self.d.guz_kisim, self.d.bahar_kisim, self.d.yuk),
                         (4, True, 1, 0, 6))

    def test_kisim_sayilari_ve_kod_bransi(self):
        self.client.force_login(self.su)
        self.client.post(reverse("dozaj:programlar"), {"islem": "kisimlar", f"k1-{self.bil.pk}": "3",
                                                       f"k2-{self.bil.pk}": "2"})
        self.bil.refresh_from_db()
        self.assertEqual((self.bil.kisim1, self.bil.kisim2), (3, 2))
        mat = Brans.objects.get(ad="MATEMATİK")
        self.client.post(reverse("dozaj:branslar"), {"islem": "kodlar", "kod-BİL103": str(mat.pk)})
        self.assertEqual(KodBransi.objects.get(yil=self.yil, kod="BİL103").brans, mat)
        self.client.post(reverse("dozaj:programlar"), {"islem": "kisimlar", f"k1-{self.bil.pk}": "x"})
        self.bil.refresh_from_db()
        self.assertEqual(self.bil.kisim1, 3)  # hatalı giriş kaydedilmez

    def test_egitim_bilimleri_ogretim_programlari(self):
        from core.models import Birim, Yetki
        self.assertEqual(Birim.objects.get(slug="ogrenci-isleri-sube").ad, "Öğrenci İşleri")
        op = Birim.objects.get(slug="ogretim-programlari")
        self.assertEqual(op.ust.slug, "egitim-bilimleri")
        egitimci = User.objects.create_user("egitimci", password="x-Parola-123")
        Yetki.objects.create(kullanici=egitimci, birim=op, seviye=Yetki.DUZENLEME)
        self.client.force_login(egitimci)
        menu = self.client.get("/")
        self.assertContains(menu, "Eğitim Bilimleri")
        self.assertContains(menu, f'href="{reverse("dozaj:op_programlar")}"')
        r = self.client.get(reverse("dozaj:op_programlar"))
        self.assertContains(r, "<h1>Öğretim Programları</h1>", html=False)
        self.assertContains(r, reverse("dozaj:op_program", args=[self.bil.pk]))
        self.assertNotContains(r, reverse("dozaj:personel"))  # Dozajmatik sekmeleri yok
        r = self.client.get(reverse("dozaj:op_program", args=[self.bil.pk]))
        self.assertContains(r, "Bilgisayar Teknolojisi")
        self.assertNotContains(r, reverse("dozaj:branslar"))  # Dozajmatik yetkisi yok: branş bağlantısız
        for url in (reverse("dozaj:tablo"), reverse("dozaj:programlar")):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        r = self.client.post(reverse("dozaj:op_programlar"), {"islem": "kisimlar", f"k1-{self.bil.pk}": "4",
                                                              f"k2-{self.bil.pk}": "1"})
        self.assertRedirects(r, reverse("dozaj:op_programlar"))
        self.bil.refresh_from_db()
        self.assertEqual(self.bil.kisim1, 4)
        # Dozajmatik'i gören, Öğretim Programları yetkisi olmayan kişi: kendi sekmesinden açar, menüdekinden açamaz
        self.client.force_login(self.bakan)
        self.assertEqual(self.client.get(reverse("dozaj:op_programlar")).status_code, 403)
        r = self.client.get(reverse("dozaj:programlar"))
        self.assertContains(r, "<h1>Dozajmatik</h1>", html=False)
        self.assertContains(r, reverse("dozaj:program", args=[self.bil.pk]))

    def test_ogretim_elemani_ayari(self):
        bolum = Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        p = Personel.objects.create(ad_soyad="Deneme Kişi", personel_kodu="9", bolum=bolum)
        self.client.force_login(self.su)
        fizik = Brans.objects.get(ad="FİZİK")
        self.client.post(reverse("dozaj:personel"), {f"b-{p.pk}": str(fizik.pk), f"k-{p.pk}": KisiAyari.KH})
        a = KisiAyari.objects.get(yil=self.yil, personel=p)
        self.assertEqual((a.brans, a.kadro), (fizik, KisiAyari.KH))
        self.client.post(reverse("dozaj:personel"), {f"b-{p.pk}": "", f"k-{p.pk}": ""})  # öneriye dön
        self.assertFalse(KisiAyari.objects.filter(personel=p).exists())

    def test_excel_yukle_ayarlari_korur(self):
        self.d.ikinci_eleman = False
        self.d.save()
        veri = _excel([("Bilgisayar", "BİLGİSAYAR TEKNOLOJİSİ", [
            ((3, 1), "1'İNCİ YARIYIL", [("BİL103", "ALGORİTMA", 3, 1, 2, 0, 2, 5), ("ELN101", "ÖLÇME", 3, 1, 2, 0, 2, 3)])])])
        self.client.force_login(self.su)
        r = self.client.post(reverse("dozaj:excel"), {"dosya": SimpleUploadedFile("p.xlsx", veri)})
        self.assertContains(r, "Excel önizleme")
        self.assertEqual(r.context["onizleme"][0]["eslesen"], self.bil)
        self.client.post(reverse("dozaj:excel"), {"islem": "uygula", "hedef-0": str(self.bil.pk)})
        dersler = {d.kod: d for d in self.bil.dersler.all()}
        self.assertEqual(set(dersler), {"BİL103", "ELN101"})
        self.assertFalse(dersler["BİL103"].ikinci_eleman)  # eski ayar korundu
        self.assertTrue(dersler["ELN101"].ikinci_eleman)  # yeni uygulamalı ders: varsayılan açık
        self.assertEqual(KodBransi.objects.get(yil=self.yil, kod="ELN101").brans.ad, "ELEKTRONİK")

    def test_yil_yoksa_acma(self):
        Yil.objects.all().delete()
        self.client.force_login(self.su)
        self.assertContains(self.client.get(reverse("dozaj:tablo")), "Henüz plan yılı açılmadı")
        self.client.post(reverse("dozaj:tablo"), {"ad": "2027-2028"})
        self.assertTrue(Yil.objects.filter(ad="2027-2028").exists())
