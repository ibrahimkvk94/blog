"""Esnek raporlar: tüm rapor türleri, seçenekler ve kayıtlı şablonlar."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import duty
from timetable.models import DutyPlace, ReportPreset, SchoolClass
from timetable.services import generate_timetable
from timetable.tests.test_operations import build_school


class ReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = build_school()
        cls.timetable = generate_timetable(cls.school, "ilk", time_limit=10)
        DutyPlace.objects.create(school=cls.school, name="Bahçe")
        duty.generate(cls.school, cls.timetable)
        cls.user = User.objects.create_superuser("rapor", password="parola-123456")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("timetable:report_render", args=[self.timetable.pk])

    def get(self, query):
        response = self.client.get(self.url + "?" + query)
        self.assertEqual(response.status_code, 200, query)
        return response

    def test_all_report_types_render(self):
        self.assertContains(self.get("tur=bireysel&varlik=sinif"), "9-A")
        self.assertContains(self.get("tur=bireysel&varlik=ogretmen&gunler=satir&sayfa=4"), "per-4")
        self.assertContains(self.get("tur=carsaf&varlik=ogretmen"), "Öğretmenler")
        self.assertContains(self.get("tur=carsaf_gun&varlik=sinif&gun=2"), "Çarşamba")
        self.assertContains(self.get("tur=yuk"), "Matematik")
        self.assertContains(self.get("tur=sinif_dersleri"), "Türkçe")
        self.assertContains(self.get("tur=bos_derslik"), "Boş derslikler")
        self.assertContains(self.get("tur=bos_ogretmen"), "Boş öğretmenler")
        self.assertContains(self.get("tur=nobet"), "Bahçe")

    def test_every_report_type_exports_to_pdf(self):
        url = reverse("timetable:report_pdf", args=[self.timetable.pk])
        queries = ["tur=bireysel&varlik=sinif", "tur=bireysel&varlik=ogretmen&gunler=satir&yon=dikey&boyut=buyuk",
                   "tur=carsaf&varlik=ogretmen", "tur=carsaf_gun&varlik=sinif&gun=2", "tur=yuk", "tur=sinif_dersleri",
                   "tur=bos_derslik", "tur=bos_ogretmen", "tur=nobet", "tur=uybs", "tur=bireysel&icerik_set=1&alt=Okul+M%C3%BCd%C3%BCr%C3%BC"]
        for query in queries:
            response = self.client.get(url + "?" + query)
            self.assertEqual(response.status_code, 200, query)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertTrue(response.content.startswith(b"%PDF"), query)
            self.assertIn(b"DejaVuSans", response.content)  # Türkçe karakterler için gömülü yazı tipi
        self.assertIn("rapor-yuk-", self.client.get(url + "?tur=yuk")["Content-Disposition"])
        empty = self.client.get(url + "?tur=bireysel&secim=999999")
        self.assertTrue(empty.content.startswith(b"%PDF"))
        page = self.client.get(reverse("timetable:reports", args=[self.timetable.pk]))
        self.assertContains(page, "PDF indir")

    def test_pdf_fits_one_page_per_entity(self):
        from timetable import report_pdf, reports

        o = reports.options({"tur": "bireysel", "varlik": "sinif"})
        data = reports.build(self.timetable, o)
        count = sum(len(g) for g in data["pages"])
        pdf = report_pdf.build(data)
        self.assertEqual(pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page "), count)

    def test_selection_content_and_options(self):
        cls = SchoolClass.objects.get(school=self.school, name="9-B")
        page = self.get(f"tur=bireysel&varlik=sinif&secim={cls.pk}&ders_adi=kisa&icerik_set=1&yon=dikey&alt=Okul+M%C3%BCd%C3%BCr%C3%BC")
        html = page.content.decode()
        self.assertIn("<h1>9-B</h1>", html)
        self.assertNotIn("<h1>9-A</h1>", html)
        self.assertIn("portrait", html)
        self.assertIn("Okul Müdürü", html)
        self.assertNotIn("Derslik 9-B</span>", html)  # içerik seçilmedi
        self.assertIn(' bw"', self.get("tur=bireysel&icerik_set=1").content.decode())  # renk işaretsiz → siyah-beyaz

    def test_page_and_presets(self):
        page = self.client.get(reverse("timetable:reports", args=[self.timetable.pk]) + "?tur=carsaf&varlik=ogretmen")
        self.assertContains(page, "report-frame")
        self.client.post(reverse("timetable:reports", args=[self.timetable.pk]), {"name": "Öğretmen çarşafı", "tur": "carsaf", "varlik": "ogretmen", "icerik": ["sinif"]})
        preset = ReportPreset.objects.get(school=self.school)
        self.assertEqual(preset.params["tur"], "carsaf")
        self.assertEqual(preset.params["icerik"], ["sinif"])
        page = self.client.get(reverse("timetable:reports", args=[self.timetable.pk]))
        self.assertContains(page, "Öğretmen çarşafı")
        self.assertContains(page, "tur=carsaf")
        self.client.post(reverse("timetable:reports", args=[self.timetable.pk]), {"action": "delete_preset", "preset": preset.pk})
        self.assertFalse(ReportPreset.objects.exists())

    def test_sheet_rows_per_lesson_columns_and_signature(self):
        from timetable import report_excel, report_pdf, reports
        from timetable.models import Teacher

        teacher = Teacher.objects.filter(school=self.school, lessons__isnull=False).distinct().first()
        Teacher.objects.filter(pk=teacher.pk).update(department="Mat.", title="Öğr.Gör. Yb.")
        query = (f"tur=carsaf&varlik=ogretmen&secim={teacher.pk}&icerik_set=1&satir=ders&hucre=kisim&kisim_ad=no"
                 "&sutun_ders=1&sutun_kod=1&sutun_saat=1&kunye=unvan&alt=Ad+SOYAD%0AYb.%0AOkul+M%C3%BCd%C3%BCr%C3%BC%0Afazla")
        html = self.get(query).content.decode()
        self.assertIn("Öğr.Gör. Yb. " + teacher.full_name, html)
        self.assertNotIn("Mat. ", html)
        self.assertIn("Ders kodu", html)
        self.assertIn("Toplam", html)
        self.assertNotIn("fazla", html)  # imza en fazla 3 satır
        o = reports.options(dict(p.split("=", 1) for p in query.replace("%0A", "\n").replace("+", " ").split("&")) | {"secim": [teacher.pk], "kunye": ["unvan"]})
        data = reports.build(self.timetable, o)
        rows = data["sheet_rows"]
        subjects = {l.subject_id for l in teacher.lessons.all()}
        self.assertEqual(len(rows), len(subjects), [(r["title"], r["pre"]) for r in rows])  # her ders ayrı satır, ad her satırda
        self.assertTrue(all(r["title"].startswith("Öğr.Gör. Yb.") for r in rows))
        self.assertEqual(sum(r["post"][0] for r in rows), rows[0]["post"][1])  # ders saatleri toplamı = toplam
        self.assertTrue(report_pdf.build(data).startswith(b"%PDF"))
        self.assertTrue(report_excel.build(data))

    def test_class_number_labels(self):
        cases = {"70.KISIM": "70", "70. KISIM": "70", "Hazırlık 1": "H1", "9-A": "9"}
        for name, expected in cases.items():
            self.assertEqual(SchoolClass(name=name).number_label(), expected, name)

    def test_same_code_variant_gets_own_row(self):
        """Aynı kodlu "(U)" dersi ayrı satırda kalır (ek ders hesabı buna bakılarak yapılır)."""
        from timetable import reports
        from timetable.models import Subject

        teacher = self.school.teachers.filter(lessons__isnull=False).distinct().first()
        lessons = list(teacher.lessons.select_related("subject")[:2])
        if len(lessons) < 2 or lessons[0].subject_id == lessons[1].subject_id:
            self.skipTest("öğretmenin iki farklı dersi yok")
        Subject.objects.filter(pk=lessons[0].subject_id).update(short="BİL211", name="Bilgisayar Programlama Dili")
        Subject.objects.filter(pk=lessons[1].subject_id).update(short="BİL211", name="Bilgisayar Programlama Dili (U)")
        o = reports.options({"tur": "carsaf", "varlik": "ogretmen", "satir": "ders", "sutun_ders": "1", "secim": [teacher.pk]})
        names = [r["pre"][0] for r in reports.build(self.timetable, o)["sheet_rows"]]
        self.assertIn("Bilgisayar Programlama Dili", names)
        self.assertIn("Bilgisayar Programlama Dili (U)", names)

    def test_kunye_in_separate_columns(self):
        from timetable import report_excel, report_pdf, reports
        from timetable.models import Teacher

        teacher = Teacher.objects.filter(school=self.school, lessons__isnull=False).distinct().first()
        Teacher.objects.filter(pk=teacher.pk).update(department="Mat.", title="Öğr.Gör. Yb.")
        o = reports.options({"tur": "carsaf", "varlik": "ogretmen", "kunye_yer": "sutun", "kunye": ["bolum", "unvan"],
                             "sutun_ders": "1", "secim": [teacher.pk], "icerik_set": "1"})
        data = reports.build(self.timetable, o)
        self.assertEqual(data["lead_headers"], ["Bölüm", "Ünvan / Rütbe"])  # addan önce
        self.assertEqual(data["pre_headers"], ["Ders adı"])
        row = data["sheet_rows"][0]
        self.assertEqual(row["title"], teacher.full_name)
        self.assertEqual(row["lead"], ["Mat.", "Öğr.Gör. Yb."])
        self.assertTrue(report_pdf.build(data).startswith(b"%PDF"))
        self.assertTrue(report_excel.build(data))
        load = reports.build(self.timetable, {**o, "tur": "yuk"})
        self.assertEqual(load["kunye_headers"], ["Bölüm", "Ünvan / Rütbe"])
        self.assertTrue(report_excel.build(load) and report_pdf.build(load))

    def test_teachers_sorted_by_department_then_name(self):
        from timetable import reports
        from timetable.models import Teacher

        teachers = list(Teacher.objects.filter(school=self.school)[:3])
        Teacher.objects.filter(pk=teachers[0].pk).update(department="")
        Teacher.objects.filter(pk=teachers[1].pk).update(department="Mat.")
        Teacher.objects.filter(pk=teachers[2].pk).update(department="Fiz.")
        o = reports.options({"tur": "carsaf", "varlik": "ogretmen", "secim": [t.pk for t in teachers]})
        order = [r["title"] for r in reports.build(self.timetable, o)["sheet_rows"] if r["first"]]
        self.assertEqual(order[:2], ["Fiz. " + teachers[2].full_name, "Mat. " + teachers[1].full_name])
        self.assertEqual(order[-1], teachers[0].full_name)  # bölümü boş olan sonda
        self.assertEqual(sorted(["Şule", "Can", "Çağrı", "Zeki"], key=reports.tr_key), ["Can", "Çağrı", "Şule", "Zeki"])
