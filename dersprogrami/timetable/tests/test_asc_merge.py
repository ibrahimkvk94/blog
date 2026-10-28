"""aSc XML'ini var olan programın üzerine güncelleyerek aktarma (asc_merge)."""

import xml.etree.ElementTree as ET

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from timetable import asc_merge, asc_xml
from timetable.demo import create_demo_school
from timetable.models import (
    Availability,
    Card,
    CardRelationship,
    Group,
    Institution,
    Lesson,
    LessonRef,
    School,
    Teacher,
    Timetable,
)


def place_all(school):
    """Çözücü çalıştırmadan basit bir yerleşim: her dersin kartları farklı günlere konur."""
    timetable = Timetable.objects.create(school=school, name="Elle", status=Timetable.OK)
    cards = []
    for n, lesson in enumerate(school.lessons.order_by("id")):
        for i, length in enumerate(lesson.card_lengths()):
            cards.append(Card(timetable=timetable, lesson=lesson, length=length, day=i % 5, period=n % (9 - length)))
    Card.objects.bulk_create(cards)
    return timetable


def edit_xml(data, change):
    root = ET.fromstring(data)
    change(root)
    return ET.tostring(root, encoding="utf-8")


def drop_lessons(root, lesson_ids):
    ids = {f"L{pk}" for pk in lesson_ids}
    for table, tag in (("lessons", "lesson"), ("cards", "card")):
        parent = root.find(table)
        for row in list(parent.findall(tag)):
            if row.get("id" if tag == "lesson" else "lessonid") in ids:
                parent.remove(row)


