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
        r = self.client.get(reverse("personel:liste"))
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
        self.assertContains(r, "Personel Bilgilerini Yönetme")
        self.assertNotContains(r, "Plan Program Kısmı")
        # bölüm hesabında ağaç yok, yalnızca kısayol
        self.client.force_login(self.bolumcu)
        r = self.client.get(reverse("core:panel"))
        self.assertNotContains(r, "Personel Bilgilerini Yönetme")
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
        self.assertEqual(Personel.objects.get(personel_kodu="Y1").bolum, self.ask)

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
        self.assertContains(r, "Personel Bilgilerini Yönetme")
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
        self.assertRedirects(r, reverse("core:bolum_yetkileri"))
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
        r = self.client.get(reverse("core:bolum_yetkileri"))
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
