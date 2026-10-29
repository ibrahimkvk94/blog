"""Büyük okul: 1000'i aşan ders ve kartla sayfalar açılabilmeli.

SQLite'ta 1000'den uzun kimlik listeleri (ör. prefetch ile "IN (...)") "Expression tree too large" hatası verebilir;
gerçek veride nöbet ve boş öğretmen raporu bu yüzden çökmüştü.
"""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.models import Card, DutyPlace, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable


class LargeSchoolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Büyük MYO", days_per_week=5)
        Period.objects.bulk_create(Period(school=cls.school, index=i, name=str(i + 1), start_time=datetime.time(8 + i),
                                          end_time=datetime.time(8 + i, 40)) for i in range(8))
        teachers = Teacher.objects.bulk_create(Teacher(school=cls.school, first_name=f"Ad{i}", last_name=f"Soyad{i}") for i in range(120))
        classes = SchoolClass.objects.bulk_create(SchoolClass(school=cls.school, name=f"{i}.KISIM") for i in range(60))
        subject = Subject.objects.create(school=cls.school, name="Ders", short="DRS")
        lessons = Lesson.objects.bulk_create(Lesson(school=cls.school, subject=subject, periods_per_week=1) for _ in range(1100))
        Lesson.classes.through.objects.bulk_create(
            Lesson.classes.through(lesson_id=l.id, schoolclass_id=classes[i % 60].id) for i, l in enumerate(lessons))
        Lesson.teachers.through.objects.bulk_create(
            Lesson.teachers.through(lesson_id=l.id, teacher_id=teachers[i % 120].id) for i, l in enumerate(lessons))
        cls.tt = Timetable.objects.create(school=cls.school, name="Ana", status=Timetable.OK)
        Card.objects.bulk_create(Card(timetable=cls.tt, lesson=l, length=1, day=(i // 8) % 5, period=i % 8) for i, l in enumerate(lessons))
        cls.school.active_timetable = cls.tt
        cls.school.save()
        DutyPlace.objects.create(school=cls.school, name="Bahçe")
        cls.user = User.objects.create_superuser("buyuk", password="parola-123456")

    def test_pages_open(self):
        self.client.force_login(self.user)
        s, t = self.school.pk, self.tt.pk
        urls = [
            reverse("timetable:school_detail", args=[s]), reverse("timetable:duties", args=[s]),
            reverse("timetable:substitutions", args=[s]), reverse("timetable:teacher_assign", args=[s]),
            reverse("timetable:api_grid", args=[t]) + "?tur=ogretmen", reverse("timetable:quality", args=[t]),
            reverse("timetable:change_report", args=[t]), reverse("timetable:print", args=[t]) + "?tur=ogretmen",
            reverse("timetable:report_render", args=[t]) + "?tur=bos_ogretmen",
            reverse("timetable:report_pdf", args=[t]) + "?tur=bos_ogretmen",
            reverse("timetable:report_render", args=[t]) + "?tur=yuk",
            reverse("timetable:report_render", args=[t]) + "?tur=bireysel&varlik=ogretmen",
            reverse("timetable:report_render", args=[t]) + "?tur=nobet",
            reverse("timetable:report_excel", args=[t]) + "?tur=carsaf&varlik=sinif",
            reverse("timetable:export_excel", args=[t]), reverse("timetable:export_asc", args=[t]),
            reverse("timetable:room_usage", args=[t]), reverse("timetable:pending", args=[t]),
            reverse("timetable:solution_center", args=[t]), reverse("timetable:statistics", args=[t]),
            reverse("timetable:timetable_detail", args=[t]), reverse("timetable:school_improve", args=[t]),
            reverse("timetable:api_versions", args=[t]), reverse("timetable:lessons", args=[s]),
            reverse("timetable:distribution", args=[s]), reverse("timetable:data_list", args=[s, "ogretmenler"]),
            reverse("timetable:data_list", args=[s, "siniflar"]), reverse("timetable:relation_wizard", args=[s]),
            reverse("timetable:relation_audit", args=[s]), reverse("timetable:room_wizard", args=[s]),
            reverse("timetable:students", args=[s]), reverse("timetable:lesson_refs", args=[s]),
            reverse("timetable:bulk_availability", args=[s]), reverse("timetable:excel_export", args=[s]),
            reverse("timetable:setup_wizard", args=[s, "dersler"]), reverse("timetable:setup_wizard", args=[s, "uret"]),
        ]
        failed = [url for url in urls if self.client.get(url).status_code != 200]
        self.assertEqual(failed, [])

    def test_teacher_and_public_pages_open(self):
        from timetable import teacher_calendar

        teacher = Teacher.objects.filter(school=self.school).first()
        teacher.user = self.user
        teacher.save()
        teacher_calendar.ensure_token(teacher)
        School.objects.filter(pk=self.school.pk).update(publish_enabled=True, publish_token="buyukokul")
        self.client.force_login(self.user)
        cls = SchoolClass.objects.filter(school=self.school).first()
        urls = [
            reverse("timetable:my_timetable"), reverse("timetable:my_requests"),
            reverse("timetable:teacher_ics", args=[teacher.calendar_token]),
            reverse("timetable:public_index", args=["buyukokul"]), reverse("timetable:public_board", args=["buyukokul"]),
            reverse("timetable:public_timetable", args=["buyukokul", "sinif", cls.pk]),
            reverse("timetable:public_timetable", args=["buyukokul", "ogretmen", teacher.pk]),
        ]
        failed = [url for url in urls if self.client.get(url).status_code != 200]
        self.assertEqual(failed, [])
