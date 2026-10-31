"""Derslik atama sihirbazı."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import rooms_wizard
from timetable.models import Classroom, Lesson, Period, School, SchoolClass, Subject


class RoomWizardTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        Period.objects.create(school=self.school, index=0, name="1")
        self.lab = Classroom.objects.create(school=self.school, name="BİL-Bilgisayar Dershanesi 1")
        self.room = Classroom.objects.create(school=self.school, name="Derslik 101")
        self.cls = SchoolClass.objects.create(school=self.school, name="1.KISIM")
        other = SchoolClass.objects.create(school=self.school, name="2.KISIM")
        self.theory = Subject.objects.create(school=self.school, name="Programlama", short="BİL211")
        self.practical = Subject.objects.create(school=self.school, name="Programlama (U)", short="BİL211")
        self.history = Subject.objects.create(school=self.school, name="Tarih", short="TAR101")
        for subject, classes in ((self.theory, [self.cls]), (self.practical, [self.cls]), (self.history, [self.cls, other])):
            lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=2)
            lesson.classes.set(classes)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:room_wizard", args=[self.school.pk])

    def test_analysis_suggests_prefix_rooms(self):
        data = rooms_wizard.analyze(self.school)
        self.assertEqual((data["lessons"], data["multi"]), (3, 1))
        bil = next(p for p in data["prefix_rows"] if p["prefix"] == "BİL")
        self.assertEqual(bil["rooms"], [self.lab.pk])
        self.assertEqual([x["practical"] for x in bil["subjects"]], [False, True])
        self.assertEqual([r["cls"] for r in data["class_rows"]], [self.cls])

    def test_apply_prefix_only_to_practical_and_class_room(self):
        self.client.post(self.url, {"onek-BİL-derslik": [self.lab.pk], "onek-BİL-ders": [self.practical.pk],
                                    f"sinif-{self.cls.pk}": self.room.pk})
        self.assertEqual(list(self.practical.classrooms.all()), [self.lab])
        self.assertFalse(self.theory.classrooms.exists())
        self.cls.refresh_from_db()
        self.assertEqual(self.cls.home_classroom, self.room)
        # Birleşik Tarih dersi: sınıflardan yalnızca birinin dersliği var, o kullanılır → dersliksiz ders kalmaz
        self.assertEqual(rooms_wizard.roomless(self.school), [])
        self.assertContains(self.client.get(self.url), "Tüm derslerin dersliği belirli")
