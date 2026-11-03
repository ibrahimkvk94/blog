import datetime

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Birim, Yetki
from personel.models import Bolum, Personel
from sinav.models import Exam, ExamPeriod, ExamPlacement, ExamRoom
from timetable.models import Classroom, School, Subject, Teacher

from . import servis
from .models import SinavGorevi

CUMARTESI = datetime.date(2026, 11, 7)


class PuantajTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bil = Bolum.objects.create(ad="Bilgisayar Teknolojisi", kod="BİL")
        cls.elk = Bolum.objects.create(ad="Elektrik", kod="ELK")
        cls.ayse = Personel.objects.create(ad_soyad="Ayşe YILMAZ", bolum=cls.bil, sinav_rolleri="AG")
        cls.veli = Personel.objects.create(ad_soyad="Veli ÇELİK", bolum=cls.elk)
        plan = Birim.objects.get(slug="plan-program")
        cls.bilci = User.objects.create_user("bil", password="x-Parola-123", bolum=cls.bil)
        Yetki.objects.create(kullanici=cls.bilci, birim=plan, seviye=Yetki.DUZENLEME, kapsam=Yetki.BOLUM)
        cls.yonetici = User.objects.create_user("yon", password="x-Parola-123")
        Yetki.objects.create(kullanici=cls.yonetici, birim=plan, seviye=Yetki.YONETIM, kapsam=Yetki.TUM)
        okul = School.objects.create(name="Güz programı")
        cls.t_ayse = Teacher.objects.create(school=okul, first_name="Ayşe", last_name="Yılmaz")
        cls.t_veli = Teacher.objects.create(school=okul, first_name="Veli", last_name="Çelik")
        cls.t_dis = Teacher.objects.create(school=okul, first_name="Misafir", last_name="Hoca")
        cls.period = ExamPeriod.objects.create(school=okul, name="Güz vize", start_date=datetime.date(2026, 11, 2),
                                               end_date=CUMARTESI, sessions=["09:30", "11:00"], weekdays=[0, 1, 2, 3, 4, 5])
        exam = Exam.objects.create(period=cls.period, subject=Subject.objects.create(school=okul, name="Matematik"),
                                   duration=2)
        pl = ExamPlacement.objects.create(exam=exam, date=CUMARTESI, session=0)
        room = ExamRoom.objects.create(placement=pl, classroom=Classroom.objects.create(school=okul, name="A101"),
                                       seats=45, roles={str(cls.t_ayse.pk): "A"})
        room.proctors.set([cls.t_ayse, cls.t_veli, cls.t_dis])

    def test_yil_ekimde_baslar(self):
        self.assertEqual(servis.yil_baslangici(datetime.date(2026, 9, 30)), datetime.date(2025, 10, 1))
        self.assertEqual(servis.yil_baslangici(datetime.date(2026, 10, 1)), datetime.date(2026, 10, 1))

    def test_isleme_ve_puan(self):
        n, eslesmeyen = servis.isle(self.period, self.yonetici)
        self.assertEqual(n, 4)  # 2 kişi × 2 oturum; eşleşmeyen öğretmen işlenmez
        self.assertEqual(eslesmeyen, ["Misafir Hoca"])
        g = SinavGorevi.objects.filter(personel=self.ayse)
        self.assertEqual(sorted(g.values_list("saat", "rol")), [("09:30", "A"), ("11:00", "A")])
        pu = servis.puanlar(datetime.date(2026, 10, 1))
        self.assertEqual(pu[self.ayse.pk], {"hi": 0, "hs": 2, "puan": 3.0})
        # yeniden işleme çoğaltmaz; geri alma siler
        servis.isle(self.period, self.yonetici)
        self.assertEqual(SinavGorevi.objects.count(), 4)
        self.assertEqual(servis.geri_al(self.period), 4)

    def test_kanca_donemin_kendi_gorevlerini_saymaz(self):
        servis.isle(self.period, self.yonetici)
        SinavGorevi.objects.create(personel=self.ayse, tarih=datetime.date(2026, 11, 20), elle=True)
        onceki = servis.onceki_puanlar(self.period)
        self.assertEqual(onceki[self.t_ayse.pk], 1.0)  # ders yükü yok: z = 0
        self.assertEqual(onceki[self.t_veli.pk], 0.0)
        self.assertNotIn(self.t_dis.pk, onceki)

    def test_sayfa_ve_yetki(self):
        servis.isle(self.period, self.yonetici)
        self.client.force_login(self.yonetici)
        r = self.client.get(reverse("sinavgorev:puantaj"), {"yil": 2026})
        self.assertContains(r, "Ayşe YILMAZ")
        self.assertContains(r, "Veli ÇELİK")
        self.assertContains(r, "Güz vize")
        r = self.client.get(reverse("sinavgorev:puantaj"), {"yil": 2026, "indir": 1})
        self.assertEqual(r["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        # bölüm: yalnızca kendi bölümü, değişiklik yok
        self.client.force_login(self.bilci)
        r = self.client.get(reverse("sinavgorev:puantaj"), {"yil": 2026})
        self.assertContains(r, "Ayşe YILMAZ")
        self.assertNotContains(r, "Veli ÇELİK")
        self.assertEqual(self.client.post(reverse("sinavgorev:roller"), {"p": [self.ayse.pk]}).status_code, 403)
        self.assertEqual(self.client.get(reverse("sinavgorev:personel", args=[self.veli.pk])).status_code, 403)

    def test_modul_sayfasindaki_roller_personele_yazilir(self):
        from dersprogrami_kopru.kunye import kunyeleri_esitle

        kunyeleri_esitle()
        self.t_ayse.refresh_from_db()
        self.assertEqual(self.t_ayse.department, "BİL")  # bölüm süzgeci için
        self.client.force_login(User.objects.create_superuser("kok", password="x-Parola-123"))
        self.period.duty_roles = True
        self.period.save()
        url = reverse("sinav:proctors", args=[self.period.school_id, self.period.pk])
        # Ayşe muaf (rolleri boş), Veli salon amiri + gözetmen
        r = self.client.post(url, {"action": "exempt", "exempt": [self.t_ayse.pk],
                               f"role-{self.t_veli.pk}-A": "1", f"role-{self.t_veli.pk}-G": "1"})
        self.assertEqual(r.status_code, 302)
        self.ayse.refresh_from_db()
        self.veli.refresh_from_db()
        self.assertEqual((self.ayse.sinav_rolleri, self.veli.sinav_rolleri), ("", "AG"))

    def test_roller_ve_elle_gorev(self):
        self.client.force_login(self.yonetici)
        self.client.post(reverse("sinavgorev:roller"), {"p": [self.ayse.pk, self.veli.pk], f"rol-{self.ayse.pk}-T": "1"})
        self.ayse.refresh_from_db()
        self.veli.refresh_from_db()
        self.assertEqual((self.ayse.sinav_rolleri, self.veli.sinav_rolleri), ("T", ""))
        self.client.post(reverse("sinavgorev:elle_ekle"), {"personel": self.ayse.pk, "tarih": "2026-11-08", "rol": "G",
                                                           "adet": "2", "aciklama": "YDS"})
        self.assertEqual(servis.puanlar(datetime.date(2026, 10, 1))[self.ayse.pk]["puan"], 3.0)  # Pazar: 2 × 1,5
