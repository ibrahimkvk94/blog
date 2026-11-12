"""Dersi başka kısımlara ayrı ders olarak kopyalama (Dersler sayfası toplu işlemi)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.data_views import copy_lessons
from timetable.models import Availability, Classroom, Division, Group, Lesson, School, SchoolClass, Subject, Teacher


class LessonCopyTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO")
        self.a, self.b, self.c = (SchoolClass.objects.create(school=self.school, name=n) for n in ("1.KISIM", "2.KISIM", "3.KISIM"))
        for cls in (self.a, self.b):  # 3.KISIM'in bölünmesi yok
            div = Division.objects.create(school_class=cls, name="Dil")
            Group.objects.create(division=div, name="A")
            Group.objects.create(division=div, name="B")
        self.teacher = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Er")
        self.lab = Classroom.objects.create(school=self.school, name="Lab 1")
        self.mat = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Matematik", short="MAT"),
                                         periods_per_week=4, card_length=2, max_per_day=1)
        self.mat.classes.set([self.a])
        self.mat.teachers.set([self.teacher])
        self.mat.classrooms.set([self.lab])
        Availability.objects.create(school=self.school, lesson=self.mat, day=0, period=0, state=Availability.NO)
        self.dil = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="İngilizce", short="YDL"),
                                         periods_per_week=2)
        self.dil.classes.set([self.a])
        self.dil.groups.set([Group.objects.get(division__school_class=self.a, name="A")])

    def lessons_of(self, cls):
        return Lesson.objects.filter(classes=cls)

    def test_copies_are_separate_lessons_without_teachers(self):
        message, level = copy_lessons(self.school, [self.mat, self.dil], [self.b, self.c])
        self.assertEqual(level, "success")
        self.assertIn("3 yeni ders", message)
        self.assertIn("aynı adlı grup", message)  # İngilizce-A 3.KISIM'a atlandı
        mat_b = self.lessons_of(self.b).get(subject__short="MAT")
        self.assertEqual(list(mat_b.classes.all()), [self.b])  # ortak ders değil
        self.assertEqual((mat_b.periods_per_week, mat_b.card_length, mat_b.max_per_day), (4, 2, 1))
        self.assertEqual(list(mat_b.classrooms.all()), [self.lab])
        self.assertFalse(mat_b.teachers.exists())
        self.assertEqual(list(mat_b.availabilities.values_list("day", "period")), [(0, 0)])
        dil_b = self.lessons_of(self.b).get(subject__short="YDL")
        self.assertEqual([(g.division.school_class_id, g.name) for g in dil_b.groups.all()], [(self.b.pk, "A")])
        self.assertFalse(self.lessons_of(self.c).filter(subject__short="YDL").exists())
        self.assertEqual(list(self.mat.classes.all()), [self.a])  # kaynak değişmedi

    def test_keep_teachers_and_skip_existing(self):
        copy_lessons(self.school, [self.mat], [self.b], keep_teachers=True)
        self.assertEqual(list(self.lessons_of(self.b).get().teachers.all()), [self.teacher])
        message, level = copy_lessons(self.school, [self.mat], [self.b, self.a])
        self.assertEqual(level, "warning")
        self.assertIn("zaten", message)
        self.assertEqual(self.lessons_of(self.b).count(), 1)
        copy_lessons(self.school, [self.mat], [self.b], skip_existing=False)
        self.assertEqual(self.lessons_of(self.b).count(), 2)

    def test_bulk_action_from_lessons_page(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:lessons", args=[self.school.pk])
        page = self.client.get(url)
        self.assertContains(page, "Başka kısımlara kopyala")
        self.assertContains(page, f'name="hedef" value="{self.c.pk}"')
        response = self.client.post(url, {"ders": [self.mat.pk], "islem": "kopyala", "hedef": [self.b.pk, self.c.pk], "atla": "1"}, follow=True)
        self.assertContains(response, "2 yeni ders")
        self.assertEqual(Lesson.objects.filter(subject__short="MAT").count(), 3)
        response = self.client.post(url, {"ders": [self.mat.pk], "islem": "kopyala"}, follow=True)
        self.assertContains(response, "kısımları seçin")

    def test_copy_from_single_lesson_screen(self):
        self.client.force_login(User.objects.create_superuser("admin2", "b@x.tr", "pw"))
        edit = reverse("timetable:lesson_edit", args=[self.school.pk, self.mat.pk])
        page = self.client.get(edit)
        self.assertContains(page, "Kısımlara kopyala")
        self.assertContains(page, f'name="hedef" value="{self.a.pk}" disabled')  # dersin kendi kısmı seçilemez
        self.assertContains(page, f'name="hedef" value="{self.b.pk}">')
        response = self.client.post(reverse("timetable:lessons", args=[self.school.pk]),
                                    {"ders": [self.mat.pk], "islem": "kopyala", "hedef": [self.b.pk], "atla": "1", "geri": edit})
        self.assertRedirects(response, edit, fetch_redirect_response=False)
        self.assertTrue(self.lessons_of(self.b).filter(subject__short="MAT").exists())
        # dışarıya yönlendirme yok
        response = self.client.post(reverse("timetable:lessons", args=[self.school.pk]),
                                    {"ders": [self.mat.pk], "islem": "kopyala", "hedef": [self.c.pk], "geri": "//kotu.example"})
        self.assertRedirects(response, reverse("timetable:lessons", args=[self.school.pk]), fetch_redirect_response=False)
