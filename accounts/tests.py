import time

from django.test import TestCase
from django.urls import reverse

from . import iki_adim as ia
from .models import IkiAdimliDogrulama, User

PAROLA = "x-Parola-123"


class TotpTests(TestCase):
    def test_rfc6238_ornegi(self):
        # RFC 6238 ek B: "12345678901234567890" anahtarı, T = 59 sn → 94287082 (8 hane); son 6 hane
        gizli = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        self.assertEqual(ia._kod(gizli, 59 // 30), "287082")

    def test_pencere_ve_tekrar(self):
        gizli = ia.gizli_uret()
        simdi = time.time()
        kod = ia._kod(gizli, ia.simdiki_adim(simdi) - 1)  # bir önceki adımın kodu da geçer
        adim = ia.dogrula(gizli, kod, zaman=simdi)
        self.assertIsNotNone(adim)
        self.assertIsNone(ia.dogrula(gizli, kod, son_adim=adim, zaman=simdi))  # aynı kod ikinci kez geçmez
        self.assertIsNone(ia.dogrula(gizli, ia._kod(gizli, ia.simdiki_adim(simdi) - 3), zaman=simdi))
        self.assertIsNone(ia.dogrula(gizli, "12345", zaman=simdi))

    def test_yedek_kod_tek_kullanim(self):
        yedekler = ia.yedek_kodlar_uret()
        ozetler = [o for _k, o in yedekler]
        kalan, ok = ia.yedek_kod_kullan(ozetler, yedekler[3][0].upper().replace("-", ""))
        self.assertTrue(ok)
        self.assertEqual(len(kalan), ia.YEDEK_SAYISI - 1)
        self.assertFalse(ia.yedek_kod_kullan(kalan, yedekler[3][0])[1])


class GirisTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ali", password=PAROLA, is_staff=True)

    def _ac(self):
        gizli = ia.gizli_uret()
        yedekler = ia.yedek_kodlar_uret()
        IkiAdimliDogrulama.objects.create(kullanici=self.user, gizli=gizli, etkin=True,
                                          yedek_kodlar=[o for _k, o in yedekler])
        return gizli, [k for k, _o in yedekler]

    def _kod(self, gizli):
        return ia._kod(gizli, ia.simdiki_adim())

    def test_kapaliysa_yalniz_parola(self):
        r = self.client.post(reverse("login"), {"username": "ali", "password": PAROLA})
        self.assertRedirects(r, reverse("core:panel"), fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)

    def test_aciksa_kod_sorulur(self):
        gizli, _ = self._ac()
        r = self.client.post(reverse("login"), {"username": "ali", "password": PAROLA, "next": "/personel/"})
        self.assertRedirects(r, reverse("giris_kodu"))
        self.assertNotIn("_auth_user_id", self.client.session)  # henüz oturum yok
        self.assertEqual(self.client.get(reverse("core:panel")).status_code, 302)
        r = self.client.post(reverse("giris_kodu"), {"kod": "000000"})
        self.assertContains(r, "Kod hatalı")
        r = self.client.post(reverse("giris_kodu"), {"kod": self._kod(gizli)})
        self.assertRedirects(r, "/personel/", fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)

    def test_yedek_kod_ve_deneme_siniri(self):
        _gizli, yedekler = self._ac()
        self.client.post(reverse("login"), {"username": "ali", "password": PAROLA})
        r = self.client.post(reverse("giris_kodu"), {"kod": yedekler[0]})
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(IkiAdimliDogrulama.objects.get(kullanici=self.user).kalan_yedek, ia.YEDEK_SAYISI - 1)
        self.client.logout()
        self.client.post(reverse("login"), {"username": "ali", "password": PAROLA})
        for _ in range(5):
            r = self.client.post(reverse("giris_kodu"), {"kod": "111111"})
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_kod_sayfasi_dogrudan_acilmaz(self):
        self.assertRedirects(self.client.get(reverse("giris_kodu")), reverse("login"), fetch_redirect_response=False)

    def test_yonetim_paneli_girisi_atlanamaz(self):
        self._ac()
        r = self.client.get("/yonetim/login/")
        self.assertTrue(r["Location"].startswith(reverse("login")))
        r = self.client.post("/yonetim/login/", {"username": "ali", "password": PAROLA})
        self.assertNotIn("_auth_user_id", self.client.session)


class AyarTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("veli", password=PAROLA)
        self.client.force_login(self.user)
        self.url = reverse("iki_adim")

    def test_ac_yenile_kapat(self):
        self.assertContains(self.client.get(self.url), "Kapalı")
        self.client.post(self.url, {"islem": "baslat"})
        r = self.client.get(self.url)
        self.assertContains(r, "<svg")
        gizli = self.client.session["iki_adim_kurulum"]
        r = self.client.post(self.url, {"islem": "onayla", "kod": "000000"}, follow=True)
        self.assertContains(r, "Kod doğrulanamadı")
        r = self.client.post(self.url, {"islem": "onayla", "kod": ia._kod(gizli, ia.simdiki_adim())})
        self.assertContains(r, "Yedek kodlarınız")
        kayit = IkiAdimliDogrulama.objects.get(kullanici=self.user)
        self.assertTrue(kayit.etkin)
        # kapatma: parola + kod (aynı adımın kodu ikinci kez geçmez, sonraki adımın kodu kullanılır)
        sonraki = ia._kod(gizli, kayit.son_adim + 1)
        r = self.client.post(self.url, {"islem": "kapat", "parola": "yanlis", "kod": sonraki}, follow=True)
        self.assertContains(r, "Parola ya da uygulamadaki kod hatalı")
        r = self.client.post(self.url, {"islem": "kapat", "parola": PAROLA, "kod": sonraki}, follow=True)
        self.assertContains(r, "kapatıldı")
        self.assertFalse(IkiAdimliDogrulama.objects.filter(kullanici=self.user).exists())


class GuvenlikTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.user = User.objects.create_user("ayse", password=PAROLA)

    def test_hatali_deneme_kilidi(self):
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "ayse", "password": "yanlis"})
        r = self.client.post(reverse("login"), {"username": "AYSE", "password": PAROLA})  # doğru parola da geçmez
        self.assertContains(r, "Çok sayıda hatalı deneme")
        self.assertNotIn("_auth_user_id", self.client.session)
        r = self.client.post(reverse("login"), {"username": "baska", "password": "x"})  # başka hesap etkilenmez
        self.assertNotContains(r, "Çok sayıda hatalı deneme")

    def test_kilit_kademeli_uzar(self):
        import time
        from unittest import mock

        def bes_hata():
            for _ in range(5):
                self.client.post(reverse("login"), {"username": "ayse", "password": "yanlis"})

        simdi = time.time()
        with mock.patch("accounts.guvenlik.time.time", return_value=simdi):
            bes_hata()
            self.assertContains(self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA}), "1 dakika")
        with mock.patch("accounts.guvenlik.time.time", return_value=simdi + 61):  # ilk kilit bitti
            bes_hata()
            self.assertContains(self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA}), "3 dakika")
        with mock.patch("accounts.guvenlik.time.time", return_value=simdi + 61 + 181):
            bes_hata()
            self.assertContains(self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA}), "9 dakika")
        with mock.patch("accounts.guvenlik.time.time", return_value=simdi + 61 + 181 + 541):
            self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA})
            self.assertIn("_auth_user_id", self.client.session)

    def test_basarili_giris_sayaci_sifirlar(self):
        for _ in range(4):
            self.client.post(reverse("login"), {"username": "ayse", "password": "yanlis"})
        self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        self.client.post(reverse("login"), {"username": "ayse", "password": "yanlis"})
        self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA})
        self.assertIn("_auth_user_id", self.client.session)

    def test_internetten_iki_adim_zorunlu(self):
        from .models import GuvenlikAyari

        dis = {"HTTP_HOST": "kamyosis.ornek.ts.net"}
        r = self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA}, **dis)
        self.assertContains(r, "İnternet üzerinden giriş için iki adımlı doğrulama gerekir")
        self.assertNotIn("_auth_user_id", self.client.session)
        # kurum ağından yalnız parola yeter
        self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA}, HTTP_HOST="192.168.1.14:8000")
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        # 2FA açık kullanıcı dışarıdan kod sayfasına geçer
        IkiAdimliDogrulama.objects.create(kullanici=self.user, gizli=ia.gizli_uret(), etkin=True)
        r = self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA}, **dis)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith(reverse("giris_kodu")))
        # ayar kapatılırsa dışarıdan da parola yeter
        IkiAdimliDogrulama.objects.all().delete()
        GuvenlikAyari.objects.update_or_create(pk=GuvenlikAyari.al().pk, defaults={"dis_erisimde_iki_adim_zorunlu": False})
        self.client.post(reverse("login"), {"username": "ayse", "password": PAROLA}, **dis)
        self.assertIn("_auth_user_id", self.client.session)


