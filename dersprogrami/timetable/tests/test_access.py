"""Çok okullu yapı ve yetkilendirme."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.models import Membership, School
from timetable.services import generate_timetable
from timetable.tests.test_operations import build_school

M = Membership


class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = build_school()
        cls.other = School.objects.create(name="Başka okul")
        cls.timetable = generate_timetable(cls.school, "ilk", time_limit=10)
        cls.central = User.objects.create_superuser("merkez", password="parola-123456")
        cls.admin = User.objects.create_user("mudur", password="parola-123456")
        M.objects.create(user=cls.admin, school=cls.school, permissions=M.ALL)
        cls.viewer = User.objects.create_user("izleyici", password="parola-123456")
        M.objects.create(user=cls.viewer, school=cls.school, permissions=[])

    def test_login_page_and_school_list_filtering(self):
        self.assertEqual(self.client.get(reverse("timetable:login")).status_code, 200)
        self.assertTrue(self.client.login(username="mudur", password="parola-123456"))
        page = self.client.get(reverse("timetable:school_list"))
        self.assertContains(page, self.school.name)
        self.assertNotContains(page, "Başka okul")
        self.assertNotContains(page, "Merkez paneli")
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.other.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("timetable:central")).status_code, 403)
        self.assertEqual(self.client.post(reverse("timetable:create_demo")).status_code, 403)

    def test_viewer_can_read_but_not_edit(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:api_grid", args=[self.timetable.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:report_render", args=[self.timetable.pk]) + "?tur=carsaf").status_code, 200)
        card = self.timetable.cards.first()
        response = self.client.post(reverse("timetable:api_card_move", args=[card.pk]), json.dumps({"day": 0, "period": 0}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertIn("yetkiniz yok", response.json()["message"])
        response = self.client.post(reverse("timetable:data_new", args=[self.school.pk, "ders-adlari"]), {"name": "X"})
        self.assertEqual(response.status_code, 403)
        page = self.client.get(reverse("timetable:school_detail", args=[self.school.pk]))
        self.assertNotContains(page, "Ders dağıtımı")  # veri menüsü gizli
        self.assertEqual(self.client.get(reverse("timetable:school_users", args=[self.school.pk])).status_code, 403)

    def test_delegation_is_limited_to_own_permissions(self):
        lead = User.objects.create_user("zumre", password="parola-123456")
        M.objects.create(user=lead, school=self.school, permissions=[M.DATA, M.USERS])
        self.client.force_login(lead)
        url = reverse("timetable:school_users", args=[self.school.pk])
        response = self.client.post(url, {"action": "add", "username": "ogretmen1", "password": "Guclu-Parola-2026",
                                          "permissions": [M.DATA, M.PROGRAM, M.PUBLISH]})
        self.assertRedirects(response, url)
        member = M.objects.get(user__username="ogretmen1")
        self.assertEqual(member.permissions, [M.DATA])  # program/yayın verilemedi
        # Sizden yetkili kullanıcıyı (müdür) değiştiremez
        boss = M.objects.get(user=self.admin)
        self.client.post(url, {"action": "update", "membership": boss.pk, "permissions": []})
        boss.refresh_from_db()
        self.assertEqual(boss.permissions, M.ALL)
        # Kendi eklediğinin yetkisini değiştirebilir ve çıkarabilir
        self.client.post(url, {"action": "update", "membership": member.pk, "permissions": []})
        member.refresh_from_db()
        self.assertEqual(member.permissions, [])
        self.client.post(url, {"action": "password", "membership": member.pk, "password": "Yeni-Parola-2026"})
        self.assertTrue(User.objects.get(username="ogretmen1").check_password("Yeni-Parola-2026"))
        self.client.post(url, {"action": "remove", "membership": member.pk})
        self.assertFalse(M.objects.filter(pk=member.pk).exists())
        # Yeni kullanıcı yalnızca bu okulu görür
        self.client.force_login(User.objects.get(username="ogretmen1"))
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])).status_code, 403)

    def test_central_creates_school_with_admin(self):
        self.client.force_login(self.central)
        self.assertContains(self.client.get(reverse("timetable:central")), "Okul ekle")
        response = self.client.post(reverse("timetable:central_school_new"), {
            "school_name": "Yeni Lise", "username": "yenimudur", "password": "Guclu-Parola-2026", "permissions": M.ALL,
        })
        self.assertRedirects(response, reverse("timetable:central"))
        school = School.objects.get(name="Yeni Lise")
        self.assertEqual(school.periods.count(), 8)
        membership = M.objects.get(school=school)
        self.assertEqual(membership.user.username, "yenimudur")
        self.client.force_login(membership.user)
        self.assertEqual(self.client.get(reverse("timetable:school_users", args=[school.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])).status_code, 403)

    def test_account_page(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse("timetable:account")), self.school.name)
        response = self.client.post(reverse("timetable:account"), {
            "old_password": "parola-123456", "new_password1": "Baska-Parola-2026", "new_password2": "Baska-Parola-2026",
        })
        self.assertRedirects(response, reverse("timetable:account"))
        self.assertTrue(User.objects.get(username="izleyici").check_password("Baska-Parola-2026"))
