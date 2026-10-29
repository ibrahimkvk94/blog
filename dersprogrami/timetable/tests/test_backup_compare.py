"""Yedekle karşılaştırma: yedekteki üretim girdisi ayrı bir veritabanına yüklenip bugünküyle karşılaştırılır."""

import datetime
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from timetable import backup
from timetable.models import Lesson, Period, School, SchoolClass, Subject, Teacher


class BackupCompareTests(TransactionTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(BACKUP_DIR=Path(self.dir.name))
        self.settings_override.enable()
        self.school = School.objects.create(name="MYO", days_per_week=5)
        Period.objects.create(school=self.school, index=0, name="1", start_time=datetime.time(8), end_time=datetime.time(8, 40))
        self.teacher = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya")
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Fizik"), periods_per_week=1)
        lesson.classes.add(SchoolClass.objects.create(school=self.school, name="1A"))
        lesson.teachers.add(self.teacher)

    def tearDown(self):
        self.settings_override.disable()
        self.dir.cleanup()

    def test_compare_finds_changed_limit(self):
        path = backup.create()
        self.teacher.max_periods_per_day = 2
        self.teacher.save()
        result = backup.compare(path, self.school)
        self.assertNotIn("error", result)
        self.assertEqual([(g["kind"], g["added"]) for g in result["diff"]], [("teachers", [("Ali Kaya", "günde ≤2 ders")])])
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        page = self.client.get(reverse("timetable:backup_compare", args=[self.school.pk]) + f"?yedek={path.name}")
        self.assertContains(page, "+ Ali Kaya")
