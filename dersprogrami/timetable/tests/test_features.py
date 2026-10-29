"""aSc kılavuzundan eklenen veri özelliklerinin testleri: kart dağılımı, sınıfsız ders, varsayılan
derslikler, çok derslikli ders, okul geneli kapalı saatler, branş, sınıf öğretmeni, bölünme kopyalama."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import editing, importer
from timetable.demo import create_demo_school
from timetable.models import (
    Availability,
    Card,
    Classroom,
    Division,
    Group,
    Lesson,
    Period,
    School,
    SchoolClass,
    Subject,
    Teacher,
)
from timetable.services import check_school, generate_timetable, verify_timetable
from timetable.solver.builder import build_problem


def small_school(periods=6):
    school = School.objects.create(name="Küçük okul", days_per_week=5)
    for i in range(periods):
        Period.objects.create(school=school, index=i, name=f"{i + 1}. saat")
    return school


class SplitTests(TestCase):
    def test_parse_split(self):
        self.assertEqual(Lesson.parse_split("2+2+1"), [2, 2, 1])
        self.assertEqual(Lesson.parse_split("2111"), [2, 1, 1, 1])
        self.assertEqual(Lesson.parse_split("2, 1 ,1"), [2, 1, 1])
        self.assertEqual(Lesson.parse_split("2+x"), [])
        self.assertEqual(Lesson.parse_split("2+0"), [])

    def test_card_lengths_use_split_when_sum_matches(self):
        school = small_school()
        subject = Subject.objects.create(school=school, name="Matematik")
        lesson = Lesson.objects.create(school=school, subject=subject, periods_per_week=5, card_length=2, split="1+2+1+1")
        self.assertEqual(lesson.card_lengths(), [2, 1, 1, 1])
        lesson.split = "2+2"  # toplam tutmuyor → kart uzunluğuna göre
        self.assertEqual(lesson.card_lengths(), [2, 2, 1])


class BuilderFeatureTests(TestCase):
    def setUp(self):
        self.school = small_school()
        self.cls = SchoolClass.objects.create(school=self.school, name="9-A")
        self.other = SchoolClass.objects.create(school=self.school, name="9-B")
        self.subject = Subject.objects.create(school=self.school, name="Fizik", short="FİZ")
        self.teacher = Teacher.objects.create(school=self.school, first_name="Ayşe", last_name="Yılmaz")
        self.teacher2 = Teacher.objects.create(school=self.school, first_name="Can", last_name="Demir")
        self.lab = Classroom.objects.create(school=self.school, name="Lab")
        self.home = Classroom.objects.create(school=self.school, name="Derslik 9-A")
        self.home_b = Classroom.objects.create(school=self.school, name="Derslik 9-B")
        self.teacher_room = Classroom.objects.create(school=self.school, name="Ayşe'nin odası")
        self.cls.home_classroom = self.home
        self.cls.save()
        self.other.home_classroom = self.home_b
        self.other.save()

    def lesson(self, classes=(), teachers=(), hours=1, **kwargs):
        lesson = Lesson.objects.create(school=self.school, subject=self.subject, periods_per_week=hours, **kwargs)
        lesson.classes.set(classes)
        lesson.teachers.set(teachers)
        return lesson

    def card_of(self, problem, lesson):
        return next(c for c in problem.cards if c.lesson_id == lesson.id)

    def test_room_resolution_order(self):
        lesson = self.lesson([self.cls], [self.teacher])
        self.assertEqual(self.card_of(build_problem(self.school), lesson).room_options, (self.home.id,))
        self.teacher.home_classroom = self.teacher_room
        self.teacher.save()
        self.assertEqual(self.card_of(build_problem(self.school), lesson).room_options, (self.teacher_room.id,))
        self.subject.classrooms.set([self.lab])
        self.assertEqual(self.card_of(build_problem(self.school), lesson).room_options, (self.lab.id,))
        lesson.classrooms.set([self.home_b])
        self.assertEqual(self.card_of(build_problem(self.school), lesson).room_options, (self.home_b.id,))

    def test_lesson_without_class_is_a_teacher_meeting(self):
        meeting = self.lesson([], [self.teacher, self.teacher2])
        problem = build_problem(self.school)
        card = self.card_of(problem, meeting)
        self.assertEqual(card.atoms, ())
        self.assertEqual(set(card.teachers), {self.teacher.id, self.teacher2.id})
        self.assertIn("Ayşe Yılmaz", problem.label("lesson", meeting.id))
        self.assertFalse([i for i in check_school(self.school) if i.level == "error"])
        timetable = generate_timetable(self.school, "t", time_limit=10)
        self.assertEqual(timetable.cards.filter(day__isnull=False).count(), 1)

    def test_lesson_with_nothing_is_an_error(self):
        self.lesson([], [])
        self.assertIn("no_class", {i.code for i in check_school(self.school)})

    def test_school_wide_closed_cells(self):
        lesson = self.lesson([self.cls], [self.teacher])
        Availability.objects.create(school=self.school, day=4, period=5)
        Availability.objects.create(school=self.school, day=4, period=4)
        problem = build_problem(self.school)
        starts = set(self.card_of(problem, lesson).starts)
        self.assertNotIn((4, 5), starts)
        self.assertNotIn((4, 4), starts)
        self.assertIn((4, 3), starts)
        self.assertEqual(problem.teacher_available[self.teacher.id], 28)

    def test_rooms_needed_assigns_distinct_rooms(self):
        joined = self.lesson([self.cls, self.other], [self.teacher, self.teacher2], hours=3, rooms_needed=2)
        problem = build_problem(self.school)
        card = self.card_of(problem, joined)
        self.assertEqual(set(card.room_options), {self.home.id, self.home_b.id})
        self.assertEqual(card.rooms_needed, 2)
        timetable = generate_timetable(self.school, "t", time_limit=10)
        for db_card in timetable.cards.all():
            self.assertEqual(set(db_card.room_ids), {self.home.id, self.home_b.id})
        violations, _ = verify_timetable(timetable)
        self.assertEqual(violations, [])

        # Elle taşımada iki derslik de atanır; başka dersin dersliği doluysa o kart çıkarılır.
        single = self.lesson([self.other], [self.teacher2])
        timetable = generate_timetable(self.school, "t2", time_limit=10)
        moving = timetable.cards.get(lesson=single)
        target = timetable.cards.filter(lesson=joined).first()
        result = editing.move_card(moving, target.day, target.period)
        self.assertTrue(result["ok"])
        self.assertIn(target.id, result["displaced"])

    def test_rooms_needed_more_than_options_is_an_error(self):
        self.lesson([self.cls], [self.teacher], rooms_needed=2)  # yalnızca sınıf dersliği var
        self.assertIn("rooms_needed", {i.code for i in check_school(self.school)})

    def test_out_of_branch_warning(self):
        other_subject = Subject.objects.create(school=self.school, name="Kimya")
        self.teacher.subjects.set([other_subject])
        self.lesson([self.cls], [self.teacher])
        issues = check_school(self.school)
        self.assertIn("out_of_branch", {i.code for i in issues if i.level == "warning"})


class FeatureViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.user = User.objects.create_superuser("ozellik", password="parola-123456")

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name, *args):
        return reverse(f"timetable:{name}", args=[self.school.pk, *args])

    def test_lesson_form_split_and_meeting(self):
        subject = self.school.subjects.first()
        teachers = list(self.school.teachers.all()[:2])
        response = self.client.post(self.url("lesson_new"), {
            "subject": subject.pk, "teachers": [t.pk for t in teachers], "periods_per_week": "1", "card_length": "1",
        })
        meeting = Lesson.objects.filter(school=self.school, classes__isnull=True).get()
        self.assertRedirects(response, self.url("lesson_edit", meeting.pk))
        self.assertEqual(meeting.teachers.count(), 2)

        cls = self.school.classes.first()
        response = self.client.post(self.url("lesson_new"), {
            "subject": subject.pk, "classes": [cls.pk], "periods_per_week": "5", "card_length": "1", "split": "2 2 2",
        })
        self.assertContains(response, "eşit olmalı")
        response = self.client.post(self.url("lesson_new"), {
            "subject": subject.pk, "classes": [cls.pk], "periods_per_week": "5", "card_length": "1", "split": "221",
        })
        self.assertRedirects(response, self.url("lesson_edit", Lesson.objects.get(split="2+2+1").pk))

        response = self.client.post(self.url("lesson_new"), {"subject": subject.pk, "periods_per_week": "1", "card_length": "1"})
        self.assertContains(response, "En az bir sınıf")

    def test_settings_save_school_closed_hours(self):
        page = self.client.get(self.url("school_settings"))
        self.assertContains(page, "Okul geneli kapalı saatler")
        data = {
            "name": self.school.name, "days_per_week": "5", "weeks_count": "1", "terms_count": "1",
            "periods-TOTAL_FORMS": "0", "periods-INITIAL_FORMS": "0", "periods-MIN_NUM_FORMS": "0", "periods-MAX_NUM_FORMS": "1000",
            "availability": json.dumps({"4-7": "no", "4-6": "maybe"}),
        }
        # Ders saatleri formu boş gönderilirse kayıt reddedilir; mevcut saatleri ekleyelim.
        periods = list(self.school.periods.all())
        data["periods-TOTAL_FORMS"] = data["periods-INITIAL_FORMS"] = str(len(periods))
        for i, p in enumerate(periods):
            data.update({
                f"periods-{i}-id": p.pk, f"periods-{i}-name": p.name,
                f"periods-{i}-start_time": p.start_time.strftime("%H:%M"), f"periods-{i}-end_time": p.end_time.strftime("%H:%M"),
            })
        response = self.client.post(self.url("school_settings"), data)
        self.assertRedirects(response, self.url("school_settings"))
        rows = Availability.objects.filter(school=self.school, teacher__isnull=True, school_class__isnull=True,
                                           classroom__isnull=True, subject__isnull=True, lesson__isnull=True)
        self.assertEqual(sorted((a.day, a.period, a.state) for a in rows), [(4, 6, "maybe"), (4, 7, "no")])

    def test_copy_divisions(self):
        source = self.school.classes.get(name="10-A")
        target = self.school.classes.get(name="9-A")
        Division.objects.filter(school_class=target).delete()
        names = {d.name: sorted(g.name for g in d.groups.all()) for d in source.divisions.all()}
        self.assertTrue(names)
        response = self.client.post(self.url("copy_divisions", source.pk), {"targets": [target.pk]})
        self.assertRedirects(response, self.url("data_edit", "siniflar", source.pk))
        copied = {d.name: sorted(g.name for g in d.groups.all()) for d in target.divisions.all()}
        self.assertEqual(copied, names)
        # Yeniden kopyalamak grupları çoğaltmaz.
        self.client.post(self.url("copy_divisions", source.pk), {"targets": [target.pk]})
        self.assertEqual(Group.objects.filter(division__school_class=target).count(), sum(len(g) for g in names.values()))

    def test_new_fields_on_forms_and_lists(self):
        teacher = self.school.teachers.first()
        subject = self.school.subjects.first()
        response = self.client.post(self.url("data_edit", "ogretmenler", teacher.pk), {
            "first_name": teacher.first_name, "last_name": teacher.last_name, "short": teacher.short,
            "target_periods": "18", "subjects": [subject.pk],
        })
        self.assertRedirects(response, self.url("data_edit", "ogretmenler", teacher.pk))
        teacher.refresh_from_db()
        self.assertEqual(teacher.target_periods, 18)
        self.assertEqual(list(teacher.subjects.all()), [subject])
        page = self.client.get(self.url("data_list", "ogretmenler"))
        self.assertContains(page, "Hedef yük")
        self.assertContains(page, "18 saat")

        cls = self.school.classes.first()
        response = self.client.post(self.url("data_edit", "siniflar", cls.pk), {"name": cls.name, "class_teacher": teacher.pk})
        self.assertRedirects(response, self.url("data_edit", "siniflar", cls.pk))
        self.assertContains(self.client.get(self.url("data_list", "siniflar")), teacher.full_name)

    def test_excel_round_trip_of_new_columns(self):
        teacher = self.school.teachers.first()
        teacher.target_periods = 20
        teacher.save()
        teacher.subjects.set(self.school.subjects.all()[:2])
        cls = self.school.classes.first()
        cls.class_teacher = teacher
        cls.student_count = 28
        cls.save()
        lesson = self.school.lessons.filter(periods_per_week=5).first()
        lesson.split = "2+2+1"
        lesson.save()
        data = importer.export_workbook(self.school)

        target = School.objects.create(name="Kopya")
        importer.import_workbook(target, data)
        copy = Teacher.objects.get(school=target, first_name=teacher.first_name, last_name=teacher.last_name)
        self.assertEqual(copy.target_periods, 20)
        self.assertEqual(copy.subjects.count(), 2)
        copy_cls = SchoolClass.objects.get(school=target, name=cls.name)
        self.assertEqual((copy_cls.class_teacher, copy_cls.student_count), (copy, 28))
        self.assertTrue(Lesson.objects.filter(school=target, split="2+2+1").exists())


class AdvisorTests(TestCase):
    def setUp(self):
        self.school = small_school()
        self.cls = SchoolClass.objects.create(school=self.school, name="9-A")
        division = Division.objects.create(school_class=self.cls, name="Dil")
        self.g1 = Group.objects.create(division=division, name="Almanca")
        self.g2 = Group.objects.create(division=division, name="Fransızca")
        self.teacher = Teacher.objects.create(school=self.school, first_name="A", last_name="B")

    def lesson(self, name, groups, hours, length=1):
        subject, _ = Subject.objects.get_or_create(school=self.school, name=name)
        lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=hours, card_length=length)
        lesson.classes.set([self.cls])
        lesson.groups.set(groups)
        lesson.teachers.set([self.teacher])
        return lesson

    def codes(self):
        return {i.code: i.level for i in check_school(self.school)}

    def test_group_hours_and_lengths(self):
        self.lesson("Almanca", [self.g1], 2)
        self.lesson("Fransızca", [self.g2], 3)
        self.assertEqual(self.codes().get("group_hours"), "warning")
        Lesson.objects.filter(subject__name="Fransızca").update(periods_per_week=2, card_length=2)
        codes = self.codes()
        self.assertNotIn("group_hours", codes)
        self.assertEqual(codes.get("group_lengths"), "warning")

    def test_room_and_period_and_class_limit_checks(self):
        self.lesson("Matematik", [], 4)
        Classroom.objects.create(school=self.school, name="Lab")
        self.assertNotIn("no_room", self.codes())  # dersliksiz ders sınıfın kendi dersliğinde yapılır
        for d in range(5):
            Availability.objects.create(school=self.school, school_class=self.cls, day=d, period=5)
        self.assertIn("closed_period", self.codes())
        self.cls.min_periods_per_day = 2
        self.cls.save()
        self.assertEqual(self.codes().get("class_min_total"), "error")
