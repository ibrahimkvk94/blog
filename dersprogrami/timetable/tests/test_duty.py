"""Nöbet çizelgesi: otomatik dağıtım, elle düzenleme, yazdırma ve vekâlet önceliği."""

import datetime
from collections import Counter

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import duty, substitutes
from timetable.models import Absence, Availability, Duty, DutyPlace, School
from timetable.tests.test_operations import build_school
from timetable.services import generate_timetable


class DutyTests(TestCase):
    def setUp(self):
        self.school = build_school()
        self.timetable = generate_timetable(self.school, "ilk", time_limit=10)
        School.objects.filter(pk=self.school.pk).update(active_timetable=self.timetable)
        self.school.refresh_from_db()
        self.place = DutyPlace.objects.create(school=self.school, name="Bahçe", teachers_per_day=1)

    def test_generate_fills_every_day_on_lesson_days(self):
        result = duty.generate(self.school)
        self.assertTrue(result["ok"], result)
        duties = list(Duty.objects.filter(place=self.place))
        self.assertEqual(sorted(d.day for d in duties), [0, 1, 2, 3, 4])
        lessons = duty.teacher_days(self.school, self.timetable)
        busy_days = {day for days in lessons.values() for day, hours in days.items() if hours}
        for d in duties:
            if d.day in busy_days:  # o gün kimsenin dersi yoksa nöbet kaçınılmaz olarak ders dışı güne düşer
                self.assertGreater(lessons[d.teacher_id][d.day], 0, "nöbet dersi olmayan güne verilmemeli")
        # 3 öğretmen, 5 nöbet: dağılım dengeli (en çok 2, en az 1)
        counts = Counter(d.teacher_id for d in duties)
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        if busy_days == set(range(5)):
            self.assertEqual(duty.roster(self.school)["warnings"], [])

    def test_exempt_and_closed_days_are_respected(self):
        teachers = list(self.school.teachers.all())
        teachers[0].duty_exempt = True
        teachers[0].save()
        for p in range(6):
            Availability.objects.create(school=self.school, teacher=teachers[1], day=0, period=p)
        duty.generate(self.school)
        self.assertFalse(Duty.objects.filter(teacher=teachers[0]).exists())
        self.assertFalse(Duty.objects.filter(teacher=teachers[1], day=0).exists())

    def test_no_places(self):
        self.place.delete()
        self.assertFalse(duty.generate(self.school)["ok"])

    def test_on_duty_teacher_is_preferred_for_substitution(self):
        duty.generate(self.school)
        monday = datetime.date(2026, 10, 26)  # Pazartesi
        on_duty = Duty.objects.get(place=self.place, day=0).teacher
        absent = next(t for t in self.school.teachers.all() if t != on_duty)
        Absence.objects.create(school=self.school, date=monday, teacher=absent)
        plan = substitutes.day_plan(self.school, self.timetable, monday)
        reasons = [c["reasons"] for slot in plan[0]["slots"] for c in slot["candidates"] if c["teacher"] == on_duty]
        self.assertTrue(all("bugün nöbetçi" in r for r in reasons))


class DutyViewTests(TestCase):
    def setUp(self):
        self.school = build_school()
        generate_timetable(self.school, "ilk", time_limit=10)
        self.user = User.objects.create_user("nobet", password="parola-123456")
        self.client.force_login(self.user)
        self.url = reverse("timetable:duties", args=[self.school.pk])

    def test_flow(self):
        self.assertContains(self.client.get(self.url), "Nöbet yerleri")
        self.client.post(self.url, {"action": "add_place", "name": "Koridor", "teachers_per_day": "2"})
        place = DutyPlace.objects.get(school=self.school)
        self.assertEqual(place.teachers_per_day, 2)
        self.client.post(self.url, {"action": "update_place", "place": place.pk, "name": "Koridor", "teachers_per_day": "1", "days": ["0", "2"]})
        place.refresh_from_db()
        self.assertEqual(place.days, [0, 2])
        response = self.client.post(self.url, {"action": "generate"})
        self.assertRedirects(response, self.url)
        self.assertEqual(sorted(Duty.objects.values_list("day", flat=True)), [0, 2])
        teacher = self.school.teachers.first()
        self.client.post(self.url, {"action": "set", "place": place.pk, "day": "0", "teachers": [teacher.pk]})
        self.assertEqual(list(Duty.objects.filter(day=0).values_list("teacher_id", flat=True)), [teacher.pk])
        page = self.client.get(reverse("timetable:duties_print", args=[self.school.pk]))
        self.assertContains(page, teacher.full_name)
        self.client.post(self.url, {"action": "clear"})
        self.assertFalse(Duty.objects.exists())
