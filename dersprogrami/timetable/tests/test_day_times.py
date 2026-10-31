"""Günlere göre farklı ders saatleri."""

import datetime
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.grid import grid_data
from timetable.models import Card, Lesson, Period, School, SchoolClass, Subject, Timetable, day_time_notes


class DayTimeTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        self.periods = [Period.objects.create(school=self.school, index=i, name=str(i + 1),
                                              start_time=datetime.time(8 + i, 20), end_time=datetime.time(9 + i, 0)) for i in range(3)]
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def test_model_times_and_notes(self):
        p = self.periods[0]
        p.day_times = {"4": ["08:00", "08:35"]}
        p.save()
        self.assertEqual(p.times(4), (datetime.time(8, 0), datetime.time(8, 35)))
        self.assertEqual(p.times(0), (datetime.time(8, 20), datetime.time(9, 0)))
        self.assertEqual(p.span(4), "08:00–08:35")
        self.assertEqual(day_time_notes(self.periods, self.school.day_names), ["Cuma: 1. 08:00–08:35"])

    def post_settings(self, extra):
        data = {"name": self.school.name, "days_per_week": 5, "weeks_count": 1, "terms_count": 1,
                "periods-TOTAL_FORMS": 3, "periods-INITIAL_FORMS": 3, "periods-MIN_NUM_FORMS": 0, "periods-MAX_NUM_FORMS": 1000,
                "availability": "{}", **extra}
        for i, p in enumerate(self.periods):
            data.update({f"periods-{i}-id": p.pk, f"periods-{i}-name": p.name,
                         f"periods-{i}-start_time": f"{p.start_time:%H:%M}", f"periods-{i}-end_time": f"{p.end_time:%H:%M}"})
        return self.client.post(reverse("timetable:school_settings", args=[self.school.pk]), data, HTTP_X_REQUESTED_WITH="fetch")

    def test_settings_save_and_validation(self):
        p = self.periods[1]
        response = self.post_settings({f"gs-{p.pk}-4-start": "09:00", f"gs-{p.pk}-4-end": "09:35",
                                       f"gs-{p.pk}-0-start": "09:20", f"gs-{p.pk}-0-end": "10:00"})  # varsayılanla aynı: kaydedilmez
        self.assertTrue(response.json()["ok"], response.content)
        p.refresh_from_db()
        self.assertEqual(p.day_times, {"4": ["09:00", "09:35"]})
        bad = self.post_settings({f"gs-{p.pk}-2-start": "10:00", f"gs-{p.pk}-2-end": "09:00"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn(f"gs-{p.pk}-2-end", bad.json()["errors"])
        page = self.client.get(reverse("timetable:school_settings", args=[self.school.pk]))
        self.assertContains(page, 'value="09:35"')

    def test_grid_and_uybs_rows_use_day_time(self):
        from timetable import uybs

        p = self.periods[0]
        p.day_times = {"4": ["08:00", "08:35"]}
        p.save()
        cls = SchoolClass.objects.create(school=self.school, name="1.KISIM")
        subject = Subject.objects.create(school=self.school, name="Mat", short="MAT")
        lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=1)
        lesson.classes.add(cls)
        timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        Card.objects.create(timetable=timetable, lesson=lesson, length=1, day=4, period=0)
        starts = grid_data(timetable, "sinif")["periods"][0]["starts"]
        self.assertEqual((starts[0], starts[4]), ("08:20", "08:00"))
        rows, _ = uybs.week_rows(timetable, None, None)
        self.assertEqual(rows[0]["time"], "08:00–08:35")
