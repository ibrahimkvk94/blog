from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Birim, Yetki
from personel.models import Personel
from program.models import Ders, ProgramHucresi, ProgramOgretmeni, ProgramSurumu
from timetable.demo import create_demo_school
from timetable.models import Card, Membership as M, Timetable

from .yetki import kurum

User = get_user_model()


def yetki_ver(kullanici, slug, seviye, kapsam=Yetki.TUM):
    return Yetki.objects.create(kullanici=kullanici, birim=Birim.objects.get(slug=slug), seviye=seviye, kapsam=kapsam)


class BirimTests(TestCase):
    def test_birimler(self):
        b = Birim.objects.get(slug="program-hazirlama")
        self.assertEqual(b.ust.slug, "plan-program")
        self.assertEqual(b.modul_url, "timetable:school_list")
        self.assertEqual(Birim.objects.get(slug="sinav-planlari").modul_url, "dersprogrami_kopru:sinavlar")
        self.assertEqual(kurum().name, "Kara Astsubay Meslek Yüksekokulu")


class YetkiEslemeTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("ogr", password="x")

    def uyelik(self):
        return M.objects.filter(user=self.u).first()

    def test_seviyeler(self):
        with self.captureOnCommitCallbacks(execute=True):
            y = yetki_ver(self.u, "program-hazirlama", Yetki.DUZENLEME)
        self.assertEqual(self.uyelik().permissions, [M.DATA, M.SUBSTITUTE])
        with self.captureOnCommitCallbacks(execute=True):
            y.seviye = Yetki.YONETIM
            y.save()
        self.assertEqual(set(self.uyelik().perms), {M.VIEW, M.DATA, M.SUBSTITUTE, M.PROGRAM, M.PUBLISH, M.PROGRAMS})
        self.assertNotIn(M.USERS, self.uyelik().perms)
        with self.captureOnCommitCallbacks(execute=True):
            y.kapsam = Yetki.BOLUM
            y.save()
        self.assertEqual(self.uyelik().permissions, [])
        with self.captureOnCommitCallbacks(execute=True):
            y.delete()
        self.assertIsNone(self.uyelik())

    def test_ust_birimden_gecer(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "plan-program", Yetki.YONETIM)
        self.assertIn(M.PUBLISH, self.uyelik().perms)

    def test_sinav_yetkisi_goruntuleme_uyeligi_verir(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "sinav-planlari", Yetki.DUZENLEME)
        self.assertEqual((self.uyelik().permissions, self.uyelik().modules), ([], ["sinav"]))

    def test_modul_kisiti(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "program-hazirlama", Yetki.DUZENLEME)
        self.assertEqual(self.uyelik().modules, ["ders"])
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "sinav-planlari", Yetki.GORUNTULEME)
        self.assertEqual(self.uyelik().modules, ["ders", "sinav"])

    def test_baska_birim_uyelik_vermez(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "nobet-gruplari", Yetki.YONETIM)
        self.assertIsNone(self.uyelik())


class AraKatmanTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("yonetici", password="x")

    def test_giris_gerekir(self):
        r = self.client.get("/ders-programi/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith(reverse("login")))

    def test_kapali_sayfalar_super_kullaniciya_da_kapali(self):
        self.client.force_login(self.admin)
        for ad in ("system_update", "backups", "central", "create_demo", "import_asc"):
            r = self.client.get(reverse(f"timetable:{ad}"))
            self.assertEqual(r.status_code, 404, ad)
        r = self.client.post(reverse("timetable:system_update"))
        self.assertEqual(r.status_code, 404)

    def test_yedek_karsilastirma_yalniz_goruntulenir(self):
        self.client.force_login(self.admin)
        school = create_demo_school(institution=kurum())
        url = reverse("timetable:backup_compare", args=[school.pk])
        self.assertEqual(self.client.get(url).status_code, 200)  # önceki başarılı üretimle karşılaştırma
        self.assertEqual(self.client.post(url, {"yedek": "x.json"}).status_code, 404)

    def test_giris_ve_hesap_kamyosise_yonlenir(self):
        self.assertRedirects(self.client.get(reverse("timetable:login")), reverse("login") + "?next=/",
                             fetch_redirect_response=False)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("timetable:account")), reverse("parola_degistir"),
                             fetch_redirect_response=False)
        # modülün iki adımlı giriş sayfaları da KAMYOSİS'e yönlenir (kilit ve iki adımlı doğrulama atlanamaz)
        self.assertRedirects(self.client.get(reverse("timetable:account_two_factor")), reverse("iki_adim"),
                             fetch_redirect_response=False)
        self.client.logout()
        r = self.client.post(reverse("timetable:login_verify"), {"code": "000000"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith(reverse("login")))

    def test_modul_ana_sayfasi_acilir(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("timetable:school_list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "KAMYOSİS · Ders Programı")
        self.assertNotContains(r, reverse("timetable:central"))

    def test_api_403_json(self):
        school = create_demo_school(institution=kurum())
        tt = Timetable.objects.create(school=school, name="P", status=Timetable.OK)
        u = User.objects.create_user("yetkisiz", password="x")
        self.client.force_login(u)
        r = self.client.get(reverse("timetable:api_grid", args=[tt.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r["Content-Type"], "application/json")


class SinavYetkisiTests(TestCase):
    """Sınav Planlama modülü KAMYOSİS'in Sınav Planları birimine bağlıdır."""

    def setUp(self):
        self.school = create_demo_school(institution=kurum())
        self.u = User.objects.create_user("sinav", password="x")
        self.client.force_login(self.u)
        self.url = reverse("sinav:periods", args=[self.school.pk])

    def test_yetkisiz_goremez(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_goruntuleme_yetkisi(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "sinav-planlari", Yetki.GORUNTULEME)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)

    def test_duzenleme_yetkisi_degistirebilir(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "sinav-planlari", Yetki.DUZENLEME, Yetki.BOLUM)
        self.assertNotEqual(self.client.post(self.url, {}).status_code, 403)  # form hatası, yetki hatası değil

    def test_program_yetkisi_sinava_girmez(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "program-hazirlama", Yetki.YONETIM)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)

    def test_sinav_birimi_yonlendirir(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "sinav-planlari", Yetki.GORUNTULEME)
        r = self.client.get(reverse("dersprogrami_kopru:sinavlar"))
        self.assertRedirects(r, self.url, fetch_redirect_response=False)

    def test_eski_sinav_adresi_yonlenir(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "sinav-planlari", Yetki.GORUNTULEME)
        r = self.client.get(reverse("timetable:exams_old", args=[self.school.pk]))
        self.assertRedirects(r, self.url, fetch_redirect_response=False)


class YayinAktarimTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("yonetici", password="x")
        self.client.force_login(self.admin)
        self.school = create_demo_school(institution=kurum())
        self.tt = Timetable.objects.create(school=self.school, name="Güz", status=Timetable.OK)
        self.saat = 0
        for i, lesson in enumerate(self.school.lessons.all()):  # ders başına bir kart yeter
            Card.objects.create(timetable=self.tt, lesson=lesson, length=lesson.card_length,
                                day=i % self.school.days_per_week, period=0)
            self.saat += lesson.card_length

    def yayinla(self):
        return self.client.post(reverse("timetable:publish", args=[self.tt.pk]))

    def test_yayinlaninca_taslak_surum_olusur(self):
        self.yayinla()
        surum = ProgramSurumu.objects.get(kaynak_dosya=f"dersprogrami:{self.tt.pk}")
        self.assertEqual(surum.durum, ProgramSurumu.TASLAK)
        self.assertEqual(ProgramHucresi.objects.filter(surum=surum).count(), self.saat)
        self.assertTrue(all(d.asc_id.startswith("DP-D") for d in Ders.objects.all()))

    def test_yeniden_yayin_taslagi_degistirir_kayit_cogaltmaz(self):
        self.yayinla()
        dersler = Ders.objects.count()
        self.yayinla()
        self.assertEqual(ProgramSurumu.objects.filter(kaynak_dosya=f"dersprogrami:{self.tt.pk}").count(), 1)
        self.assertEqual(Ders.objects.count(), dersler)

    def test_ogretmen_tc_ile_eslesir(self):
        t = self.school.teachers.first()
        t.tc_no = "10000000146"
        t.save()
        p = Personel.objects.create(ad_soyad="Bambaşka Bir Ad", personel_kodu="10000000146")
        self.yayinla()
        o = ProgramOgretmeni.objects.get(personel=p)
        self.assertEqual(o.durum, ProgramOgretmeni.ELLE)
        self.assertNotIn("10000000146", o.asc_id)

    def test_ab_haftali_program_aktarilmaz(self):
        lesson = self.school.lessons.first()
        lesson.weeks_mask = 1
        lesson.save()
        self.yayinla()
        self.assertFalse(ProgramSurumu.objects.exists())
        self.school.refresh_from_db()
        self.assertEqual(self.school.active_timetable_id, self.tt.pk)  # modülde yayın yine yapılır


class SadeceSinavTests(TestCase):
    """Program Hazırlama yetkisi olmayan, yalnızca Sınav Planları'nı gören hesap (ör. bölüm hesabı)."""

    def setUp(self):
        self.school = create_demo_school(institution=kurum())
        self.u = User.objects.create_user("bolum", password="x")
        with self.captureOnCommitCallbacks(execute=True):
            self.yetki = yetki_ver(self.u, "sinav-planlari", Yetki.GORUNTULEME, Yetki.BOLUM)
        self.client.force_login(self.u)
        self.url = reverse("sinav:periods", args=[self.school.pk])

    def test_yalniz_sinav_sayfalari_acilir(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Sınav dönemleri")
        for metin in ("Genel bakış", "Veri girişi", "Ortak veri", "data-palette-open"):
            self.assertNotContains(r, metin)
        sinav = reverse("dersprogrami_kopru:sinavlar")
        for url in (reverse("timetable:home"), reverse("timetable:school_detail", args=[self.school.pk]),
                    reverse("timetable:school_list"), reverse("timetable:events", args=[self.school.pk]),
                    reverse("timetable:institution_detail", args=[kurum().pk]),
                    reverse("timetable:data_list", args=[self.school.pk, "ogretmenler"])):
            self.assertRedirects(self.client.get(url), sinav, fetch_redirect_response=False)
        self.assertEqual(self.client.post(reverse("timetable:events", args=[self.school.pk]), {}).status_code, 403)
        r = self.client.get(reverse("sinav:home"))
        self.assertContains(r, self.school.name)
        self.assertNotContains(r, "Kurumlarım")

    def test_duzenleme_yetkisinde_ortak_veri_menude_yok(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.yetki.seviye = Yetki.DUZENLEME
            self.yetki.save()
        r = self.client.get(self.url)
        self.assertContains(r, "Sınav dönemleri")
        self.assertNotContains(r, "Ortak veri")

    def test_program_hazirlama_yetkisi_varsa_kisit_yok(self):
        with self.captureOnCommitCallbacks(execute=True):
            yetki_ver(self.u, "program-hazirlama", Yetki.GORUNTULEME)
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])).status_code, 200)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Modül değiştir")  # Ders Planlama ve Sınav Planlama arasında geçiş


class KunyeTests(TestCase):
    """Personel künyesi (PPYS V47Birlestir kuralı) modüldeki öğretmenin "ünvan / rütbe" alanına yazılır."""

    def setUp(self):
        from personel.models import Bolum, Secenek
        from timetable.models import School, Teacher

        S = Secenek
        self.og = S.objects.create(tur=S.SINIF, metin="Öğ.")
        self.utgm = S.objects.create(tur=S.RUTBE, metin="Ütğm.")
        self.yb = S.objects.create(tur=S.RUTBE, metin="Yb.")
        self.dr_uye = S.objects.create(tur=S.UNVAN, metin="Dr.Öğt.Üyesi", one_cikan=True)
        self.dr = S.objects.create(tur=S.UNVAN, metin="Dr.", one_cikan=False)
        self.ogtgor = S.objects.create(tur=S.UNVAN, metin="Öğt.Gör.", one_cikan=False)
        bil = Bolum.objects.create(ad="Bilgisayar", kod="BİL")
        self.okul = School.objects.create(name="Program", institution=kurum())
        self.ali = Personel.objects.create(ad_soyad="Ali KAYA", bolum=bil, sinif=self.og, rutbe=self.yb, unvan=self.dr_uye)
        self.veli = Personel.objects.create(ad_soyad="Veli ÇELİK", bolum=bil, sinif=self.og, rutbe=self.utgm, unvan=self.dr)
        self.ayse = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=bil, unvan=self.ogtgor)
        with self.captureOnCommitCallbacks(execute=True):
            self.t_ali = Teacher.objects.create(school=self.okul, first_name="Ali", last_name="Kaya")
            self.t_veli = Teacher.objects.create(school=self.okul, first_name="Veli", last_name="Çelik", title="elle yazılmış")
            self.t_ayse = Teacher.objects.create(school=self.okul, first_name="Ayşe", last_name="Yılmaz")
            self.t_yok = Teacher.objects.create(school=self.okul, first_name="Kimse", last_name="Yok", title="dokunulmaz")

    def unvan(self, t):
        t.refresh_from_db()
        return t.title

    def test_kural(self):
        self.assertEqual(self.ali.kunye, "Dr.Öğt.Üyesi Öğ.Yb.")  # unvan önde
        self.assertEqual(self.veli.kunye, "Öğ.Ütğm. Dr.")  # unvan sonda; sınıf ve rütbe bitişik
        self.assertEqual(self.ayse.kunye, "Öğt.Gör.")
        self.assertEqual(self.ali.tam_ad, "Dr.Öğt.Üyesi Öğ.Yb. Ali KAYA")  # KAMYOSİS ekranlarında da aynı kural
        from personel.models import Secenek
        topcu = Secenek.objects.create(tur=Secenek.SINIF, metin="Topçu")  # kısaltmasız sınıf: boşlukla
        self.assertEqual(Personel(ad_soyad="X", sinif=topcu, rutbe=self.utgm).kunye, "Topçu Ütğm.")

    def test_yeni_ogretmene_yazilir_eslesmeyene_dokunulmaz(self):
        self.assertEqual(self.unvan(self.t_ali), "Dr.Öğt.Üyesi Öğ.Yb.")
        self.assertEqual(self.unvan(self.t_veli), "Öğ.Ütğm. Dr.")  # KAMYOSİS kaynaktır
        self.assertEqual(self.unvan(self.t_ayse), "Öğt.Gör.")
        self.assertEqual(self.unvan(self.t_yok), "dokunulmaz")

    def test_personel_ve_secenek_degisince_guncellenir(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.ali.rutbe = self.utgm
            self.ali.save()
        self.assertEqual(self.unvan(self.t_ali), "Dr.Öğt.Üyesi Öğ.Ütğm.")
        with self.captureOnCommitCallbacks(execute=True):
            self.og.metin = "Öğr."
            self.og.save()
        self.assertEqual(self.unvan(self.t_veli), "Öğr.Ütğm. Dr.")
        with self.captureOnCommitCallbacks(execute=True):
            self.dr.one_cikan = True
            self.dr.save()
        self.assertEqual(self.unvan(self.t_veli), "Dr. Öğr.Ütğm.")
