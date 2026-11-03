"""KAMYOSİS sınav kuralları: ders koduna göre sınav, %100 UYG hariç, zorluk ve tür sırası, aynı ad aynı gün,
oturumda tek sınıf düzeyi, Excel aktarımı ve "Ders sınav bilgileri" sayfası (bkz. sinav/kurallar.py)."""

import datetime
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from sinav import kurallar
from sinav import services as exams
from sinav import solver as exams_solver
from sinav.models import Exam, ExamCourse, ExamPeriod
from timetable.models import Classroom, Institution, Lesson, Period, School, SchoolClass, Subject, Teacher

User = get_user_model()
MONDAY = datetime.date(2026, 11, 2)


def _xlsx(rows):
    from openpyxl import Workbook

    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    out = BytesIO()
    wb.save(out)
    return SimpleUploadedFile("veri.xlsx", out.getvalue())


class KuralTests(TestCase):
    def test_tur(self):
        self.assertEqual(kurallar.tur_normalize("40% mt+60%uyg"), "%40 MT + %60 UYG")
        self.assertEqual(kurallar.tur_ailesi("%100 UYG"), kurallar.UYG)
        self.assertTrue(kurallar.plana_alinmaz("% 100 uyg"))
        self.assertEqual(kurallar.tur_ailesi("%40 MT + %60 UYG"), kurallar.MT)
        self.assertEqual(kurallar.tur_ailesi("%100 CS"), kurallar.CS)
        self.assertEqual(kurallar.tur_ailesi(""), kurallar.DIGER)

    def test_ad_yil_zorluk(self):
        self.assertEqual(kurallar.temel_ad("Askerî Harekâtın Yönetimi 1 (SVN)"), kurallar.temel_ad("Askerî  Harekâtın Yönetimi 1"))
        self.assertEqual([kurallar.sinif_yili(k) for k in ("BİL103", "ASK201", "TBE", "T3")], [1, 2, None, None])
        self.assertEqual((kurallar.zorluk(None), kurallar.zorluk("5"), kurallar.zorluk(9)), (3, 5, 3))