class AscMergeTests(TestCase):
    def setUp(self):
        self.institution = Institution.objects.create(name="Kurum")
        self.school = create_demo_school(institution=self.institution)
        self.timetable = place_all(self.school)
        self.school.active_timetable = self.timetable
        self.school.save(update_fields=["active_timetable"])
        self.math = self.school.lessons.get(subject__short="MAT", classes__name="9-A")
        cls = self.math.classes.get()
        LessonRef.objects.bulk_create(
            LessonRef(lesson=self.math, school_class=cls, ordinal=i, ref=f"10{i:02d}") for i in range(1, 7)
        )
        self.teacher = Teacher.objects.get(school=self.school, short="ZKA")
        self.teacher.target_periods = 21
        self.teacher.save(update_fields=["target_periods"])

    def export(self):
        return asc_xml.export_school(self.school, self.timetable)

    def test_round_trip_keeps_everything(self):
        lessons = set(self.school.lessons.values_list("pk", flat=True))
        teachers = set(self.school.teachers.values_list("pk", flat=True))
        groups = set(Group.objects.filter(division__school_class__school=self.school).values_list("pk", flat=True))
        availability = Availability.objects.filter(school=self.school).count()
        schools = School.objects.count()

        timetable, summary = asc_merge.merge_into(self.school, self.export())

        self.assertEqual(School.objects.count(), schools)  # geçici program silindi
        self.assertEqual(set(self.school.lessons.values_list("pk", flat=True)), lessons)
        self.assertEqual(set(self.school.teachers.values_list("pk", flat=True)), teachers)
        self.assertEqual(set(Group.objects.filter(division__school_class__school=self.school).values_list("pk", flat=True)), groups)
        self.assertEqual(LessonRef.objects.filter(lesson=self.math).count(), 6)
        self.assertEqual(Availability.objects.filter(school=self.school).count(), availability)
        self.assertEqual(CardRelationship.objects.filter(school=self.school).count(), 1)
        self.assertEqual(self.school.duty_places.count(), 2)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.max_periods_per_day, 6)  # aSc'de olmayan alanlar korunur
        self.assertEqual(self.teacher.target_periods, 21)
        self.assertEqual(Teacher.objects.get(school=self.school, short="MPO").max_days_per_week, 2)
        self.assertEqual(self.school.classes.get(name="9-A").divisions.get().name, "Yabancı dil 2")
        for kind, _ in asc_merge.KINDS:
            stats = summary[kind]
            self.assertEqual((stats["added"], stats["updated"], stats["removed"], stats["kept"]), (0, 0, 0, []), kind)
        self.assertEqual(summary["refs_dropped"], 0)

        # Yerleşim yeni sürüm olarak açılır; eski sürüm ve yayındaki program yerinde kalır.
        self.assertIsNotNone(timetable)
        self.assertEqual(timetable.school, self.school)
        self.assertTrue(timetable.name.startswith("aSc güncelleme"))
        self.assertEqual(timetable.versions.count(), 1)
        self.assertTrue(Timetable.objects.filter(pk=self.timetable.pk).exists())
        self.school.refresh_from_db()
        self.assertEqual(self.school.active_timetable, self.timetable)
        old = sorted((c.lesson_id, c.day, c.period, c.length) for c in self.timetable.cards.all())
        new = sorted((c.lesson_id, c.day, c.period, c.length) for c in timetable.cards.all())
        self.assertEqual(new, old)
        self.assertIn("Veride değişiklik yok", asc_merge.describe(summary))

    def test_changed_periods_update_lesson_and_trim_refs(self):
        def change(root):
            root.find("lessons").find(f"lesson[@id='L{self.math.pk}']").set("periodsperweek", "4.0")
            root.find("teachers").find(f"teacher[@id='T{self.teacher.pk}']").set("lastname", "Kaya-Yıldız")

        _, summary = asc_merge.merge_into(self.school, edit_xml(self.export(), change))
        self.math.refresh_from_db()
        self.assertEqual(self.math.periods_per_week, 4)
        self.assertEqual(list(LessonRef.objects.filter(lesson=self.math).values_list("ordinal", flat=True)), [1, 2, 3, 4])
        self.assertEqual(summary["refs_dropped"], 2)
        self.assertEqual(summary["lessons"]["updated"], 1)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.last_name, "Kaya-Yıldız")  # kısa adla eşleşti, ad güncellendi
        self.assertEqual(self.teacher.target_periods, 21)
        self.assertEqual(summary["teachers"]["updated"], 1)

    def test_removed_lesson_and_unused_teacher_are_deleted(self):
        german = list(self.school.lessons.filter(subject__short="ALM").values_list("pk", flat=True))
        music = self.school.lessons.get(subject__short="MÜZ", classes__name="9-A")
        LessonRef.objects.create(lesson=music, school_class=music.classes.get(), ordinal=1, ref="X")
        mpo = Teacher.objects.get(school=self.school, short="MPO")

        def change(root):
            drop_lessons(root, german + [music.pk])
            teachers = root.find("teachers")
            teachers.remove(teachers.find(f"teacher[@id='T{mpo.pk}']"))

        timetable, summary = asc_merge.merge_into(self.school, edit_xml(self.export(), change))
        self.assertFalse(Lesson.objects.filter(pk__in=german + [music.pk]).exists())
        self.assertEqual(summary["lessons"]["removed"], 3)
        self.assertEqual(summary["refs_dropped"], 1)
        self.assertFalse(Teacher.objects.filter(pk=mpo.pk).exists())
        self.assertEqual(summary["teachers"]["removed_names"], [mpo.full_name])
        # ALM ders adı dosyada duruyor; Almanca grupları da dosyada olduğu için korunur.
        self.assertTrue(self.school.subjects.filter(short="ALM").exists())
        self.assertEqual(Group.objects.filter(division__school_class__school=self.school, name="Almanca").count(), 4)
        self.assertFalse(timetable.cards.filter(lesson__subject__short="ALM").exists())
        self.assertIn("ÜYBS referansı silindi", asc_merge.describe(summary))

    def test_new_teacher_and_lesson_are_added(self):
        cls = self.school.classes.get(name="9-B")
        music = self.school.subjects.get(short="MÜZ")

        def change(root):
            ET.SubElement(root.find("teachers"), "teacher", id="TNEW", firstname="Yeni", lastname="Hoca", short="YNH")
            ET.SubElement(
                root.find("lessons"), "lesson", id="LNEW", classids=f"C{cls.pk}", groupids=f"G{cls.pk}_0",
                subjectid=f"S{music.pk}", periodspercard="1", periodsperweek="3.0", teacherids="TNEW", classroomids="",
                weeksdefid="WALL", termsdefid="PALL", daysdefid="D0",
            )

        _, summary = asc_merge.merge_into(self.school, edit_xml(self.export(), change))
        teacher = Teacher.objects.get(school=self.school, short="YNH")
        lesson = self.school.lessons.get(teachers=teacher)
        self.assertEqual((lesson.periods_per_week, list(lesson.classes.all())), (3, [cls]))
        self.assertEqual(lesson.availabilities.count(), 4 * 8)  # yalnızca Pazartesi (daysdef)
        self.assertEqual((summary["teachers"]["added"], summary["lessons"]["added"]), (1, 1))

    def test_view_update_mode_is_default_and_replace_still_works(self):
        user = User.objects.create_superuser("yonetici", password="parola-123456")
        self.client.force_login(user)
        url = reverse("timetable:program_import", args=[self.institution.pk])
        lessons = set(self.school.lessons.values_list("pk", flat=True))

        response = self.client.post(url, {"file": SimpleUploadedFile("asc.xml", self.export()), "target": self.school.pk}, follow=True)
        self.assertContains(response, "güncellenerek aktarıldı")
        self.assertTrue(School.objects.filter(pk=self.school.pk).exists())
        self.assertEqual(set(self.school.lessons.values_list("pk", flat=True)), lessons)
        self.assertEqual(LessonRef.objects.filter(lesson=self.math).count(), 6)
        self.assertEqual(self.school.timetables.count(), 2)

        page = self.client.get(reverse("timetable:institution_detail", args=[self.institution.pk]))
        self.assertContains(page, "Güncelleyerek aktar")

        self.client.post(url, {"file": SimpleUploadedFile("asc.xml", self.export()), "target": self.school.pk, "mode": "replace"})
        self.assertFalse(School.objects.filter(pk=self.school.pk).exists())
        replaced = School.objects.get(institution=self.institution, name=self.school.name)
        self.assertEqual(replaced.lessons.count(), len(lessons))
        self.assertFalse(LessonRef.objects.filter(lesson__school=replaced).exists())

    def test_real_asc_file_reimport_matches_case_insensitively(self):
        from timetable.tests.test_asc_import import SAMPLE

        school, _ = asc_xml.import_school(SAMPLE, name="MYO", institution=self.institution)
        teacher = school.teachers.get(last_name="KAYA")
        teacher.short = "ydl ayşe kaya"  # elle küçük harfe çevrilmiş
        teacher.max_gaps_per_day = 1
        teacher.save()
        lessons = set(school.lessons.values_list("pk", flat=True))
        _, summary = asc_merge.merge_into(school, SAMPLE)
        self.assertEqual(set(school.lessons.values_list("pk", flat=True)), lessons)
        teacher.refresh_from_db()
        self.assertEqual((teacher.short, teacher.max_gaps_per_day), ("YDL Ayşe KAYA", 1))
        self.assertEqual(summary["teachers"]["added"], 0)
        self.assertEqual(summary["lessons"]["added"], 0)
        self.assertEqual(school.timetables.count(), 2)

    def test_invalid_file_changes_nothing(self):
        with self.assertRaises(asc_xml.AscImportError):
            asc_merge.merge_into(self.school, b"<html/>")
        self.assertEqual(School.objects.count(), 1)
