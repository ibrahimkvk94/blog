"""Genel bakıştaki sürüm silme (Sürümler tablosu menüsü → timetables_delete)."""

from django.contrib.auth import get_user_model
User = get_user_model()  # KAMYOSİS: özel kullanıcı modeli
from django.test import TestCase
from django.urls import reverse

from timetable.models import Card, Membership, School, Timetable
from timetable.tests.test_operations import build_school

M = Membership


class TimetablesDeleteTests(TestCase):
    def setUp(self):
        self.school = build_school()
        self.a = Timetable.objects.create(school=self.school, name="A", status=Timetable.OK)
        self.b = Timetable.objects.create(school=self.school, name="B", status=Timetable.OK)
        self.running = Timetable.objects.create(school=self.school, name="Çalışan", status=Timetable.RUNNING)
        self.school.active_timetable = self.a
        self.school.working_timetable = self.a
        self.school.save()
        self.other = Timetable.objects.create(school=School.objects.create(name="Başka", institution=self.school.institution),
                                              name="Başka sürüm", status=Timetable.OK)
        self.url = reverse("timetable:timetables_delete", args=[self.school.pk])
        self.manager = User.objects.create_user("yonetici", password="parola-123456")
        M.objects.create(user=self.manager, institution=self.school.institution, permissions=M.ALL)
        self.client.force_login(self.manager)

    def test_menu_is_on_the_dashboard(self):
        page = self.client.get(reverse("timetable:school_detail", args=[self.school.pk]))
        self.assertContains(page, 'id="tt-menu"')
        self.assertContains(page, f'data-tt="{self.a.pk}"')
        self.assertContains(page, 'data-tt-busy="1"')  # çalışan sürüm menüde silinemez görünür

    def test_selected_versions_are_deleted_and_links_cleared(self):
        Card.objects.create(timetable=self.a, lesson=self.school.lessons.first(), length=1)
        response = self.client.post(self.url, {"ids": [self.a.pk, self.b.pk]})
        self.assertRedirects(response, reverse("timetable:school_detail", args=[self.school.pk]), fetch_redirect_response=False)
        self.assertFalse(Timetable.objects.filter(pk__in=[self.a.pk, self.b.pk]).exists())
        self.assertFalse(Card.objects.filter(timetable_id=self.a.pk).exists())
        self.school.refresh_from_db()
        self.assertIsNone(self.school.active_timetable_id)
        self.assertIsNone(self.school.working_timetable_id)

    def test_running_version_is_skipped(self):
        self.client.post(self.url, {"ids": [self.running.pk, self.b.pk]})
        self.assertTrue(Timetable.objects.filter(pk=self.running.pk).exists())
        self.assertFalse(Timetable.objects.filter(pk=self.b.pk).exists())

    def test_other_school_versions_are_untouched(self):
        self.client.post(self.url, {"ids": [self.other.pk]})
        self.assertTrue(Timetable.objects.filter(pk=self.other.pk).exists())

    def test_viewer_cannot_delete(self):
        viewer = User.objects.create_user("izleyici", password="parola-123456")
        M.objects.create(user=viewer, institution=self.school.institution, permissions=[M.VIEW])
        self.client.force_login(viewer)
        response = self.client.post(self.url, {"ids": [self.a.pk]})
        self.assertIn(response.status_code, (302, 403))
        self.assertTrue(Timetable.objects.filter(pk=self.a.pk).exists())
        page = self.client.get(reverse("timetable:school_detail", args=[self.school.pk]))
        self.assertNotContains(page, 'id="tt-menu"')

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_published_version_can_be_unpublished_then_deleted(self):
        page = self.client.get(reverse("timetable:school_detail", args=[self.school.pk]))
        self.assertContains(page, 'data-tt-published="1"')
        self.assertContains(page, 'id="tt-unpublish"')
        self.client.post(reverse("timetable:unpublish", args=[self.school.pk]))
        self.school.refresh_from_db()
        self.assertIsNone(self.school.active_timetable_id)
        self.assertTrue(Timetable.objects.filter(pk=self.a.pk).exists())  # yalnızca pasife alınır
        self.client.post(self.url, {"ids": [self.a.pk]})
        self.assertFalse(Timetable.objects.filter(pk=self.a.pk).exists())