class GelistirmeKoduTests(TestCase):
    """Geliştirme sürecinde ortak kod: herkes kod sayfasına gider, ortak kod (ve 2FA'lının kendi kodu) geçer."""

    KOD = "24681357"

    def setUp(self):
        from django.core.cache import cache

        from .models import GuvenlikAyari

        cache.clear()
        self.user = User.objects.create_user("veli", password=PAROLA)
        GuvenlikAyari.objects.update_or_create(pk=GuvenlikAyari.al().pk, defaults={"gelistirme_kodu": self.KOD})

    def test_herkese_kod_sorulur_ortak_kod_gecer(self):
        r = self.client.post(reverse("login"), {"username": "veli", "password": PAROLA})
        self.assertRedirects(r, reverse("giris_kodu"))
        self.assertNotIn("_auth_user_id", self.client.session)
        r = self.client.get(reverse("giris_kodu"))
        self.assertContains(r, "geçici ortak doğrulama kodu")
        self.assertNotContains(r, self.KOD)  # kod sayfada yazmaz
        r = self.client.post(reverse("giris_kodu"), {"kod": "11111111"})
        self.assertContains(r, "Kod hatalı")
        self.client.post(reverse("giris_kodu"), {"kod": self.KOD})
        self.assertIn("_auth_user_id", self.client.session)

    def test_internetten_ortak_kodla_girilir(self):
        dis = {"HTTP_HOST": "kamyosis.ornek.ts.net"}
        r = self.client.post(reverse("login"), {"username": "veli", "password": PAROLA}, **dis)
        self.assertTrue(r["Location"].endswith(reverse("giris_kodu")))
        self.client.post(reverse("giris_kodu"), {"kod": self.KOD}, **dis)
        self.assertIn("_auth_user_id", self.client.session)

    def test_iki_adimlinin_kendi_kodu_da_gecer(self):
        gizli = ia.gizli_uret()
        IkiAdimliDogrulama.objects.create(kullanici=self.user, gizli=gizli, etkin=True)
        self.client.post(reverse("login"), {"username": "veli", "password": PAROLA})
        self.client.post(reverse("giris_kodu"), {"kod": ia._kod(gizli, ia.simdiki_adim())})
        self.assertIn("_auth_user_id", self.client.session)

    def test_kod_bosaltilinca_eski_duzen(self):
        from .models import GuvenlikAyari

        GuvenlikAyari.objects.update(gelistirme_kodu="")
        self.client.post(reverse("login"), {"username": "veli", "password": PAROLA})
        self.assertIn("_auth_user_id", self.client.session)  # 2FA'sız kullanıcıya kod sorulmaz
