"""Kısım değişikliği: gelemeyen öğretmenin kısmı, aynı dersi başka kısımda okutan öğretmenle değiştirilir."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import swaps
from timetable.models import Availability, Card, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable


class _Base(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(2):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.math = Subject.objects.create(school=self.school, name="Matematik", short="MAT")
        self.mehmet = Teacher.objects.create(school=self.school, first_name="Mehmet", last_name="Kaya")
        self.ahmet = Teacher.objects.create(school=self.school, first_name="Ahmet", last_name="Er")
        self.ahmet.subjects.add(self.math)
        self.timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        self.l1 = self._lesson(self.math, "2.KISIM", self.mehmet, (3, 0))  # perşembe 1. saat
        self.l2 = self._lesson(self.math, "3.KISIM", self.ahmet, (1, 0))   # salı 1. saat

    def _lesson(self, subject, cls_name, teacher, cell):
        lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=1, card_length=1)
        lesson.classes.add(SchoolClass.objects.create(school=self.school, name=cls_name))
        lesson.teachers.add(teacher)
        Card.objects.create(timetable=self.timetable, lesson=lesson, length=1, day=cell[0], period=cell[1], locked=True)
        return lesson


class SwapTests(_Base):
    def test_find_and_apply(self):
        found = swaps.find(self.timetable, self.mehmet.id, 3, [0])
        self.assertEqual(len(found), 1)
        s = found[0]["swaps"][0]
        self.assertEqual((s["l1"], s["l2"], s["a"], s["branch"]), (self.l1.id, self.l2.id, self.ahmet.id, True))
        self.assertEqual((found[0]["resolved"], found[0]["total"]), (1, 1))
        # Doğrulama geçici yazdı ve geri aldı
        self.assertEqual(list(self.l1.teachers.all()), [self.mehmet])
        self.assertFalse(Availability.objects.exists())
        swaps.apply(self.timetable, found[0], (self.mehmet.id, 3, [0]))
        self.assertEqual(list(self.l1.teachers.all()), [self.ahmet])
        self.assertEqual(list(self.l2.teachers.all()), [self.mehmet])
        self.assertTrue(Availability.objects.filter(teacher=self.mehmet, day=3, period=0, state=Availability.NO).exists())
        with self.assertRaises(ValueError):  # ikinci kez: öğretmenler artık farklı
            swaps.apply(self.timetable, found[0])

    def test_no_swap_when_other_teacher_busy_or_closed(self):
        physics = Subject.objects.create(school=self.school, name="Fizik")
        self._lesson(physics, "4.KISIM", self.ahmet, (3, 0))  # Ahmet perşembe 1. saatte dolu
        self.assertEqual(swaps.find(self.timetable, self.mehmet.id, 3, [0]), [])
        # Mehmet'in kendi kapanan saati yeni kısmın saatine denk gelirse de olmaz
        self.assertEqual(swaps.find(self.timetable, self.mehmet.id, 1, [0]), [])

    def test_solution_center_offers_and_applies_swap(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:solution_center", args=[self.timetable.pk])
        page = self.client.post(url, {"action": "solve", "tur": "teacher", "ogretmen": self.mehmet.id, "gun": "3", "saatler": ["0"]})
        self.assertContains(page, "Kısım değişikliği önerileri")
        self.assertContains(page, "Ahmet Er")
        response = self.client.post(url, {"action": "swap", "oneri": "0", "musaitlik": "1"})
        self.assertRedirects(response, reverse("timetable:timetable_detail", args=[self.timetable.pk]))
        self.assertEqual(list(self.l1.teachers.all()), [self.ahmet])
        self.assertTrue(Availability.objects.filter(teacher=self.mehmet, day=3).exists())


class WhyRedTests(_Base):
    def test_options_explain_class_and_availability(self):
        from timetable import editing

        Availability.objects.create(school=self.school, school_class=self.l1.classes.first(), day=4, period=0, state=Availability.NO)
        card = self.l1.cards.first()
        physics = Subject.objects.create(school=self.school, name="Fizik")
        other = Lesson.objects.create(school=self.school, subject=physics, periods_per_week=1, card_length=1)
        other.classes.add(self.l1.classes.first())
        Card.objects.create(timetable=self.timetable, lesson=other, length=1, day=0, period=1)
        options, why = editing.Board(self.timetable).options_explained(card.id)
        by = {w["who"]: w for w in why}
        self.assertEqual(by["Sınıf 2.KISIM"]["busy"], 1)
        self.assertEqual(by["Sınıf 2.KISIM"]["closed"], 1)
        friday = next(o for o in options if (o["day"], o["period"]) == (4, 0))
        self.assertEqual(friday["reasons"], ["Kapalı saat: Sınıf 2.KISIM müsaitliği"])
