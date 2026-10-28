"""Veri giriş ekranlarının testleri."""

import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from timetable.data_views import ENTITIES
from timetable.demo import create_demo_school
from timetable.models import Availability, Division, Group, Lesson, Period, School, SchoolClass, Teacher


class DataEntryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.user = User.objects.create_superuser("veri", password="parola-123456")

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name, *args):
        return reverse(f"timetable:{name}", args=[self.school.pk, *args])

    def test_all_pages_render(self):
        for slug, entity in ENTITIES.items():
            self.assertEqual(self.client.get(self.url("data_list", slug)).status_code, 200, slug)
            self.assertEqual(self.client.get(self.url("data_new", slug)).status_code, 200, slug)
            obj = entity.model.objects.filter(school=self.school).first()
            if obj:
                self.assertEqual(self.client.get(self.url("data_edit", slug, obj.pk)).status_code, 200, slug)
        cls = self.school.classes.first()
        for name, args in (("lessons", ()), ("lesson_new", ()), ("school_settings", ()), ("class_lessons", (cls.pk,))):
            self.assertEqual(self.client.get(self.url(name, *args)).status_code, 200, name)
        lesson = self.school.lessons.first()
        self.assertContains(self.client.get(self.url("lesson_edit", lesson.pk)), lesson.subject.name)
        self.assertEqual(self.client.get(reverse("timetable:school_create")).status_code, 200)

    def test_teacher_with_availability(self):
        response = self.client.post(
            self.url("data_new", "ogretmenler"),
            {
                "first_name": "Deniz", "last_name": "Yıldız", "short": "DYI", "max_days_per_week": "3",
                "availability": json.dumps({"0-0": "no", "0-1": "maybe", "9-9": "no", "1-2": "bad"}),
            },
        )
        teacher = Teacher.objects.get(short="DYI")
        self.assertRedirects(response, self.url("data_edit", "ogretmenler", teacher.pk))  # kaydedince kayıtta kalınır
        self.assertEqual(teacher.max_days_per_week, 3)
        states = dict(((a.day, a.period), a.state) for a in Availability.objects.filter(teacher=teacher))
        self.assertEqual(states, {(0, 0): "no", (0, 1): "maybe"})

        # Düzenlemede ızgara baştan yazılır.
        self.client.post(
            self.url("data_edit", "ogretmenler", teacher.pk),
            {"first_name": "Deniz", "last_name": "Yıldız", "short": "DYI", "availability": json.dumps({"4-7": "no"})},
        )
        self.assertEqual(list(Availability.objects.filter(teacher=teacher).values_list("day", "period")), [(4, 7)])

    def test_class_divisions_editor_keeps_group_ids(self):
        cls = self.school.classes.get(name="9-A")
        division = cls.divisions.first()
        german = division.groups.get(name="Almanca")
        french = division.groups.get(name="Fransızca")
        payload = [
            {"id": division.id, "name": "Dil", "groups": [{"id": german.id, "name": "Almanca"}, {"id": french.id, "name": "Fransızca B"}]},
            {"id": None, "name": "Beden", "groups": [{"id": None, "name": "Kız"}, {"id": None, "name": "Erkek"}]},
            {"id": None, "name": "Tek grup", "groups": [{"id": None, "name": "Yalnız"}]},
        ]
        self.client.post(
            self.url("data_edit", "siniflar", cls.pk),
            {"name": "9-A", "grade": "9", "home_classroom": cls.home_classroom_id, "divisions": json.dumps(payload)},
        )
        self.assertEqual(sorted(cls.divisions.values_list("name", flat=True)), ["Beden", "Dil"])
        self.assertEqual(Group.objects.get(pk=french.pk).name, "Fransızca B")
        self.assertTrue(Lesson.objects.filter(groups=german).exists())  # derslerdeki grup bağı korunur

        payload = [{"id": division.id, "name": "Dil", "groups": [{"id": german.id, "name": "Almanca"}, {"id": None, "name": "İspanyolca"}]}]
        self.client.post(
            self.url("data_edit", "siniflar", cls.pk),
            {"name": "9-A", "grade": "9", "home_classroom": cls.home_classroom_id, "divisions": json.dumps(payload)},
        )
        self.assertFalse(Group.objects.filter(pk=french.pk).exists())
        self.assertEqual(Division.objects.filter(school_class=cls).count(), 1)

    def test_lesson_form_validates_groups(self):
        a, b = self.school.classes.get(name="9-A"), self.school.classes.get(name="10-A")
        group_b = Group.objects.filter(division__school_class=b).first()
        subject = self.school.subjects.first()
        response = self.client.post(
            self.url("lesson_new"),
            {"subject": subject.pk, "classes": [a.pk], "groups": [group_b.pk], "periods_per_week": "2", "card_length": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "seçilen sınıflardan birine ait değil")

        before = Lesson.objects.count()
        response = self.client.post(
            self.url("lesson_new"),
            {"subject": subject.pk, "classes": [a.pk, b.pk], "teachers": [self.school.teachers.first().pk], "periods_per_week": "3", "card_length": "2"},
        )
        self.assertRedirects(response, self.url("lesson_edit", Lesson.objects.latest("pk").pk))
        self.assertEqual(Lesson.objects.count(), before + 1)
        lesson = Lesson.objects.latest("id")
        self.assertEqual(lesson.card_lengths(), [2, 1])
        self.assertEqual(set(lesson.classes.all()), {a, b})

    def test_lesson_form_rejects_other_school_objects(self):
        other = School.objects.create(name="Başka okul")
        foreign = SchoolClass.objects.create(school=other, name="X")
        response = self.client.post(
            self.url("lesson_new"),
            {"subject": self.school.subjects.first().pk, "classes": [foreign.pk], "periods_per_week": "1", "card_length": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lesson.objects.filter(classes=foreign).exists())

    def test_class_lessons_quick_table(self):
        cls = self.school.classes.get(name="10-B")
        subjects = {s.short: s for s in self.school.subjects.all()}
        teacher = self.school.teachers.get(short="ACE")
        data = {}
        for subject in subjects.values():
            data[f"hours-{subject.pk}"] = ""
        data[f"hours-{subjects['MAT'].pk}"] = "4"
        data[f"length-{subjects['MAT'].pk}"] = "2"
        data[f"teacher-{subjects['MAT'].pk}"] = str(teacher.pk)
        data[f"hours-{subjects['ALM'].pk}"] = "3"  # yeni basit ders
        response = self.client.post(self.url("class_lessons", cls.pk), data)
        self.assertRedirects(response, self.url("class_lessons", cls.pk))

        def simple(lesson):
            return lesson.classes.count() == 1 and not lesson.groups.exists() and lesson.classrooms.count() <= 1

        by_subject = {l.subject.short: l for l in Lesson.objects.filter(classes=cls) if simple(l)}
        self.assertEqual(set(by_subject), {"MAT", "ALM"})  # boş bırakılan basit dersler silindi
        # İki laboratuvar seçeneği olan dersler tabloda düzenlenmez ve korunur.
        self.assertTrue(Lesson.objects.filter(classes=cls, subject__short="KİM").exists())
        self.assertEqual((by_subject["MAT"].periods_per_week, by_subject["MAT"].card_length), (4, 2))
        self.assertEqual(list(by_subject["MAT"].teachers.all()), [teacher])
        # Gruplu birleşik dersler tablodan etkilenmez.
        self.assertTrue(Lesson.objects.filter(classes=cls, groups__isnull=False).exists())

    def test_school_settings_periods(self):
        periods = list(self.school.periods.all())
        data = {
            "name": self.school.name, "days_per_week": "5", "weeks_count": "1", "terms_count": "1",
            "periods-TOTAL_FORMS": str(len(periods) + 1), "periods-INITIAL_FORMS": str(len(periods)),
            "periods-MIN_NUM_FORMS": "0", "periods-MAX_NUM_FORMS": "1000",
        }
        for i, p in enumerate(periods):
            data.update({f"periods-{i}-id": str(p.pk), f"periods-{i}-name": p.name, f"periods-{i}-start_time": p.start_time.strftime("%H:%M"), f"periods-{i}-end_time": p.end_time.strftime("%H:%M")})
        data["periods-1-DELETE"] = "on"
        n = len(periods)
        data.update({f"periods-{n}-id": "", f"periods-{n}-name": "", f"periods-{n}-start_time": "16:00", f"periods-{n}-end_time": "16:40"})
        response = self.client.post(self.url("school_settings"), data)
        self.assertRedirects(response, self.url("school_settings"))
        indices = list(Period.objects.filter(school=self.school).values_list("index", flat=True))
        self.assertEqual(indices, list(range(len(periods))))
        last = Period.objects.filter(school=self.school).last()
        self.assertEqual((last.name, last.start_time.strftime("%H:%M")), (f"{len(periods)}. saat", "16:00"))

    def test_create_school_gets_default_periods(self):
        response = self.client.post(reverse("timetable:school_create"), {"name": "Yeni Lise", "days_per_week": "5", "weeks_count": "1", "terms_count": "1"})
        school = School.objects.get(name="Yeni Lise")
        self.assertRedirects(response, reverse("timetable:school_settings", args=[school.pk]))
        self.assertEqual(school.periods.count(), 8)

    def test_delete_class_removes_its_own_lessons_only(self):
        cls = self.school.classes.get(name="9-A")
        joint = Lesson.objects.filter(classes=cls, groups__isnull=False).first()
        response = self.client.post(self.url("data_delete", "siniflar", cls.pk))
        self.assertRedirects(response, self.url("data_list", "siniflar"))
        self.assertFalse(SchoolClass.objects.filter(pk=cls.pk).exists())
        self.assertTrue(Lesson.objects.filter(pk=joint.pk).exists())  # 9-B ile ortak ders kalır


class ExcelAndLessonAvailabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.user = User.objects.create_superuser("excel", password="parola-123456")

    def setUp(self):
        self.client.force_login(self.user)

    def test_lesson_availability_is_saved(self):
        lesson = self.school.lessons.first()
        data = {
            "subject": lesson.subject_id, "classes": [c.pk for c in lesson.classes.all()],
            "teachers": [t.pk for t in lesson.teachers.all()], "periods_per_week": lesson.periods_per_week,
            "card_length": lesson.card_length, "availability": json.dumps({"4-6": "no", "4-7": "no"}),
        }
        response = self.client.post(reverse("timetable:lesson_edit", args=[self.school.pk, lesson.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sorted(Availability.objects.filter(lesson=lesson).values_list("period", flat=True)), [6, 7])
        page = self.client.get(reverse("timetable:lesson_edit", args=[self.school.pk, lesson.pk]))
        self.assertContains(page, "availability-data")

    def test_round_trip_into_empty_school(self):
        from timetable import importer
        from timetable.services import check_school

        first = self.school.teachers.first()
        type(first).objects.filter(pk=first.pk).update(department="ELN", title="Öğr.Gör. Ütğm.")
        data = importer.export_workbook(self.school)
        target = School.objects.create(name="Boş okul")
        from timetable.data_views import default_periods

        default_periods(target)
        result = importer.import_workbook(target, data)
        self.assertEqual(result["Dersler"]["eklenen"], self.school.lessons.count())
        self.assertEqual(target.teachers.count(), self.school.teachers.count())
        copied = target.teachers.get(first_name=first.first_name, last_name=first.last_name)
        self.assertEqual((copied.department, copied.title), ("ELN", "Öğr.Gör. Ütğm."))  # künye aktarımda korunur
        self.assertEqual(target.classrooms.count(), self.school.classrooms.count())
        self.assertEqual(Group.objects.filter(division__school_class__school=target).count(), 8)
        joint = Lesson.objects.filter(school=target, groups__isnull=False).distinct()
        self.assertEqual(joint.count(), 4)
        self.assertTrue(all(l.classes.count() == 2 and l.groups.count() == 2 for l in joint))
        self.assertFalse([i for i in check_school(target) if i.level == "error"])

        # Aynı dosyayı tekrar yüklemek kayıt çoğaltmaz, yalnızca günceller.
        again = importer.import_workbook(target, data)
        self.assertEqual(again["Dersler"].get("eklenen", 0), 0)
        self.assertEqual(target.lessons.count(), self.school.lessons.count())

    def test_errors_roll_back_everything(self):
        from io import BytesIO

        from openpyxl import Workbook

        from timetable import importer

        wb = Workbook()
        ws = wb.active
        ws.title = "Öğretmenler"
        ws.append(importer.SHEETS["Öğretmenler"])
        ws.append(["Yeni", "Öğretmen", "YNO", 6, None, None])
        lessons = wb.create_sheet("Dersler")
        lessons.append(importer.SHEETS["Dersler"])
        lessons.append(["Olmayan Ders", "9-A", "", "YNO", "", 2, 1, None])
        buffer = BytesIO()
        wb.save(buffer)
        response = self.client.post(
            reverse("timetable:excel_import", args=[self.school.pk]),
            {"file": SimpleUploadedFile("veri.xlsx", buffer.getvalue())},
        )
        self.assertContains(response, "Dersler, satır 2")
        self.assertContains(response, "“Olmayan Ders” ders adı bulunamadı")
        self.assertFalse(Teacher.objects.filter(short="YNO").exists())  # öğretmen satırı da geri alındı

    def test_excel_pages(self):
        self.assertContains(self.client.get(reverse("timetable:excel_import", args=[self.school.pk])), "Excel dosyasını indir")
        response = self.client.get(reverse("timetable:excel_export", args=[self.school.pk]))
        self.assertIn("spreadsheetml", response["Content-Type"])
        upload = SimpleUploadedFile("veri.xlsx", response.content)
        response = self.client.post(reverse("timetable:excel_import", args=[self.school.pk]), {"file": upload})
        self.assertRedirects(response, reverse("timetable:excel_import", args=[self.school.pk]))


class DistributionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.user = User.objects.create_superuser("dagitim", password="parola-123456")

    def setUp(self):
        self.client.force_login(self.user)

    def post_json(self, name, payload):
        return self.client.post(reverse(f"timetable:{name}", args=[self.school.pk]), json.dumps(payload), content_type="application/json")

    def test_page_renders_matrix_data(self):
        response = self.client.get(reverse("timetable:distribution", args=[self.school.pk]))
        self.assertContains(response, "dist-data")
        data = response.context["data"]
        cls = self.school.classes.get(name="9-A")
        mat = self.school.subjects.get(short="MAT")
        self.assertEqual(data["cells"][f"{mat.pk}-{cls.pk}"]["hours"], 6)
        alm = self.school.subjects.get(short="ALM")
        self.assertEqual(data["complex"][f"{alm.pk}-{cls.pk}"], 2)  # birleşik/gruplu ders matrise girmez

    def test_bulk_save(self):
        cls_a, cls_b = self.school.classes.get(name="9-A"), self.school.classes.get(name="10-B")
        mat, muz = self.school.subjects.get(short="MAT"), self.school.subjects.get(short="MÜZ")
        teacher = self.school.teachers.get(short="ACE")
        response = self.post_json("distribution_save", {"cells": [
            {"subject": mat.pk, "class": cls_a.pk, "hours": 5, "length": 1, "teacher": teacher.pk},   # güncelle
            {"subject": muz.pk, "class": cls_b.pk, "hours": 0},                                        # sil
            {"subject": self.school.subjects.get(short="REH").pk, "class": cls_b.pk, "hours": 2, "teacher": None},  # güncelle
        ]})
        self.assertEqual(response.json()["ok"], True)
        lesson = Lesson.objects.get(subject=mat, classes=cls_a)
        self.assertEqual((lesson.periods_per_week, lesson.card_length, list(lesson.teachers.all())), (5, 1, [teacher]))
        self.assertFalse(Lesson.objects.filter(subject=muz, classes=cls_b).exists())

    def test_paste_preview_and_apply(self):
        text = (
            "Öğretmen\tDers\tSınıflar\tSaat\tBlok\n"
            "Zeynep Kaya\tMatematik\t9-A, 9-B\t4\t2\n"
            "Yeni Öğretmen Adı\tAstronomi\t10-A 10-B\t1\n"
            "Kimse\tTarih\t9-A\t2\n"
            "Ali Çelik\tMatematik\t11-Z\t3\n"
        )
        preview = self.post_json("distribution_paste", {"text": text}).json()
        self.assertFalse(preview["applied"])
        self.assertEqual(len(preview["rows"]), 4)
        self.assertEqual(preview["errors"], 2)
        self.assertIn("yeni öğretmen", preview["rows"][1]["notes"])
        self.assertIn("yeni ders adı", preview["rows"][1]["notes"])
        self.assertEqual(preview["rows"][1]["classes"], ["10-A", "10-B"])
        # Hatalı satır varken aktarılmaz.
        self.assertFalse(self.post_json("distribution_paste", {"text": text, "apply": True}).json()["applied"])

        good = "\n".join(text.splitlines()[:3])
        result = self.post_json("distribution_paste", {"text": good, "apply": True}).json()
        self.assertTrue(result["applied"])
        teacher = Teacher.objects.get(first_name="Yeni Öğretmen", last_name="Adı")
        astro = Lesson.objects.filter(subject__name="Astronomi")
        self.assertEqual(astro.count(), 2)
        self.assertTrue(all(list(l.teachers.all()) == [teacher] for l in astro))
        mat = Lesson.objects.get(subject__short="MAT", classes__name="9-B")
        self.assertEqual((mat.periods_per_week, mat.card_length), (4, 2))
