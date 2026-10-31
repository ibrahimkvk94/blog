"""Gruplu menü, bölüm sekmeleri ve hızlı git (Ctrl+K) araması."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.models import Institution, Membership, School, SchoolClass, Teacher


class NavigationTests(TestCase):
    def setUp(self):
        inst = Institution.objects.create(name="Kurum")
        self.school = School.objects.create(name="MYO", institution=inst)
        Teacher.objects.create(school=self.school, first_name="Mehmet", last_name="Albayram", department="ELN")
        SchoolClass.objects.create(school=self.school, name="1.KISIM", short="1SVN")
        self.viewer = User.objects.create_user("izleyici", password="pw")
        Membership.objects.create(user=self.viewer, institution=inst, permissions=[Membership.VIEW])
        self.admin = User.objects.create_superuser("admin", "a@x.tr", "pw")

    def test_grouped_sidebar_and_section_tabs(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("timetable:data_list", args=[self.school.pk, "ogretmenler"]))
        self.assertContains(page, 'data-nav-group="veri"')
        self.assertContains(page, 'data-nav-group="kurallar"')
        self.assertContains(page, '<nav class="subnav" aria-label="Veri girişi">')
        self.assertContains(page, "Binalar</a>")  # yalnızca sekmede
        self.assertContains(page, 'id="palette"')
        # Görüntüleme yetkisi: veri grupları görünmez
        self.client.force_login(self.viewer)
        page = self.client.get(reverse("timetable:school_detail", args=[self.school.pk]))
        self.assertNotContains(page, 'data-nav-group="veri"')
        self.assertContains(page, 'data-nav-group="gunluk"')

    def test_quick_search(self):
        url = reverse("timetable:quick_search", args=[self.school.pk])
        self.client.force_login(self.admin)
        results = self.client.get(url, {"q": "albay"}).json()["results"]
        self.assertEqual([(r["kind"], r["label"]) for r in results], [("Öğretmen", "Mehmet Albayram")])
        self.assertEqual(self.client.get(url, {"q": "1svn"}).json()["results"][0]["kind"], "Sınıf")
        self.client.force_login(self.viewer)  # düzenleme yetkisi yoksa kayıt sonucu yok
        self.assertEqual(self.client.get(url, {"q": "albay"}).json()["results"], [])
