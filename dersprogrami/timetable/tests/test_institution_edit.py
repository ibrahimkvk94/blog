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
        self.assertContains(page, f'{{"id": {self.kamyo.pk}, "name"')  # taşıma hedefi
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
        # Hedef kurumda program yetkisi yoksa o kurum taşıma hedeflerinde çıkmaz ve taşınamaz
        self.assertNotContains(self.client.get(self.url(self.kamyo)), f'{{"id": {self.asc.pk}, "name"')
        self.client.post(self.url(self.kamyo), {"action": "move_program", "program": self.main.pk, "target": self.asc.pk})
        self.main.refresh_from_db()
        self.assertEqual(self.main.institution, self.kamyo)
        # Programı olan kurum silinemez (merkez değil)
        self.client.post(self.url(self.kamyo), {"action": "delete"})
        self.assertTrue(Institution.objects.filter(pk=self.kamyo.pk).exists())


class ProgramMenuTests(TestCase):
    """Sağ tık menüsü: sayfalar menü verisini taşır; menünün formları işlemleri yapıp geldiği sayfaya döner."""

    def setUp(self):
        self.kamyo = Institution.objects.create(name="KAMYO")
        self.other = Institution.objects.create(name="Boş kurum")
        self.school = School.objects.create(name="Güz", institution=self.kamyo)
        self.client.force_login(User.objects.create_superuser("merkez", "m@x.tr", "pw"))

    def test_pages_carry_menu(self):
        for url in (reverse("timetable:school_list"), reverse("timetable:institution_detail", args=[self.kamyo.pk])):
            page = self.client.get(url)
            self.assertContains(page, f'data-pm="program" data-pm-id="{self.school.pk}"')
            self.assertContains(page, "program_menu.js")
            self.assertContains(page, f'{{"id": {self.other.pk}, "name"')  # taşıma hedefleri
        self.assertContains(self.client.get(reverse("timetable:school_list")), 'data-pm-deletable="1"')  # boş kurum silinebilir

    def test_rename_and_move_return_to_list(self):
        inst_url = reverse("timetable:institution_detail", args=[self.kamyo.pk])
        response = self.client.post(inst_url, {"action": "rename_program", "program": self.school.pk, "name": "Bahar", "next": "/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        response = self.client.post(inst_url, {"action": "move_program", "program": self.school.pk, "target": self.other.pk,
                                               "next": "https://evil.example/"})
        self.assertRedirects(response, inst_url, fetch_redirect_response=False)  # dış adrese dönülmez
        self.school.refresh_from_db()
        self.assertEqual((self.school.name, self.school.institution), ("Bahar", self.other))

    def test_delete_program_needs_exact_name(self):
        url = reverse("timetable:program_delete", args=[self.school.pk])
        self.client.post(url, {"confirm": "yanlış", "next": "/"})
        self.assertTrue(School.objects.filter(pk=self.school.pk).exists())
        response = self.client.post(url, {"confirm": "Güz", "next": "/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertFalse(School.objects.filter(pk=self.school.pk).exists())
