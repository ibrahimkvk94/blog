"""Veritabanı, servis ve görünüm katmanının uçtan uca testleri."""

from django.test import TestCase
from django.urls import reverse

from timetable.demo import create_demo_school
from timetable.models import Availability, Card, Lesson, Timetable
from timetable.services import check_school, generate_timetable, verify_timetable


class DemoSchoolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()

    def test_demo_data_passes_checks(self):
        self.assertFalse([i for i in check_school(self.school) if i.level == "error"])

    def test_generate_places_all_cards_without_violations(self):
        timetable = generate_timetable(self.school, "test", time_limit=30)
        self.assertEqual(timetable.status, Timetable.OK, timetable.report)
        expected = sum(len(lesson.card_lengths()) for lesson in self.school.lessons.all())
        self.assertEqual(timetable.cards.filter(day__isnull=False).count(), expected)
        violations, stats = verify_timetable(timetable)
        self.assertEqual(violations, [])
        self.assertEqual(stats["unplaced"], 0)

    def test_physics_teacher_has_no_friday_lessons(self):
        timetable = generate_timetable(self.school, "test", time_limit=30)
        physics = timetable.cards.filter(lesson__subject__short="FİZ")
        self.assertTrue(physics.exists())
        self.assertFalse(physics.filter(day=4).exists())

    def test_locked_cards_are_kept_when_regenerating(self):
        first = generate_timetable(self.school, "ilk", time_limit=30)
        card = first.cards.filter(lesson__subject__short="TDE").first()
        card.locked = True
        card.save()
        second = generate_timetable(self.school, "ikinci", time_limit=30, base=first)
        self.assertEqual(second.status, Timetable.OK)
        kept = second.cards.get(lesson=card.lesson, day=card.day, period=card.period)
        self.assertTrue(kept.locked)

    def test_lessons_added_after_base_are_included(self):
        first = generate_timetable(self.school, "ilk", time_limit=30)
        lesson = Lesson.objects.create(
            school=self.school, subject=self.school.subjects.get(short="MÜZ"), periods_per_week=1
        )
        lesson.classes.set([self.school.classes.get(name="10-A")])
        lesson.teachers.set([self.school.teachers.get(short="GAK")])
        second = generate_timetable(self.school, "ikinci", time_limit=30, base=first)
        self.assertEqual(second.status, Timetable.OK)
        self.assertEqual(second.cards.count(), first.cards.count() + 1)
        self.assertTrue(second.cards.get(lesson=lesson).is_placed)

    def test_manual_clash_is_detected_by_verification(self):
        timetable = generate_timetable(self.school, "test", time_limit=30)
        a, b = timetable.cards.filter(lesson__subject__short="TDE", lesson__classes__name="9-A")[:2]
        b.day, b.period = a.day, a.period
        b.save()
        violations, _ = verify_timetable(timetable)
        self.assertIn("atom_clash", [v.code for v in violations])

    def test_overloaded_teacher_fails_before_solving(self):
        lesson = Lesson.objects.filter(school=self.school, subject__short="MAT").first()
        teacher = lesson.teachers.first()
        Availability.objects.bulk_create(
            Availability(school=self.school, teacher=teacher, day=d, period=p)
            for d in range(4)
            for p in range(8)
        )
        timetable = generate_timetable(self.school, "test", time_limit=5)
        self.assertEqual(timetable.status, Timetable.FAILED)
        self.assertIn("teacher_overload", [i["code"] for i in timetable.report["issues"]])
        self.assertFalse(Card.objects.filter(timetable=timetable).exists())


class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.timetable = generate_timetable(cls.school, "görünüm", time_limit=30)

    def test_pages_render(self):
        self.assertContains(self.client.get(reverse("timetable:school_list")), self.school.name)
        self.assertContains(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])), "Program üret")
        url = reverse("timetable:timetable_detail", args=[self.timetable.pk])
        for kind in ("sinif", "ogretmen", "derslik"):
            self.assertContains(self.client.get(url, {"tur": kind}), "Pazartesi")

    def test_generate_view_redirects_to_new_timetable(self):
        response = self.client.post(
            reverse("timetable:generate", args=[self.school.pk]), {"name": "web", "time_limit": "20"}
        )
        new = Timetable.objects.get(name="web")
        self.assertRedirects(response, reverse("timetable:timetable_detail", args=[new.pk]))

    def test_toggle_lock(self):
        card = self.timetable.cards.first()
        self.client.post(reverse("timetable:toggle_lock", args=[card.pk]), {"next": "https://evil.example/"})
        card.refresh_from_db()
        self.assertTrue(card.locked)
