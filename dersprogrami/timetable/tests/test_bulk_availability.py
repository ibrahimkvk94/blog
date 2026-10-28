"""Toplu müsaitlik, kaydederken diğerlerine uygulama ve ana görünüm problem önbelleği."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import problem_cache
from timetable.demo import create_demo_school
from timetable.models import Availability, Period, School, SchoolClass, Teacher


class BulkAvailabilityTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(8):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.classes = [SchoolClass.objects.create(school=self.school, name=f"{n}.KISIM", short=f"{n}{d}")
                        for n, d in ((1, "SVN"), (2, "SVN"), (3, "İŞL"))]
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:bulk_availability", args=[self.school.pk])

    def states(self, cls):
        return {(a.day, a.period): a.state for a in Availability.objects.filter(school_class=cls)}

    def test_close_then_open_marked_cells(self):
        Availability.objects.create(school=self.school, school_class=self.classes[0], day=0, period=0, state="no")
        grid = json.dumps({"4-6": "no", "4-7": "no"})
        self.client.post(self.url, {"tur": "sinif", "copy_to": [self.classes[0].pk, self.classes[1].pk],
                                    "copy_mode": "close", "availability": grid})
        self.assertEqual(self.states(self.classes[0]), {(0, 0): "no", (4, 6): "no", (4, 7): "no"})  # eski kapatma korunur
        self.assertEqual(self.states(self.classes[1]), {(4, 6): "no", (4, 7): "no"})
        self.assertEqual(self.states(self.classes[2]), {})
        self.client.post(self.url, {"tur": "sinif", "copy_to": [self.classes[0].pk], "copy_mode": "open",
                                    "availability": json.dumps({"4-7": "no"})})
        self.assertEqual(self.states(self.classes[0]), {(0, 0): "no", (4, 6): "no"})

    def test_replace_and_page(self):
        Availability.objects.create(school=self.school, school_class=self.classes[2], day=1, period=1, state="no")
        self.client.post(self.url, {"tur": "sinif", "copy_to": [self.classes[2].pk], "copy_mode": "replace",
                                    "availability": json.dumps({"0-0": "maybe"})})
        self.assertEqual(self.states(self.classes[2]), {(0, 0): "maybe"})
        page = self.client.get(self.url, {"tur": "sinif", "kaynak": self.classes[2].pk})
        self.assertContains(page, "Tüm SVN")  # kısa addan küme
        self.assertContains(page, "müsaitliği yüklendi")
        self.assertEqual(self.client.get(self.url, {"tur": "ogretmen"}).status_code, 200)

    def test_copy_on_save_from_class_form(self):
        cls = self.classes[0]
        url = reverse("timetable:data_edit", args=[self.school.pk, "siniflar", cls.pk])
        self.client.post(url, {"name": cls.name, "short": cls.short, "availability": json.dumps({"2-3": "no"}),
                               "divisions": "[]", "copy_to": [self.classes[1].pk], "copy_mode": "replace"})
        self.assertEqual(self.states(cls), {(2, 3): "no"})
        self.assertEqual(self.states(self.classes[1]), {(2, 3): "no"})
        self.assertEqual(self.states(self.classes[2]), {})

    def test_teacher_copy(self):
        a = Teacher.objects.create(school=self.school, first_name="A", last_name="B")
        b = Teacher.objects.create(school=self.school, first_name="C", last_name="D")
        self.client.post(self.url, {"tur": "ogretmen", "copy_to": [a.pk, b.pk], "copy_mode": "close",
                                    "availability": json.dumps({"0-0": "no"})})
        self.assertEqual(Availability.objects.filter(teacher__in=[a, b], day=0, period=0).count(), 2)


class ProblemCacheTests(TestCase):
    def setUp(self):
        from timetable.services import generate_timetable

        self.school = create_demo_school()
        self.timetable = generate_timetable(self.school, "t", time_limit=20)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def test_reused_until_data_changes(self):
        first = problem_cache.problem_for(self.timetable)
        self.assertIs(problem_cache.problem_for(self.timetable), first)
        # Kart taşımak problemi değiştirmez
        card = self.timetable.cards.filter(day__isnull=False, locked=False).first()
        options = self.client.get(reverse("timetable:api_card_options", args=[card.pk])).json()["options"]
        free = next(o for o in options if o["status"] == "free")
        self.client.post(reverse("timetable:api_card_move", args=[card.pk]), json.dumps({"day": free["day"], "period": free["period"]}),
                         content_type="application/json")
        self.assertIs(problem_cache.problem_for(self.timetable), first)
        # Kilit doğrulamayı etkiler: yenilenir
        self.client.post(reverse("timetable:api_card_lock", args=[card.pk]))
        second = problem_cache.problem_for(self.timetable)
        self.assertIsNot(second, first)
        # Veri değişikliği (toplu müsaitlik) yeniler
        cls = self.school.classes.first()
        self.client.post(reverse("timetable:bulk_availability", args=[self.school.pk]),
                         {"tur": "sinif", "copy_to": [cls.pk], "copy_mode": "close", "availability": json.dumps({"0-0": "no"})})
        third = problem_cache.problem_for(self.timetable)
        self.assertIsNot(third, second)
        cell_closed = all((0, 0) not in c.starts for c in third.cards if any(a.startswith(f"{cls.pk}|") for a in c.atoms))
        self.assertTrue(cell_closed)
