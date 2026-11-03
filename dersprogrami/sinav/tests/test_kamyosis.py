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


class KisimProgramiTests(TestCase):
    def test_kisim_bilgisi(self):
        self.assertEqual(kurallar.kisim_bilgisi("10MKT"), ("MKT", 2))
        self.assertEqual(kurallar.kisim_bilgisi("56SVN"), ("SVN", 1))
        self.assertEqual(kurallar.kisim_bilgisi("13İNŞ"), ("İNŞ", 2))
        self.assertEqual(kurallar.kisim_bilgisi("40ELN"), ("ELN", None))  # aralık dışı
        self.assertEqual(kurallar.kisim_bilgisi("Hazırlık 1"), ("", None))

    def test_dagitim(self):
        siniflar = [SchoolClass(pk=i) for i in (1, 2, 3)]
        self.assertEqual(kurallar.kontenjan_dagit(100, siniflar), {1: 34, 2: 33, 3: 33})


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

    def test_gozetmen_aninda_kayit(self):
        t = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya")
        self.period.duty_roles = True
        self.period.save()
        self.client.force_login(User.objects.create_superuser("yon", password="x"))
        url = reverse("sinav:proctors", args=[self.school.pk, self.period.pk])
        r = self.client.post(url, {"action": "duty", "teacher": t.pk, "exempt": "0", "roles": "AG"})
        self.assertEqual(r.json(), {"ok": True, "exempt": False, "roles": "AG"})
        r = self.client.post(url, {"action": "duty", "teacher": t.pk, "exempt": "1", "roles": ""})
        self.period.refresh_from_db()
        self.assertEqual((self.period.roles_of(t.pk), list(self.period.proctor_exempt.all())), ("", [t]))

    def test_program_kontenjani(self):
        exams.generate_from_lessons(self.period)
        u = User.objects.create_superuser("yon", password="x")
        self.client.force_login(u)
        url = reverse("sinav:courses", args=[self.school.pk])
        self.assertContains(self.client.get(url), "Kısımlara program ve sınıf ata")
        self.client.post(url, {"action": "assign_programs"})
        self.c1.refresh_from_db()
        self.assertEqual((self.c1.program, self.c1.grade), ("SVN", 2))
        self.client.post(url, {"action": "save_quotas", "kontenjan-SVN|2": "81"})
        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual((self.c1.student_count, self.c2.student_count), (41, 40))
        self.assertEqual(Exam.objects.get(period=self.period).student_count, 81)  # sınav sayısı yenilendi
        dosya = _xlsx([["Program", "Sınıf", "Kontenjan"], ["svn", "2. sınıf", 60], ["MKT", 1, 10]])
        r = self.client.post(url, {"action": "import_quotas", "dosya": dosya}, follow=True)
        self.assertContains(r, "MKT 1. sınıf")
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.student_count, 30)


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


