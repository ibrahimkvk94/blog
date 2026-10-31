"""Kurum sayfasında düzenleme: kurum adı, program adı, programı başka kuruma taşıma, boş kurumu silme."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.models import Institution, Membership, School


class InstitutionEditTests(TestCase):
    def setUp(self):
        self.kamyo = Institution.objects.create(name="KAMYO")
        self.asc = Institution.objects.create(name="asctt2012 (5)")
        self.main = School.objects.create(name="2026-2027 EÖY Güz", institution=self.kamyo)
        self.imported = School.objects.create(name="asctt2012 (5)", institution=self.asc)
        self.admin = User.objects.create_superuser("merkez", "m@x.tr", "pw")
        self.client.force_login(self.admin)

    def url(self, inst):
        return reverse("timetable:institution_detail", args=[inst.pk])

    def test_rename_institution_and_program(self):
        self.client.post(self.url(self.kamyo), {"action": "rename", "name": "Kara Harp MYO"})
        self.kamyo.refresh_from_db()
        self.assertEqual(self.kamyo.name, "Kara Harp MYO")
        self.client.post(self.url(self.kamyo), {"action": "rename_program", "program": self.main.pk, "name": "2026 Güz"})
        self.main.refresh_from_db()
        self.assertEqual(self.main.name, "2026 Güz")
        response = self.client.post(self.url(self.kamyo), {"action": "rename", "name": "  "}, follow=True)
        self.assertContains(response, "Kurum adı boş olamaz")

    def test_move_program_then_delete_empty_institution(self):
        page = self.client.get(self.url(self.asc))
        self.assertContains(page, 'value="move_program"')
        self.assertNotContains(page, "Kurumu sil")  # programı varken silinemez
        self.client.post(self.url(self.asc), {"action": "move_program", "program": self.imported.pk, "target": self.kamyo.pk})
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.institution, self.kamyo)
        self.assertContains(self.client.get(self.url(self.asc)), "Kurumu sil")
        self.client.post(self.url(self.asc), {"action": "delete"})
        self.assertFalse(Institution.objects.filter(pk=self.asc.pk).exists())

    def test_permissions(self):
        viewer = User.objects.create_user("izleyici", password="pw")
        Membership.objects.create(user=viewer, institution=self.kamyo, permissions=[Membership.VIEW])
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(self.url(self.kamyo), {"action": "rename", "name": "X"}).status_code, 403)
        manager = User.objects.create_user("sorumlu", password="pw")
        Membership.objects.create(user=manager, institution=self.kamyo, permissions=[Membership.VIEW, Membership.PROGRAMS])
        self.client.force_login(manager)
        # Hedef kurumda program yetkisi yoksa taşıma seçeneği çıkmaz ve taşınamaz
        self.assertNotContains(self.client.get(self.url(self.kamyo)), 'value="move_program"')
        self.client.post(self.url(self.kamyo), {"action": "move_program", "program": self.main.pk, "target": self.asc.pk})
        self.main.refresh_from_db()
        self.assertEqual(self.main.institution, self.kamyo)
        # Programı olan kurum silinemez (merkez değil)
        self.client.post(self.url(self.kamyo), {"action": "delete"})
        self.assertTrue(Institution.objects.filter(pk=self.kamyo.pk).exists())
