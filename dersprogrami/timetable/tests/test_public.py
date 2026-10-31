"""Herkese açık web yayını."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.models import Absence, Membership, School, Substitution
from timetable.services import generate_timetable
from timetable.tests.test_operations import build_school


class PublicTests(TestCase):
    def setUp(self):
        self.school = build_school()
        self.timetable = generate_timetable(self.school, "ilk", time_limit=10)
        School.objects.filter(pk=self.school.pk).update(active_timetable=self.timetable)
        self.manager = User.objects.create_user("yayinci", password="parola-123456")
        Membership.objects.create(user=self.manager, institution=self.school.institution, permissions=[Membership.PUBLISH])
        self.client.force_login(self.manager)
        self.client.post(reverse("timetable:publish_settings", args=[self.school.pk]), {"action": "enable"})
        self.school.refresh_from_db()
        self.token = self.school.publish_token
        self.client.logout()

    def test_public_pages_without_login(self):
        self.assertTrue(self.token)
        index = self.client.get(reverse("timetable:public_index", args=[self.token]))
        self.assertContains(index, "9-A")
        self.assertContains(index, "Öğretmenler")
        cls = self.school.classes.get(name="9-A")
        page = self.client.get(reverse("timetable:public_timetable", args=[self.token, "sinif", cls.pk]))
        self.assertContains(page, "Matematik")
        teacher = self.school.teachers.first()
        self.assertEqual(self.client.get(reverse("timetable:public_timetable", args=[self.token, "ogretmen", teacher.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:public_index", args=["yanlis"])).status_code, 404)

    def test_options_regenerate_and_disable(self):
        self.client.force_login(self.manager)
        url = reverse("timetable:publish_settings", args=[self.school.pk])
        page = self.client.get(url)
        self.assertContains(page, "<svg")  # QR kod
        self.client.post(url, {"action": "options", "publish_substitutions": "1"})  # öğretmenler gizli
        self.client.logout()
        teacher = self.school.teachers.first()
        self.assertNotContains(self.client.get(reverse("timetable:public_index", args=[self.token])), "Öğretmenler")
        self.assertEqual(self.client.get(reverse("timetable:public_timetable", args=[self.token, "ogretmen", teacher.pk])).status_code, 404)
        cls = self.school.classes.get(name="9-A")
        self.assertNotContains(self.client.get(reverse("timetable:public_timetable", args=[self.token, "sinif", cls.pk])), teacher.full_name)
        self.client.force_login(self.manager)
        self.client.post(url, {"action": "regenerate"})
        self.client.logout()
        self.assertEqual(self.client.get(reverse("timetable:public_index", args=[self.token])).status_code, 404)
        self.school.refresh_from_db()
        self.assertEqual(self.client.get(reverse("timetable:public_index", args=[self.school.publish_token])).status_code, 200)
        self.client.force_login(self.manager)
        self.client.post(url, {"action": "disable"})
        self.client.logout()
        self.assertEqual(self.client.get(reverse("timetable:public_index", args=[self.school.publish_token])).status_code, 404)

    def test_substitution_board(self):
        monday = datetime.date(2026, 10, 26)
        card = self.timetable.cards.filter(day=0).first()
        absent = card.lesson.teachers.first()
        substitute = self.school.teachers.exclude(pk=absent.pk).first()
        absence = Absence.objects.create(school=self.school, date=monday, teacher=absent)
        Substitution.objects.create(absence=absence, card=card, period=card.period, substitute=substitute)
        page = self.client.get(reverse("timetable:public_board", args=[self.token]) + "?tarih=2026-10-26")
        self.assertContains(page, substitute.full_name)
        self.assertContains(page, absent.full_name)

    def test_settings_require_publish_permission(self):
        viewer = User.objects.create_user("izle", password="parola-123456")
        Membership.objects.create(user=viewer, institution=self.school.institution, permissions=[])
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse("timetable:publish_settings", args=[self.school.pk])).status_code, 403)
        # Giriş yapmış ama kurumla ilgisi olmayan biri de yayını görebilir (bağlantı herkese açık)
        self.assertEqual(self.client.get(reverse("timetable:public_index", args=[self.token])).status_code, 200)