class GorevKuraliTests(TestCase):
    """Görev rolleri (salon amiri / gözetmen / taşıyıcı), "mümkünse verilmesin", önceki puanla denge."""

    def _p(self, exams_, proctors, rooms=(100,), days=1, sessions=1, **kw):
        return exams_solver.Problem(
            n_days=days, n_sessions=sessions, exams=exams_,
            rooms=[exams_solver.PRoom(i, f"S{i}", c) for i, c in enumerate(rooms)],
            proctors=list(proctors), max_per_day=2, proctors_per_room=1, time_limit=10, workers=2, **kw)

    def _gorevler(self, r, eid):
        _t0, rows = r.placements[eid]
        out = []
        for _rid, _seats, teachers, roles in rows:
            out += [(t, roles.get(t, "G")) for t in teachers]
        return out

    def test_ihtiyac(self):
        p = self._p([], [], duty_roles=True)
        self.assertEqual(exams_solver.duty_need(p, 0), {"G": 1})
        self.assertEqual(exams_solver.duty_need(p, 39), {"G": 1, "T": 1})
        self.assertEqual(exams_solver.duty_need(p, 40), {"A": 1, "G": 2, "T": 1})
        self.assertEqual(exams_solver.duty_need(p, 61), {"A": 1, "G": 4, "T": 1})
        self.assertEqual(exams_solver.duty_need(self._p([], []), 61), {"G": 1})

    def test_roller_uygun_ogretmene(self):
        # 45 öğrenci: 1 amir, 3 gözetmen, 1 taşıyıcı; yalnızca 1 amir olabilir, 9 taşıyıcı olabilir
        roles = {1: "A", 9: "T", 2: "G", 3: "G", 4: "G"}
        p = self._p([exams_solver.PExam(1, "S", classes=(1,), students=45)], roles, duty_roles=True, roles=roles)
        r = exams_solver.solve(p)
        self.assertEqual(sorted(self._gorevler(r, 1)), [(1, "A"), (2, "G"), (3, "G"), (4, "G"), (9, "T")])
        self.assertEqual(r.status, "ok")

    def test_ogrenci_sayisi_yoksa_uyarir(self):
        roles = {t: "AGT" for t in range(1, 8)}
        p = self._p([exams_solver.PExam(1, "S", classes=(1,), students=0)], roles, rooms=(50,), duty_roles=True,
                    roles=roles)
        r = exams_solver.solve(p)
        self.assertEqual([rol for _t, rol in self._gorevler(r, 1)], ["G"])
        self.assertIn("kontenjanı", r.warnings[0])

    def test_mumkunse_verilmesin(self):
        p = self._p([exams_solver.PExam(1, "S", classes=(1,), students=10)], [1, 2], soft={1: {0}})
        r = exams_solver.solve(p)
        self.assertEqual(self._gorevler(r, 1), [(2, "G")])
        # tek seçenek oysa yine de verilir
        p = self._p([exams_solver.PExam(1, "S", classes=(1,), students=10)], [1], soft={1: {0}})
        self.assertEqual(self._gorevler(exams_solver.solve(p), 1), [(1, "G")])

    def test_onceki_puan_dengesi(self):
        # 2 oturum, 2 öğretmen, oturum başına 1 gözetmen: önceki puanı yüksek olan görev almaz
        exams_ = [exams_solver.PExam(1, "A", classes=(1,), students=10, fixed=0),
                  exams_solver.PExam(2, "B", classes=(2,), students=10, fixed=1)]
        p = self._p(exams_, [1, 2], sessions=2, prior={1: 8})
        r = exams_solver.solve(p)
        self.assertEqual(self._gorevler(r, 1) + self._gorevler(r, 2), [(2, "G"), (2, "G")])

    def test_hafta_sonu_agirligi(self):
        self.assertEqual(exams_solver._weight(self._p([], [], weekend=frozenset({1})), (0, 1)), 5)
        self.assertEqual(exams_solver._water_level([0, 4], 6), 5)


class GorevDegisikligiTests(TestCase):
    def setUp(self):
        from sinav.models import ExamPlacement, ExamRoom

        inst = Institution.objects.create(name="Kurum")
        self.school = School.objects.create(name="Program", institution=inst)
        self.t = {ad: Teacher.objects.create(school=self.school, first_name=ad, last_name="Hoca") for ad in "ABCD"}
        self.period = ExamPeriod.objects.create(school=self.school, name="Vize", start_date=MONDAY, end_date=MONDAY,
                                                sessions=["09:30", "11:00"], duty_roles=True,
                                                proctor_roles={str(self.t["D"].pk): "T"})
        salon = Classroom.objects.create(school=self.school, name="S1", capacity=80)
        salon2 = Classroom.objects.create(school=self.school, name="S2", capacity=80)
        self.oda = {}
        for i, (ad, oturum, salon_) in enumerate((("Mat", 0, salon), ("Fiz", 1, salon2))):
            e = Exam.objects.create(period=self.period, subject=Subject.objects.create(school=self.school, name=ad))
            pl = ExamPlacement.objects.create(exam=e, date=MONDAY, session=oturum)
            self.oda[ad] = ExamRoom.objects.create(placement=pl, classroom=salon_, seats=20)
        self.oda["Mat"].proctors.set([self.t["A"]])
        self.oda["Fiz"].proctors.set([self.t["B"]])

    def test_baskasina_ver_ve_kayit(self):
        from sinav import gorev_degisikligi as gd

        b = gd.Baglam(self.period)
        anahtar = f"{self.oda['Mat'].pk}:{self.t['A'].pk}"
        durum = {a["teacher"].first_name: a["engel"] for a in b.adaylar(anahtar)}
        self.assertEqual(durum["C"], [])
        self.assertEqual(durum["D"], ["gözetmen olamaz"])  # yalnızca taşıyıcı
        with self.assertRaises(gd.DegisiklikHatasi):
            gd.baskasina_ver(self.period, anahtar, self.t["C"].pk, None, "  ")  # gerekçe zorunlu
        self.period.proctor_blocks = {str(self.t["C"].pk): [MONDAY.isoformat()]}
        self.period.save()
        with self.assertRaises(gd.DegisiklikHatasi):
            gd.baskasina_ver(self.period, anahtar, self.t["C"].pk, None, "raporlu")  # gelemeyeceği gün
        kayit = gd.baskasina_ver(self.period, anahtar, self.t["B"].pk, None, "raporlu")
        self.assertEqual(list(self.oda["Mat"].proctors.all()), [self.t["B"]])
        self.assertTrue(self.oda["Mat"].placement.__class__.objects.get(pk=self.oda["Mat"].placement_id).locked)
        self.assertIn("A Hoca → B Hoca", kayit.summary)

    def test_takas_ve_sayfa(self):
        from sinav import gorev_degisikligi as gd

        a1 = f"{self.oda['Mat'].pk}:{self.t['A'].pk}"
        a2 = f"{self.oda['Fiz'].pk}:{self.t['B'].pk}"
        self.assertEqual([x["anahtar"] for x in gd.Baglam(self.period).takaslar(a1)], [a2])
        self.client.force_login(User.objects.create_superuser("yon", password="x"))
        url = reverse("sinav:duties", args=[self.school.pk, self.period.pk])
        self.assertContains(self.client.get(url, {"gorev": a1}), "Takas et")
        r = self.client.post(url, {"action": "swap", "gorev": a1, "diger": a2, "neden": "karşılıklı istek"}, follow=True)
        self.assertContains(r, "Takas: A Hoca")
        self.assertEqual(list(self.oda["Mat"].proctors.all()), [self.t["B"]])
        self.assertEqual(list(self.oda["Fiz"].proctors.all()), [self.t["A"]])
        self.assertContains(self.client.get(url), "karşılıklı istek")


