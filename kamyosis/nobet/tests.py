from collections import Counter
from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from personel.models import Bolum, Personel, Secenek

from . import servis
from .models import NobetAtamasi, NobetAyari, NobetDonemi, NobetGorevi
from .servis import NobetHatasi


def ay_ekle(yil, ay, n):
    t = yil * 12 + ay - 1 + n
    return t // 12, t % 12 + 1


class NobetTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        NobetGorevi.objects.update(aktif=False)  # göçle gelen görevler yerine küçük bir deney düzeni
        def rutbe(metin, sira):
            return Secenek.objects.get_or_create(tur=Secenek.RUTBE, metin=metin, defaults={"sira": sira})[0]
        cls.atgm, cls.utgm, cls.yzb = rutbe("Atğm.", 1), rutbe("Ütğm.", 2), rutbe("Yzb.", 3)
        bolum = Bolum.objects.create(ad="Deneme", kod="DNM")

        def gorev(kisa, kontenjan, rutbeler, yatili=False, puan=1, sira=0):
            g = NobetGorevi.objects.create(ad=kisa, kisa_ad=kisa, kontenjan=kontenjan, yatili=yatili, puan=puan, sira=sira)
            g.izinli_rutbeler.set(rutbeler)
            return g

        cls.amir = gorev("AMIR", 2, [cls.yzb], sira=1)
        cls.kd = gorev("KD", None, [cls.yzb], sira=2)
        cls.ord = gorev("ORD", 2, [cls.utgm], yatili=True, puan=2, sira=3)
        cls.bil = gorev("BIL", 2, [cls.utgm], yatili=True, puan=2, sira=4)
        cls.etut = gorev("ETUT", None, [cls.utgm], sira=5)
        cls.kidemli = [Personel.objects.create(ad_soyad=f"Kıdemli {i}", bolum=bolum, rutbe=cls.yzb) for i in range(4)]
        cls.genc = [Personel.objects.create(ad_soyad=f"Genç {i}", bolum=bolum, rutbe=cls.utgm) for i in range(8)]
        cls.asteg = Personel.objects.create(ad_soyad="Asteğmen", bolum=bolum, rutbe=cls.atgm)
        cls.rutbesiz = Personel.objects.create(ad_soyad="Rütbesiz", bolum=bolum)

    def test_rutbe_kurallari_ve_kalan_herkes(self):
        d = NobetDonemi.objects.create(yil=2026, ay=11)
        rapor = servis.dagit(d)
        at = {a.personel_id: a.gorev for a in d.atamalar.all()}
        self.assertTrue(all(at[p.pk] in (self.amir, self.kd) for p in self.kidemli))
        self.assertTrue(all(at[p.pk] in (self.ord, self.bil, self.etut) for p in self.genc))
        say = Counter(g.kisa_ad for g in at.values())
        self.assertEqual((say["AMIR"], say["KD"], say["ORD"], say["BIL"], say["ETUT"]), (2, 2, 2, 2, 4))
        # kuralı tanımlanmamış asteğmen ve rütbesiz personel dağıtıma girmez
        self.assertNotIn(self.asteg.pk, at)
        self.assertNotIn(self.rutbesiz.pk, at)
        self.assertEqual([p.pk for p in rapor.bosta], [self.asteg.pk])
        self.assertEqual(rapor.rutbesiz, 1)

    def test_bir_yil_boyunca_yatili_esit_dagilir(self):
        y, a = 2026, 10
        for i in range(12):
            yy, aa = ay_ekle(y, a, i)
            d = NobetDonemi.objects.create(yil=yy, ay=aa)
            servis.dagit(d)
            self.assertEqual(servis.adalet_uyarilari(d), [], f"{d} adalet uyarısı")
            d.durum = NobetDonemi.KESIN
            d.save()
        yatili = Counter(NobetAtamasi.objects.filter(gorev__yatili=True).values_list("personel_id", flat=True))
        sayilar = [yatili[p.pk] for p in self.genc]
        self.assertLessEqual(max(sayilar) - min(sayilar), 1)
        self.assertEqual(sum(sayilar), 12 * 4)

    def test_arka_arkaya_ayni_gorev_onlenir(self):
        d1 = NobetDonemi.objects.create(yil=2026, ay=10)
        servis.dagit(d1)
        d1.durum = NobetDonemi.KESIN
        d1.save()
        d2 = NobetDonemi.objects.create(yil=2026, ay=11)
        servis.dagit(d2)
        once = dict(d1.atamalar.filter(gorev__kisa_ad="AMIR").values_list("personel_id", "gorev_id"))
        sonra = dict(d2.atamalar.values_list("personel_id", "gorev_id"))
        self.assertTrue(all(sonra[p] != g for p, g in once.items()))

    def test_nobet_yili_ekimde_sifirlanir(self):
        eylul = NobetDonemi.objects.create(yil=2026, ay=9, durum=NobetDonemi.KESIN)
        NobetAtamasi.objects.create(donem=eylul, gorev=self.ord, personel=self.genc[0])
        ekim = NobetDonemi.objects.create(yil=2026, ay=10)
        self.assertNotIn(self.genc[0].pk, servis.gecmis(ekim))
        self.assertEqual(eylul.nobet_yili(), (2025, 10))
        self.assertEqual(ekim.nobet_yili(), (2026, 10))
        self.assertEqual(NobetAyari.al().yil_baslangic_ayi, 10)

    def test_elle_degisiklik_kilitlenir_ve_korunur(self):
        d = NobetDonemi.objects.create(yil=2026, ay=11)
        servis.dagit(d)
        a = d.atamalar.get(personel=self.genc[0])
        hedef = self.ord if a.gorev != self.ord else self.bil
        servis.tasi(a, hedef)
        servis.dagit(d)
        a = d.atamalar.get(personel=self.genc[0])
        self.assertEqual((a.gorev, a.kilitli), (hedef, True))
        b = d.atamalar.get(personel=self.genc[1])
        eski_a, eski_b = a.gorev, b.gorev
        servis.yer_degistir(a, b)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.gorev, b.gorev), (eski_b, eski_a))

    def test_muafiyet(self):
        p, q = self.genc[0], self.genc[1]
        p.nobet_durumu, p.nobet_muafiyet_nedeni = Personel.NOBET_MUAF, "YDGG"
        p.save()
        q.nobet_durumu, q.nobet_muafiyet_bitis = Personel.NOBET_MUAF, date(2026, 10, 31)
        q.save()
        d = NobetDonemi.objects.create(yil=2026, ay=11)
        servis.dagit(d)
        kisiler = set(d.atamalar.values_list("personel_id", flat=True))
        self.assertNotIn(p.pk, kisiler)
        self.assertIn(q.pk, kisiler)  # muafiyeti Ekim sonunda bitti
        self.assertIn(p, servis.muaf_personel(d))

    def test_kesin_ay_degistirilemez(self):
        d = NobetDonemi.objects.create(yil=2026, ay=11)
        servis.dagit(d)
        d.durum = NobetDonemi.KESIN
        d.save()
        with self.assertRaises(NobetHatasi):
            servis.dagit(d)
        with self.assertRaises(NobetHatasi):
            servis.cikar(d.atamalar.first())

    def test_ekranlar(self):
        su = User.objects.create_superuser("su", password="x-Parola-123")
        self.client.force_login(su)
        r = self.client.post(reverse("nobet:ana"), {"yil": 2026, "ay": 12})
        self.assertRedirects(r, reverse("nobet:donem", args=[2026, 12]))
        self.assertContains(self.client.get(reverse("nobet:donem", args=[2026, 12])), "Kıdemli 0")
        r = self.client.post(reverse("nobet:islem", args=[2026, 12]), {"islem": "kesinlestir"})
        self.assertEqual(NobetDonemi.objects.get(yil=2026, ay=12).durum, NobetDonemi.KESIN)
        self.assertContains(self.client.get(reverse("nobet:puantaj"), {"yil": 2026}), "Genç 0")
        r = self.client.get(reverse("nobet:excel", args=[2026, 12]))
        self.assertEqual(r["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.client.post(reverse("nobet:personel"), {"personel": self.genc[2].pk, "durum": "tutamaz", "neden": "Rapor"})
        self.genc[2].refresh_from_db()
        self.assertEqual((self.genc[2].nobet_durumu, self.genc[2].nobet_muafiyet_nedeni), ("tutamaz", "Rapor"))

    def test_yillik_plan(self):
        su = User.objects.create_superuser("su2", password="x-Parola-123")
        self.client.force_login(su)
        r = self.client.post(reverse("nobet:yillik_olustur"), {"yil": 2026})
        self.assertEqual(NobetDonemi.objects.filter(durum=NobetDonemi.TASLAK).count(), 12)
        # taslaklar da sayıldığı için 12 aylık taslak planda da yatılı dengeli
        yatili = Counter(NobetAtamasi.objects.filter(gorev__yatili=True).values_list("personel_id", flat=True))
        sayilar = [yatili[p.pk] for p in self.genc]
        self.assertLessEqual(max(sayilar) - min(sayilar), 1)
        self.assertContains(self.client.get(reverse("nobet:yillik"), {"yil": 2026}), "Genç 0")
        # hücreden değiştir: bir gence Kasım'da orduevi yaz
        p = self.genc[0]
        r = self.client.post(reverse("nobet:yillik_hucre"), {"personel": p.pk, "yil": 2026, "ay": 11, "gorev": self.ord.pk})
        j = r.json()
        self.assertTrue(j["ok"])
        self.assertEqual((j["kisa"], j["yatili"]), ("ORD", True))
        a = NobetAtamasi.objects.get(donem__yil=2026, donem__ay=11, personel=p)
        self.assertEqual((a.gorev, a.kilitli), (self.ord, True))
        # nöbetten çıkar
        j = self.client.post(reverse("nobet:yillik_hucre"), {"personel": p.pk, "yil": 2026, "ay": 11, "gorev": ""}).json()
        self.assertTrue(j["ok"])
        self.assertFalse(NobetAtamasi.objects.filter(donem__yil=2026, donem__ay=11, personel=p).exists())
        # kesin ay değiştirilemez
        NobetDonemi.objects.filter(yil=2026, ay=12).update(durum=NobetDonemi.KESIN)
        r = self.client.post(reverse("nobet:yillik_hucre"), {"personel": p.pk, "yil": 2026, "ay": 12, "gorev": self.ord.pk})
        self.assertEqual(r.status_code, 409)
        # yeniden oluştur: kesin ay ve elle yapılanlar korunur
        NobetAtamasi.objects.filter(donem__yil=2027, donem__ay=1, personel=p).delete()
        servis.hucre_ata(p, 2027, 1, self.bil)
        self.client.post(reverse("nobet:yillik_olustur"), {"yil": 2026, "baslangic": "2027-1"})
        self.assertEqual(NobetAtamasi.objects.get(donem__yil=2027, donem__ay=1, personel=p).gorev, self.bil)
    # ---------------------------------------------------------------- kısıtlama, sabit görevli, aylık kontenjan, tür dengesi

    def test_kisitlama_kesistigi_aylarda_dagitima_girmez(self):
        from .models import NobetKisitlamasi
        p, q = self.genc[0], self.genc[1]
        NobetKisitlamasi.objects.create(personel=p, tur="izin", baslangic=date(2026, 11, 10), bitis=date(2026, 11, 15))
        NobetKisitlamasi.objects.create(personel=q, tur="tayin", baslangic=date(2027, 1, 1))
        kasim, aralik, ocak = (NobetDonemi.objects.create(yil=2026, ay=11), NobetDonemi.objects.create(yil=2026, ay=12),
                               NobetDonemi.objects.create(yil=2027, ay=1))
        for d in (kasim, aralik, ocak):
            servis.dagit(d)
        def var(d, k):
            return d.atamalar.filter(personel=k).exists()
        self.assertEqual((var(kasim, p), var(aralik, p)), (False, True))
        self.assertEqual((var(aralik, q), var(ocak, q)), (True, False))
        self.assertEqual(servis.muaf_etiketi(q, 2027, 3), "TAYİN")
        self.assertIn(q, servis.muaf_personel(ocak))

    def test_sabit_gorevliler(self):
        kut = NobetGorevi.objects.create(ad="Kütüphane", kisa_ad="KUT", kontenjan=1, sira=6)
        kut.izinli_rutbeler.set([self.utgm])
        kut.sabit_uyeler.set([self.genc[7]])
        kad = NobetGorevi.objects.create(ad="Kadın Kursiyer", kisa_ad="KAD", kontenjan=5, sira=7, sadece_sabit=True)
        kad.izinli_rutbeler.set([self.utgm])
        kad.sabit_uyeler.set([self.genc[6]])
        for ay in (10, 11, 12):
            d = NobetDonemi.objects.create(yil=2026, ay=ay)
            servis.dagit(d)
            self.assertEqual(list(d.atamalar.filter(gorev=kut).values_list("personel_id", flat=True)), [self.genc[7].pk])
            # sadece sabit: kontenjan 5 olsa da başkası yazılmaz
            self.assertEqual(list(d.atamalar.filter(gorev=kad).values_list("personel_id", flat=True)), [self.genc[6].pk])

    def test_aylik_kontenjan(self):
        from .models import NobetKontenjani
        NobetKontenjani.objects.create(gorev=self.ord, ay=7, kontenjan=4)
        haz, tem = NobetDonemi.objects.create(yil=2027, ay=6), NobetDonemi.objects.create(yil=2027, ay=7)
        servis.dagit(haz)
        servis.dagit(tem)
        self.assertEqual(haz.atamalar.filter(gorev=self.ord).count(), 2)
        self.assertEqual(tem.atamalar.filter(gorev=self.ord).count(), 4)

    def test_yatili_tur_dengesi(self):
        for i in range(12):
            yy, aa = ay_ekle(2026, 10, i)
            servis.dagit(NobetDonemi.objects.create(yil=yy, ay=aa))
        for p in self.genc:
            say = Counter(NobetAtamasi.objects.filter(personel=p, gorev__yatili=True).values_list("gorev__kisa_ad", flat=True))
            self.assertLessEqual(abs(say["ORD"] - say["BIL"]), 1, f"{p}: {say}")

    def test_hucreden_bu_ay_yazilamaz(self):
        from .models import NobetKisitlamasi
        su = User.objects.create_superuser("su3", password="x-Parola-123")
        self.client.force_login(su)
        d = NobetDonemi.objects.create(yil=2026, ay=11)
        servis.dagit(d)
        p = self.genc[0]
        j = self.client.post(reverse("nobet:yillik_hucre"), {"personel": p.pk, "yil": 2026, "ay": 11, "gorev": "engelle"}).json()
        self.assertEqual((j["ok"], j["etiket"]), (True, "✕"))
        self.assertFalse(d.atamalar.filter(personel=p).exists())
        servis.dagit(d)
        self.assertFalse(d.atamalar.filter(personel=p).exists())
        j = self.client.post(reverse("nobet:yillik_hucre"), {"personel": p.pk, "yil": 2026, "ay": 11, "gorev": "engel_kaldir"}).json()
        self.assertTrue(j["ok"])
        self.assertFalse(NobetKisitlamasi.objects.filter(personel=p).exists())
        # uzun kısıtlama hücreden kaldırılamaz
        NobetKisitlamasi.objects.create(personel=p, tur="kurs", baslangic=date(2026, 10, 1), bitis=date(2027, 2, 1))
        r = self.client.post(reverse("nobet:yillik_hucre"), {"personel": p.pk, "yil": 2026, "ay": 11, "gorev": "engel_kaldir"})
        self.assertEqual(r.status_code, 409)
        self.assertContains(self.client.get(reverse("nobet:kisitlamalar")), p.ad_soyad)
    def test_personel_durumlari_siralama_ve_filtre(self):
        su = User.objects.create_superuser("su4", password="x-Parola-123")
        self.client.force_login(su)
        def sira(**p):
            icerik = self.client.get(reverse("nobet:personel"), p).content.decode()
            return icerik.index("Kıdemli 0") < icerik.index("Genç 0")
        self.assertTrue(sira(sirala="rutbe"))       # artan: kıdemliden başla
        self.assertFalse(sira(sirala="-rutbe"))
        self.assertFalse(sira(sirala="ad"))         # "Genç" < "Kıdemli"
        diger = Bolum.objects.create(ad="Başka", kod="BSK")
        Personel.objects.create(ad_soyad="Başka Bölümden", bolum=diger, rutbe=self.utgm)
        r = self.client.get(reverse("nobet:personel"), {"bolum": diger.pk})
        self.assertContains(r, "Başka Bölümden")
        self.assertNotContains(r, "Genç 0")