class UretimTests(TestCase):
    def setUp(self):
        inst = Institution.objects.create(name="Kurum")
        self.school = School.objects.create(name="Program", institution=inst)
        self.c1 = SchoolClass.objects.create(school=self.school, name="1.KISIM", short="1SVN", student_count=30)
        self.c2 = SchoolClass.objects.create(school=self.school, name="2.KISIM", short="2SVN", student_count=20)
        # aynı kodlu iki ders adı (bölüme göre ayrı yazılmış): tek sınav
        for c, ad in ((self.c1, "Matematik"), (self.c2, "Matematik (SVN)")):
            s = Subject.objects.create(school=self.school, name=ad, short="TBE101")
            Lesson.objects.create(school=self.school, subject=s, periods_per_week=2).classes.set([c])
        uyg = Subject.objects.create(school=self.school, name="Atış", short="ASK105")
        Lesson.objects.create(school=self.school, subject=uyg, periods_per_week=2).classes.set([self.c1])
        ExamCourse.objects.create(institution=inst, code="ASK105", exam_type="%100 UYG")
        self.period = ExamPeriod.objects.create(school=self.school, name="Vize", start_date=MONDAY, end_date=MONDAY)

    def test_ders_koduna_gore_ve_uyg_haric(self):
        self.assertEqual(exams.generate_from_lessons(self.period), 1)
        exam = Exam.objects.get(period=self.period)
        self.assertEqual((exam.code, exam.classes.count(), exam.student_count), ("TBE101", 2, 50))
        self.assertEqual(exams.generate_from_lessons(self.period, replace=False), 0)  # aynı kod yeniden eklenmez

    def test_ayri_sinav_kodla_secilir(self):
        self.assertEqual(exams.generate_from_lessons(self.period, separate=["TBE101"]), 2)

    def test_sonradan_uyg_olan_plana_girmez(self):
        exams.generate_from_lessons(self.period)
        ExamCourse.objects.create(institution=self.school.institution, code="TBE101", exam_type="%100 UYG")
        problem, _ = exams.build_problem(self.period)
        self.assertEqual(problem.exams, [])

    def test_excel_aktarimi_ve_sayfa(self):
        Classroom.objects.create(school=self.school, name="Salon", capacity=60)
        u = User.objects.create_superuser("yon", password="x")
        self.client.force_login(u)
        url = reverse("sinav:courses", args=[self.school.pk])
        self.assertContains(self.client.get(url), "TBE101")
        dosya = _xlsx([["Liste"], ["Ders Kodu", "Ders Adı", "Sınav Türü", "Zorluk"], ["TBE101", "Matematik", "40% mt + 60% uyg", 5],
                       ["XYZ999", "Yok", "%100 ÇS", None]])
        r = self.client.post(url, {"action": "import_courses", "dosya": dosya}, follow=True)
        self.assertContains(r, "bulunamayan 1 ders")
        c = ExamCourse.objects.get(code="TBE101")
        self.assertEqual((c.exam_type, c.difficulty), ("%40 MT + %60 UYG", 5))
        dosya = _xlsx([["Kısım", "Kontenjan"], ["1SVN", 45], ["2.kısım", "25"], ["9XYZ", 10]])
        r = self.client.post(url, {"action": "import_quotas", "dosya": dosya}, follow=True)
        self.assertContains(r, "9XYZ")
        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual((self.c1.student_count, self.c2.student_count), (45, 25))
        r = self.client.get(url, {"indir": "dersler"})
        self.assertEqual(r["Content-Type"].split(";")[0], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _problem(exams_, days=3, sessions=1, rooms=(200,)):
    return exams_solver.Problem(
        n_days=days, n_sessions=sessions, exams=exams_, rooms=[exams_solver.PRoom(i, f"S{i}", c) for i, c in enumerate(rooms)],
        proctors=[], max_per_day=2, proctors_per_room=0, time_limit=10, workers=2)


def _gun(result, eid, sessions=1):
    return result.placements[eid][0] // sessions


class CozucuTercihTests(TestCase):
    def test_zor_sinav_once(self):
        # aynı sınıf, günde tek oturum: zorluğu 5 olan ilk güne
        p = _problem([exams_solver.PExam(1, "Kolay", classes=(1,), students=10, difficulty=1),
                      exams_solver.PExam(2, "Zor", classes=(1,), students=10, difficulty=5)], days=2)
        r = exams_solver.solve(p)
        self.assertEqual((_gun(r, 2), _gun(r, 1)), (0, 1))

    def test_esit_zorlukta_mt_once_cs_sonra(self):
        p = _problem([exams_solver.PExam(1, "ÇS", classes=(1,), students=10, family="ÇS"),
                      exams_solver.PExam(2, "MT", classes=(1,), students=10, family="MT")], days=2)
        r = exams_solver.solve(p)
        self.assertEqual((_gun(r, 2), _gun(r, 1)), (0, 1))

    def test_ayni_ad_ayni_gun(self):
        # biri 2. güne sabit: aynı adlı diğeri de (erken gün tercihine rağmen) 2. güne
        p = _problem([exams_solver.PExam(1, "Harekât 1", classes=(1,), students=10, base_name="harekât 1", fixed=1),
                      exams_solver.PExam(2, "Harekât 1 (SVN)", classes=(2,), students=10, base_name="harekât 1")],
                     days=3, rooms=(200, 200))
        r = exams_solver.solve(p)
        self.assertEqual(_gun(r, 2), 1)

    def test_oturumda_tek_sinif_duzeyi(self):
        p = _problem([exams_solver.PExam(i, f"S{i}", classes=(i,), students=10, year=1 if i < 3 else 2) for i in range(1, 5)],
                     days=1, sessions=2, rooms=(50, 50))
        r = exams_solver.solve(p)
        oturum = {eid: t for eid, (t, _) in r.placements.items()}
        self.assertEqual(oturum[1], oturum[2])
        self.assertEqual(oturum[3], oturum[4])
        self.assertNotEqual(oturum[1], oturum[3])