class OturumDuzeniTests(TestCase):
    """Oturum düzeni 2,1,…: her oturum bir düzeyin; o düzeyin her bölümü tam bir sınavda."""

    def test_duzen_mukerrer_eksik(self):
        E = exams_solver.PExam
        sinavlar = [
            E(1, "Mat 1", classes=(10, 11, 12), students=10, year=1, programs=frozenset({"SVN", "MKT", "ELN"})),
            E(2, "Fiz 1", classes=(10, 11, 12), students=10, year=1, programs=frozenset({"SVN", "MKT", "ELN"})),
            E(3, "Taktik", classes=(20,), students=10, year=2, programs=frozenset({"SVN"})),
            E(4, "Hidrolik", classes=(21,), students=10, year=2, programs=frozenset({"MKT"})),
            E(5, "Analog", classes=(22,), students=10, year=2, programs=frozenset({"ELN"})),
            E(6, "Malzeme", classes=(23,), students=10, year=2, programs=frozenset({"MKT"})),  # MKT'nin başka kısmı
        ]
        p = exams_solver.Problem(
            n_days=1, n_sessions=4, exams=sinavlar, rooms=[exams_solver.PRoom(i, f"S{i}", 100) for i in range(4)],
            proctors=[], max_per_day=2, proctors_per_room=0, time_limit=10, workers=2,
            session_years=(2, 1, 2, 1), programs_by_year={1: {"SVN", "MKT", "ELN"}, 2: {"SVN", "MKT", "ELN"}})
        r = exams_solver.solve(p)
        oturum = {eid: t for eid, (t, _) in r.placements.items()}
        self.assertEqual(len(oturum), 6)
        for eid in (1, 2):
            self.assertIn(oturum[eid], (1, 3))  # 1. sınıf oturumları
        for eid in (3, 4, 5, 6):
            self.assertIn(oturum[eid], (0, 2))  # 2. sınıf oturumları
        self.assertNotEqual(oturum[4], oturum[6])  # MKT'nin iki sınavı aynı oturumda değil (mükerrer yok)
        # eksik bölüm en az: iki 2. sınıf oturumunda toplam 6 bölüm yerinden 4 sınav → en az 2 eksik
        eksik = sum(3 - len({pr for e in sinavlar if oturum[e.id] == t for pr in e.programs}) for t in (0, 2))
        self.assertEqual(eksik, 2)

    def test_duzey_kisimdan(self):
        siniflar = [SchoolClass(grade=2), SchoolClass(grade=2)]
        self.assertEqual(kurallar.sinav_duzeyi(siniflar, "TEM101"), 2)
        self.assertEqual(kurallar.sinav_duzeyi([SchoolClass(grade=1), SchoolClass(grade=2)], "TEM101"), 1)  # karışık: koddan
