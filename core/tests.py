from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from personel.models import Bolum, Personel

from . import bolum_yetkileri as by
from .models import Birim, Yetki


class YetkiTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        cls.tem = Bolum.objects.create(ad="Temel Bilimler", kod="TEM")
        cls.p_ask = Personel.objects.create(ad_soyad="Ask Personel", personel_kodu="A1", bolum=cls.ask)
        cls.p_tem = Personel.objects.create(ad_soyad="Tem Personel", personel_kodu="T1", bolum=cls.tem)

        cls.yonetici = User.objects.create_superuser("yonetici", password="x-Parola-123")
        cls.bolumcu = User.objects.create_user("bolumcu", password="x-Parola-123", bolum=cls.ask)
        Yetki.objects.create(kullanici=cls.bolumcu, birim=Birim.objects.get(slug="personel-bilgileri"),
                             seviye=Yetki.GORUNTULEME, kapsam=Yetki.BOLUM)
        cls.yetkisiz = User.objects.create_user("yetkisiz", password="x-Parola-123")

    def test_baslangic_agaci_yuklu(self):
        self.assertTrue(Birim.objects.filter(slug="ders-planlari", ust__slug="plan-program").exists())
        self.assertEqual(Birim.objects.get(slug="personel-bilgileri").modul_url, "personel:liste")

    def test_giris_gerekir(self):
        r = self.client.get(reverse("core:panel"))
        self.assertRedirects(r, f"{reverse('login')}?next=/")

    def test_yonetici_tum_personeli_gorur(self):
        self.client.force_login(self.yonetici)
        r = self.client.get(reverse("personel:liste"), {"q": "personel"})  # genel görünüm birim kutucukları; arama kişileri
        self.assertContains(r, "Ask Personel")
        self.assertContains(r, "Tem Personel")

    def test_bolum_kullanicisi_sadece_kendi_bolumunu_gorur(self):
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("personel:liste"))
        self.assertContains(r, "Ask Personel")
        self.assertNotContains(r, "Tem Personel")
        self.assertEqual(self.client.get(reverse("personel:detay", args=[self.p_tem.pk])).status_code, 404)

    def test_goruntuleme_yetkisi_duzenleyemez(self):
        self.client.force_login(self.bolumcu)
        self.assertEqual(self.client.get(reverse("personel:duzenle", args=[self.p_ask.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("personel:ekle")).status_code, 403)

    def test_menu_sadece_yetkili_dallari_gosterir(self):
        # tüm bölümler kapsamlı kullanıcı: ağaçta yalnızca yetkili dalı
        u = User.objects.create_user("izleyici", password="x-Parola-123")
        Yetki.objects.create(kullanici=u, birim=Birim.objects.get(slug="personel-bilgileri"),
                             seviye=Yetki.GORUNTULEME, kapsam=Yetki.TUM)
        self.client.force_login(u)
        r = self.client.get(reverse("core:panel"))
        self.assertContains(r, "Personel Kartları")
        self.assertNotContains(r, "Plan Program Kısmı")
        # bölüm hesabında ağaç yok, yalnızca kısayol
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("core:panel"))
        self.assertNotContains(r, "Personel Kartları")
        self.assertContains(r, 'href="/personel/"')

    def test_yetkisiz_kullanici(self):
        self.client.force_login(self.yetkisiz)
        self.assertContains(self.client.get(reverse("core:panel")), "birim yetkisi yok")
        self.assertEqual(self.client.get(reverse("personel:liste")).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:birim", args=["plan-program"])).status_code, 403)

    def test_ust_birim_yetkisi_alt_birime_gecer(self):
        Yetki.objects.create(kullanici=self.yetkisiz, birim=Birim.objects.get(slug="idari-isler"),
                             seviye=Yetki.DUZENLEME, kapsam=Yetki.TUM)
        self.client.force_login(self.yetkisiz)
        self.assertEqual(self.client.get(reverse("personel:ekle")).status_code, 200)

    def test_bolum_kapsamli_duzenleyici_baska_bolume_kayit_acamaz(self):
        Yetki.objects.filter(kullanici=self.bolumcu).update(seviye=Yetki.DUZENLEME)
        self.client.force_login(self.bolumcu)
        r = self.client.post(reverse("personel:ekle"), {
            "ad_soyad": "Yeni Kisi", "personel_kodu": "Y1", "bolum": self.tem.pk, "aktif": "on",
        })
        self.assertEqual(r.status_code, 302)
        yeni = Personel.objects.get(ad_soyad="Yeni Kisi")
        self.assertEqual(yeni.bolum, self.ask)
        self.assertIsNone(yeni.personel_kodu)  # T.C. kimlik no yalnız yöneticide

    def test_parola_degismeli_yonlendirilir(self):
        self.bolumcu.parola_degismeli = True
        self.bolumcu.save()
        self.client.force_login(self.bolumcu)
        self.assertRedirects(self.client.get(reverse("core:panel")), reverse("parola_degistir"))
        r = self.client.post(reverse("parola_degistir"), {
            "old_password": "x-Parola-123", "new_password1": "Yeni-Parola-456", "new_password2": "Yeni-Parola-456",
        })
        self.assertRedirects(r, reverse("core:panel"))
        self.bolumcu.refresh_from_db()
        self.assertFalse(self.bolumcu.parola_degismeli)

    def test_hazir_olmayan_moduller_sadece_yoneticiye_gorunur(self):
        Yetki.objects.create(kullanici=self.yetkisiz, birim=Birim.objects.get(slug="idari-isler"), seviye=Yetki.YONETIM)
        self.client.force_login(self.yetkisiz)
        r = self.client.get(reverse("core:organizasyon"))
        self.assertContains(r, "Personel Kartları")
        self.assertNotContains(r, "Nöbet Faaliyetleri")
        self.assertEqual(self.client.get(reverse("core:birim", args=["nobet-faaliyetleri"])).status_code, 403)
        self.client.force_login(self.yonetici)
        self.assertContains(self.client.get(reverse("core:organizasyon")), "Nöbet Faaliyetleri")

class BolumYetkileriTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        cls.tem = Bolum.objects.create(ad="Temel Bilimler", kod="TEM")
        plan = Birim.objects.get(slug="plan-program")
        cls.ask1 = User.objects.create_user("ask1", password="x-Parola-123", bolum=cls.ask)
        cls.ask2 = User.objects.create_user("ask2", password="x-Parola-123", bolum=cls.ask)
        cls.tem1 = User.objects.create_user("tem1", password="x-Parola-123", bolum=cls.tem)
        for u in (cls.ask1, cls.ask2, cls.tem1):
            Yetki.objects.create(kullanici=u, birim=plan, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        # bölümü atanmış ama "tüm bölümler" yetkili yönetici: tabloya girmez, dokunulmaz
        cls.yon = User.objects.create_user("yon", password="x-Parola-123", bolum=cls.ask)
        Yetki.objects.create(kullanici=cls.yon, birim=plan, seviye=Yetki.YONETIM, kapsam=Yetki.TUM)
        cls.su = User.objects.create_superuser("su", password="x-Parola-123")

    def modul(self, slug):
        return next(m for m in by.moduller() if m.slug == slug)

    def test_tablo_mirasi_gosterir(self):
        moduller, satirlar, _ = by.tablo()
        slugs = [m.slug for m in moduller]
        self.assertIn("ders-planlari", slugs)
        self.assertIn("ders-mazeretleri", slugs)
        self.assertNotIn("plan-program", slugs)  # başlıklar sütun olmaz, yalnızca modüller
        self.assertIn("sinav-mazeretleri", slugs)
        self.assertNotIn("belge-istekleri", slugs)  # planlandı
        self.assertEqual([s["bolum"].kod for s in satirlar], ["ASK", "TEM"])
        ask = satirlar[0]
        self.assertEqual([u.username for u in ask["hesaplar"]], ["ask1", "ask2"])
        hucre = next(h for h in ask["hucreler"] if h["modul"].slug == "ders-planlari")
        self.assertTrue(hucre["gorur"])  # plan-program'dan miras

    def test_kaydetme_ust_yetkiyi_modul_yetkilerine_cevirir(self):
        dp, dm = self.modul("ders-planlari"), self.modul("ders-mazeretleri")
        self.client.force_login(self.su)
        r = self.client.post(reverse("core:bolum_yetkileri"), {
            "h": [f"{self.ask.pk}-{dp.pk}", f"{self.ask.pk}-{dm.pk}", f"{self.tem.pk}-{dm.pk}"],
            f"seviye_{dp.pk}": Yetki.DUZENLEME, f"seviye_{dm.pk}": Yetki.GORUNTULEME,
        })
        self.assertRedirects(r, reverse("core:bolum_yetkileri"), fetch_redirect_response=False)
        for u in (self.ask1, self.ask2):
            self.assertEqual(set(u.yetkiler.values_list("birim__slug", "seviye", "kapsam")),
                             {("ders-planlari", 2, "bolum"), ("ders-mazeretleri", 1, "bolum")})
        self.assertEqual(set(self.tem1.yetkiler.values_list("birim__slug", "seviye")), {("ders-mazeretleri", 1)})
        self.assertEqual(set(self.yon.yetkiler.values_list("birim__slug", "seviye")), {("plan-program", 3)})
        # menü: Program Hazırlama artık görünmez
        from django.test import RequestFactory

        from .yetki import birim_bul, gorunur_mu
        istek = RequestFactory().get("/")
        istek.user = self.tem1
        self.assertFalse(gorunur_mu(istek, birim_bul(istek, "program-hazirlama")))
        self.assertTrue(gorunur_mu(istek, birim_bul(istek, "ders-mazeretleri")))

    def test_program_hazirlama_her_zaman_gorur_seviyesinde(self):
        ph = self.modul("program-hazirlama")
        by.kaydet({self.tem.pk: {ph.pk}}, {ph.pk: Yetki.DUZENLEME})
        self.assertEqual(list(self.tem1.yetkiler.values_list("birim__slug", "seviye")), [("program-hazirlama", 1)])

    def test_yalniz_sistem_yoneticisi(self):
        self.client.force_login(self.yon)
        self.assertEqual(self.client.get(reverse("core:bolum_yetkileri")).status_code, 403)
        self.client.force_login(self.su)
        r = self.client.get(reverse("core:bolum_yetkileri"))  # sayfa Kullanıcılar ve yetkiler'e taşındı
        self.assertRedirects(r, reverse("core:kullanicilar") + "?tur=bolum")
        r = self.client.get(reverse("core:bolum_yetkileri") + "?eski=1")
        self.assertContains(r, "Askeri Bilimler")
        self.assertContains(r, "ask1, ask2")


class BolumMenusuTestleri(TestCase):
    """Bölüm hesabının menüsünde yalnızca kısayollar; hangisinin görüneceğini sistem yöneticisi seçer."""

    @classmethod
    def setUpTestData(cls):
        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        plan = Birim.objects.get(slug="plan-program")
        cls.ask1 = User.objects.create_user("ask1", password="x-Parola-123", bolum=cls.ask)
        Yetki.objects.create(kullanici=cls.ask1, birim=plan, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        cls.yon = User.objects.create_user("yon", password="x-Parola-123", bolum=cls.ask)
        Yetki.objects.create(kullanici=cls.yon, birim=plan, seviye=Yetki.YONETIM, kapsam=Yetki.TUM)
        cls.su = User.objects.create_superuser("su", password="x-Parola-123")

    def test_bolum_hesabi_yalniz_kisayollari_gorur(self):
        self.client.force_login(self.ask1)
        r = self.client.get(reverse("core:panel"))
        self.assertNotContains(r, "Organizasyon şeması")
        self.assertNotContains(r, '<div class="menu-baslik">Birimler</div>', html=False)
        self.assertContains(r, "Ders takibi")
        self.assertContains(r, "Sınav planları")  # ağaç gizli olduğu için kısayol olarak
        # yönetici hesabı (tüm bölümler) ağacı görmeye devam eder
        self.client.force_login(self.yon)
        r = self.client.get(reverse("core:panel"))
        self.assertContains(r, "Organizasyon şeması")
        self.assertNotContains(r, "Sınav planları</span>")

    def test_yonetici_kisayol_secer(self):
        self.client.force_login(self.su)
        url = reverse("core:bolum_kisayollari")
        r = self.client.get(url)
        self.assertContains(r, "ask1")
        self.assertNotContains(r, ">yon<")
        # yalnızca ders takibi ve personel açık kalsın
        self.client.post(url, {"k": [f"{self.ask.pk}:ders-takibi", f"{self.ask.pk}:personel"]})
        self.client.force_login(self.ask1)
        r = self.client.get(reverse("core:panel"))
        self.assertContains(r, "Ders takibi")
        self.assertNotContains(r, "Haftalık program")
        self.assertNotContains(r, "Sınav planları")
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_kapali_kisayolun_sayfasi_acilmaz(self):
        from mazeret.models import DersMazeretDonemi

        DersMazeretDonemi.objects.create(ad="Bahar")  # ana sayfada "bildirilmemiş" görev kartı çıksın
        Personel.objects.create(ad_soyad="Ask Personel", bolum=self.ask)
        self.client.force_login(self.ask1)
        self.assertEqual(self.client.get(reverse("mazeret:ders")).status_code, 200)
        self.assertContains(self.client.get(reverse("core:panel")), reverse("mazeret:ders"))
        self.client.force_login(self.su)
        self.client.post(reverse("core:bolum_kisayollari"), {"k": [f"{self.ask.pk}:ders-takibi"]})
        self.client.force_login(self.ask1)
        self.assertEqual(self.client.get(reverse("mazeret:ders")).status_code, 403)
        self.assertEqual(self.client.get(reverse("personel:liste")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("core:panel")), reverse("mazeret:ders"))
        self.assertEqual(self.client.get(reverse("takip:gunluk")).status_code, 200)
        # yönetici hesabı etkilenmez
        self.client.force_login(self.yon)
        self.assertEqual(self.client.get(reverse("mazeret:ders")).status_code, 200)


class TurkceAramaTestleri(TestCase):
    """Arama Türkçe harf ve büyük-küçük harf duyarsızdır; sözcük sırası önemsizdir."""

    def test_ara(self):
        from .arama import ara, eslesir

        b = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        p1 = Personel.objects.create(ad_soyad="Deneme KİRAZ", bolum=b)
        p2 = Personel.objects.create(ad_soyad="Şükrü IŞIK", bolum=b)
        p3 = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=b)
        qs = Personel.objects.all()
        bul = lambda q: set(ara(qs, q, "ad_soyad"))
        self.assertEqual(bul("kiraz"), {p1})
        self.assertEqual(bul("KİRAZ"), {p1})
        self.assertEqual(bul("kiraz deneme"), {p1})
        self.assertEqual(bul("işık"), {p2})
        self.assertEqual(bul("sukru isik"), {p2})
        self.assertEqual(bul("ayse"), {p3})
        self.assertEqual(bul("yılmaz ayşe"), {p3})
        self.assertEqual(bul("x"), set())
        self.assertTrue(eslesir("kiraz", "Deneme KİRAZ"))

    def test_personel_listesinde_soyadla_arama(self):
        u = User.objects.create_superuser("y2", password="x-Parola-123")
        Personel.objects.create(ad_soyad="Deneme KİRAZ")
        self.client.force_login(u)
        self.assertContains(self.client.get(reverse("personel:liste"), {"q": "kiraz"}), "KİRAZ")


class KullaniciYonetimiTestleri(TestCase):
    """Kullanıcılar ve yetkiler: yalnız sistem yöneticisi; tablo, hesap sayfası, parola, yeni hesap, günlük."""

    @classmethod
    def setUpTestData(cls):
        from personel.models import TeskilatBirimi

        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        cls.kisim = TeskilatBirimi.objects.create(ad="Plan Program Kısmı", tur=TeskilatBirimi.KISIM)
        cls.su = User.objects.create_superuser("su", password="x-Parola-123")
        cls.ask1 = User.objects.create_user("ask1", password="x-Parola-123", bolum=cls.ask)
        cls.plan = User.objects.create_user("plan", password="x-Parola-123", teskilat_birimi=cls.kisim,
                                            first_name="Plan Program Kısmı")
        cls.yoklama = Birim.objects.get(slug="personel-yoklamasi")
        cls.kartlar = Birim.objects.get(slug="personel-bilgileri")
        Yetki.objects.create(kullanici=cls.ask1, birim=cls.yoklama, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)

    def test_yalniz_sistem_yoneticisi(self):
        self.client.force_login(self.ask1)
        for ad, arg in (("core:kullanicilar", []), ("core:kullanici", [self.plan.pk]), ("core:kullanici_yeni", []),
                        ("core:kullanici_gecmisi", [])):
            self.assertEqual(self.client.get(reverse(ad, args=arg)).status_code, 403)

    def test_tablo_ve_toplu_kayit(self):
        self.client.force_login(self.su)
        r = self.client.get(reverse("core:kullanicilar"))
        self.assertContains(r, "Plan Program Kısmı")
        self.assertContains(r, "Şube / kısım hesabı")
        self.assertContains(r, f'data-u="{self.ask1.pk}" data-m="{self.yoklama.pk}" data-s="2"')
        r = self.client.post(reverse("core:kullanicilar"), {"c": [
            f"{self.plan.pk}:{self.yoklama.pk}:2:bolum", f"{self.plan.pk}:{self.kartlar.pk}:1:bolum",
            f"{self.ask1.pk}:{self.yoklama.pk}:0:bolum", f"{self.su.pk}:{self.yoklama.pk}:0:tum"]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(set(self.plan.yetkiler.values_list("birim__slug", "seviye", "kapsam")),
                         {("personel-yoklamasi", 2, "bolum"), ("personel-bilgileri", 1, "bolum")})
        self.assertFalse(self.ask1.yetkiler.exists())
        self.assertTrue(User.objects.get(pk=self.su.pk).is_superuser)  # sistem yöneticisine dokunulmaz
        r = self.client.get(reverse("core:kullanici_gecmisi"))
        self.assertContains(r, "Personel Yoklaması: Yok → Düzenler (kendi birimi)")

    def test_ust_birim_yetkisi_hucre_degisince_modullere_cevrilir(self):
        plan_program = Birim.objects.get(slug="plan-program")
        dp = Birim.objects.get(slug="ders-planlari")
        Yetki.objects.create(kullanici=self.plan, birim=plan_program, seviye=Yetki.GORUNTULEME, kapsam=Yetki.BOLUM)
        self.client.force_login(self.su)
        self.assertContains(self.client.get(reverse("core:kullanicilar")), 'data-miras="Plan Program Kısmı"')
        self.client.post(reverse("core:kullanicilar"), {"c": [f"{self.plan.pk}:{dp.pk}:0:bolum"]})
        slugs = set(self.plan.yetkiler.values_list("birim__slug", flat=True))
        self.assertNotIn("plan-program", slugs)
        self.assertNotIn("ders-planlari", slugs)
        self.assertIn("ders-mazeretleri", slugs)  # diğer modüller korunur

    def test_hesap_sayfasi_yetki_ve_bilgi(self):
        self.client.force_login(self.su)
        url = reverse("core:kullanici", args=[self.plan.pk])
        self.assertContains(self.client.get(url), "Yetkiler")
        self.client.post(url, {"islem": "yetki", f"s_{self.yoklama.pk}": "3", f"k_{self.yoklama.pk}": "tum"})
        self.assertEqual(list(self.plan.yetkiler.values_list("seviye", "kapsam")), [(3, "tum")])
        self.client.post(url, {"islem": "bilgi", "h-first_name": "Plan", "h-last_name": "", "h-bolum": "",
                               "h-teskilat_birimi": self.kisim.pk, "h-personel": "", "h-is_active": ""})
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_active)
        self.assertEqual(self.plan.first_name, "Plan")

    def test_parola_yenileme_zayifsa_onay_ister(self):
        self.client.force_login(self.su)
        url = reverse("core:kullanici", args=[self.plan.pk])
        r = self.client.post(url, {"islem": "parola", "p-parola": "plan", "p-degistirsin": "on"})
        self.assertContains(r, "Parola zayıf olsa da kabul et")
        self.assertTrue(User.objects.get(pk=self.plan.pk).check_password("x-Parola-123"))
        self.client.post(url, {"islem": "parola", "p-parola": "plan", "p-zayif_onay": "on", "p-degistirsin": "on"})
        u = User.objects.get(pk=self.plan.pk)
        self.assertTrue(u.check_password("plan"))
        self.assertTrue(u.parola_degismeli)

    def test_sistem_yoneticisi_hesabi_salt_okunur(self):
        diger = User.objects.create_superuser("su2", password="x-Parola-123")
        self.client.force_login(self.su)
        url = reverse("core:kullanici", args=[diger.pk])
        self.assertContains(self.client.get(url), "Sistem yöneticisi hesabı")
        self.assertEqual(self.client.post(url, {"islem": "parola", "p-parola": "Yeni-Parola-987"}).status_code, 403)

    def test_yeni_hesap_yetkileri_kopyalar(self):
        self.client.force_login(self.su)
        r = self.client.post(reverse("core:kullanici_yeni"), {
            "username": "ask2", "first_name": "", "last_name": "", "bolum": self.ask.pk, "teskilat_birimi": "",
            "personel": "", "parola": "Guclu-Parola-482", "is_active": "on", "parola_degismeli": "on",
            "sablon": self.ask1.pk})
        u = User.objects.get(username="ask2")
        self.assertRedirects(r, reverse("core:kullanici", args=[u.pk]))
        self.assertEqual(list(u.yetkiler.values_list("birim__slug", "seviye", "kapsam")),
                         [("personel-yoklamasi", 2, "bolum")])
        self.assertTrue(u.check_password("Guclu-Parola-482") and u.parola_degismeli and u.bolum_id == self.ask.pk)
        # büyük / küçük harf farkıyla aynı ad alınamaz
        r = self.client.post(reverse("core:kullanici_yeni"), {"username": "ASK2", "parola": "Guclu-Parola-482"})
        self.assertContains(r, "zaten var")


class GostergePaneliTestleri(TestCase):
    """İstatistikler sayfası (Bugün ve Personel sekmeleri): yalnız sistem yöneticisi görür; ana sayfa sade kalır;
    bir kart hata verirse sayfa yine açılır."""

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone

        from personel.models import Secenek
        from yoklama import servis as ys
        from yoklama.models import IzinTuru, YoklamaKaydi

        cls.ask = Bolum.objects.create(ad="Askeri Bilimler", kod="ASK")
        alb = Secenek.objects.create(tur=Secenek.RUTBE, metin="Alb.", sira=20)
        asb = Secenek.objects.create(tur=Secenek.RUTBE, metin="Asb.Kd.Bçvş.", sira=5)
        dm = Secenek.objects.create(tur=Secenek.UNVAN, metin="De.Me.", sira=1)
        cls.p1 = Personel.objects.create(ad_soyad="Bir Deneme", personel_kodu="A1", bolum=cls.ask, rutbe=alb)
        cls.p2 = Personel.objects.create(ad_soyad="İki Deneme", personel_kodu="A2", bolum=cls.ask, rutbe=asb)
        cls.p3 = Personel.objects.create(ad_soyad="Üç Deneme", personel_kodu="A3", bolum=cls.ask, unvan=dm)
        cls.su = User.objects.create_superuser("su", password="x-Parola-123")
        cls.ask1 = User.objects.create_user("ask1", password="x-Parola-123", bolum=cls.ask)
        Yetki.objects.create(kullanici=cls.ask1, birim=Birim.objects.get(slug="personel-yoklamasi"),
                             seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        tur = IzinTuru.objects.create(ad="Raporlu (deneme)", kisa="RP", renk="#b91c1c")
        bas, bit = ys.gun_araligi(timezone.localdate())
        YoklamaKaydi.objects.create(personel=cls.p2, tur=tur, baslangic=bas, bitis=bit)

    def test_bugun_sekmesi(self):
        self.client.force_login(self.su)
        r = self.client.get(reverse("core:istatistikler"))
        self.assertContains(r, "Personelin bugünkü durumu")
        self.assertContains(r, "İki Deneme · Raporlu (deneme)")
        self.assertContains(r, "Bir Deneme · mevcut")
        self.assertContains(r, "Raporlu (deneme) <b>1</b>")
        p = r.context["pano"]["personel"]
        self.assertEqual((p["toplam"], p["mevcut"], p["gun_boyu"]), (3, 2, 1))

    def test_personel_sekmesi(self):
        self.client.force_login(self.su)
        r = self.client.get(reverse("core:istatistikler") + "?sekme=personel")
        self.assertContains(r, "Kadro yapısı")
        k = r.context["kadro"]
        self.assertEqual({t["kod"]: t["sayi"] for t in k["turler"]}, {"subay": 1, "astsubay": 1, "sivil": 1})
        self.assertEqual([c["ad"] for c in k["rutbeler"]], ["Alb.", "Asb.Kd.Bçvş."])  # kıdemliden başlar
        self.assertEqual(k["siviller"], [{"ad": "Devlet memuru", "sayi": 1}])

    def test_ana_sayfa_sade_menude_baglanti(self):
        self.client.force_login(self.su)
        r = self.client.get(reverse("core:panel"))
        self.assertNotContains(r, "Personelin bugünkü durumu")
        self.assertContains(r, reverse("core:istatistikler"))

    def test_yalniz_sistem_yoneticisi(self):
        self.client.force_login(self.ask1)
        self.assertEqual(self.client.get(reverse("core:istatistikler")).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:istatistikler") + "?sekme=personel").status_code, 403)
        self.assertNotContains(self.client.get(reverse("core:panel")), reverse("core:istatistikler"))

    def test_bir_kart_hata_verse_de_sayfa_acilir(self):
        from unittest import mock

        from . import pano

        self.client.force_login(self.su)
        with mock.patch.object(pano, "sinavlar", side_effect=RuntimeError("deneme")),                 self.assertLogs("core.pano", level="ERROR"):
            r = self.client.get(reverse("core:istatistikler"))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["pano"]["sinavlar"])
        self.assertContains(r, "Personelin bugünkü durumu")

    def test_yuzde_yerel_ayardan_bagimsiz(self):
        from . import pano

        self.assertEqual(pano._yuzde(1, 3), "33.33")
        self.assertEqual(pano._yuzde(5, 0), "0")
        self.assertEqual(pano._olcek(7), 8)

    def test_ogrenim_ve_kadro_durumu_kart_alanlari(self):
        from personel.models import KartAlani, KartDegeri

        ogr = KartAlani.objects.get(ad="Öğrenim durumu")  # personel/migrations/0017
        kd = KartAlani.objects.get(ad="Kadro durumu")
        self.assertEqual(ogr.secenek_listesi, ["Lise", "Ön lisans", "Lisans", "Yüksek lisans", "Doktora"])
        self.assertIn("Görevlendirme", kd.secenek_listesi)
        KartDegeri.objects.create(personel=self.p1, alan=ogr, deger="Yüksek lisans")
        KartDegeri.objects.create(personel=self.p2, alan=ogr, deger="Lisans")
        KartDegeri.objects.create(personel=self.p3, alan=ogr, deger="Lisans")
        KartDegeri.objects.create(personel=self.p1, alan=kd, deger="Muvazzaf")
        self.client.force_login(self.su)
        k = self.client.get(reverse("core:istatistikler") + "?sekme=personel").context["kadro"]
        o = k["ogrenim"]
        self.assertEqual((o["girilen"], o["girilmemis"]), (3, 0))
        self.assertEqual([(s["ad"], s["toplam"]) for s in o["satirlar"]], [("Lisans", 2), ("Yüksek lisans", 1)])
        self.assertEqual([x["ad"] for x in o["satirlar"][0]["parcalar"]], ["Astsubay", "Sivil"])
        self.assertEqual((k["kadro_durumu"]["girilen"], k["kadro_durumu"]["girilmemis"]), (1, 2))
        kd.aktif = False
        kd.save()
        self.assertIsNone(self.client.get(reverse("core:istatistikler") + "?sekme=personel").context["kadro"]["kadro_durumu"])

    def test_kadro_kapasitesi_ve_doluluk(self):
        from .models import KadroKapasitesi

        self.client.force_login(self.su)
        url = reverse("core:istatistikler")
        self.assertIsNone(self.client.get(url + "?sekme=personel").context["kadro"]["doluluk"]["genel"]["kapasite"])
        r = self.client.post(url, {"islem": "kapasite", "toplam": "", "subay": "2", "astsubay": "1", "sivil": "1"})
        self.assertRedirects(r, url + "?sekme=personel#doluluk", fetch_redirect_response=False)
        d = self.client.get(url + "?sekme=personel").context["kadro"]["doluluk"]
        self.assertEqual((d["genel"]["kapasite"], d["genel"]["oran"], d["genel"]["bos"]), (4, 75, 1))  # 3 kişi / 4
        self.assertEqual([(t["ad"], t["oran"]) for t in d["turler"]], [("Subay", 50), ("Astsubay", 100), ("Sivil", 100)])
        self.client.post(url, {"islem": "kapasite", "toplam": "2", "subay": "abc"})
        self.assertEqual(KadroKapasitesi.al().toplam, None)  # hatalı giriş kaydedilmez
        self.client.post(url, {"islem": "kapasite", "toplam": "2"})
        g = self.client.get(url + "?sekme=personel").context["kadro"]["doluluk"]["genel"]
        self.assertEqual((g["oran"], g["fazla"], g["boy"]), (150, 1, "100.00"))
        self.assertEqual(KadroKapasitesi.objects.count(), 1)
        self.client.force_login(self.ask1)
        self.assertEqual(self.client.post(url, {"islem": "kapasite", "toplam": "9"}).status_code, 403)
