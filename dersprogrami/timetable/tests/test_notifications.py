"""Bildirimler: olaylardan bildirim, zil verisi, okundu işareti, geçmiş sayfası ve merkezden duyuru."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import notifications
from timetable import teacher_requests as tr
from timetable.demo import create_demo_school
from timetable.models import Institution, Membership, Notification, Teacher, Timetable
from timetable.services import run_generation


class NotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.manager = User.objects.create_user("sorumlu", password="pw")
        Membership.objects.create(user=cls.manager, institution=cls.school.institution, permissions=[Membership.VIEW, Membership.DATA, Membership.PROGRAM])
        cls.teacher_user = User.objects.create_user("ogretmen", password="pw")
        cls.teacher = Teacher.objects.filter(school=cls.school).first()
        cls.teacher.user = cls.teacher_user
        cls.teacher.save(update_fields=["user"])
        cls.admin = User.objects.create_superuser("merkez", "m@x.tr", "pw")

    def test_generation_notifies_starter(self):
        tt = Timetable.objects.create(school=self.school, name="Deneme", status=Timetable.RUNNING, time_limit=15,
                                      report={"by": self.manager.pk})
        run_generation(tt.pk)
        n = Notification.objects.get(user=self.manager)
        self.assertEqual(n.title, "Program hazır: Deneme")
        self.assertEqual(n.level, Notification.SUCCESS)
        self.assertEqual(n.url, reverse("timetable:timetable_detail", args=[tt.pk]))

    def test_request_flow(self):
        req, _ = tr.submit(self.teacher, self.teacher_user, {(0, 0): "no"}, "Doktor randevusu")
        sent = Notification.objects.get(user=self.manager)
        self.assertIn("müsaitlik isteği", sent.title)
        self.assertFalse(Notification.objects.filter(user=self.teacher_user).exists())  # kendi işine bildirim yok
        tr.approve(req, self.manager, "Uygun")
        got = Notification.objects.get(user=self.teacher_user)
        self.assertEqual(got.title, "Müsaitlik isteğiniz onaylandı")
        self.assertEqual(got.level, Notification.SUCCESS)

    def test_bell_api_toasts_and_read(self):
        old = notifications.send([self.manager], "Eski")
        first = Notification.objects.get(user=self.manager)
        self.client.force_login(self.manager)
        url = reverse("timetable:api_notifications")
        data = self.client.get(url).json()
        self.assertEqual((data["unread"], data["last_id"], data["latest"][0]["title"]), (1, first.pk, "Eski"))
        self.assertEqual(old, 1)
        notifications.send([self.manager], "Yeni", "ayrıntı", "/bildirimler/", Notification.WARNING)
        data = self.client.get(url + f"?sonra={first.pk}").json()
        self.assertEqual([n["title"] for n in data["new"]], ["Yeni"])  # yalnızca yeni olan toast olur
        self.client.post(reverse("timetable:api_notifications_read"), data='{"all": true}', content_type="application/json")
        self.assertEqual(self.client.get(url).json()["unread"], 0)
        page = self.client.get(reverse("timetable:notifications"))
        self.assertContains(page, "Yeni")
        self.assertContains(page, "data-ntf-toggle")  # zil şeritte

    def test_open_marks_read_and_redirects(self):
        notifications.send([self.manager], "Git", url="/bildirimler/")
        n = Notification.objects.get(user=self.manager)
        self.client.force_login(self.manager)
        response = self.client.get(reverse("timetable:notification_open", args=[n.pk]))
        self.assertRedirects(response, "/bildirimler/", fetch_redirect_response=False)
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)
        self.client.force_login(self.teacher_user)  # başkasının bildirimi açılamaz
        self.assertEqual(self.client.get(reverse("timetable:notification_open", args=[n.pk])).status_code, 404)

    def test_broadcast(self):
        url = reverse("timetable:broadcast")
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(url).status_code, 403)  # yalnızca merkez
        self.client.force_login(self.admin)
        other = Institution.objects.create(name="Başka kurum")
        outsider = User.objects.create_user("dis", password="pw")
        Membership.objects.create(user=outsider, institution=other, permissions=[Membership.VIEW])
        self.client.post(url, {"title": "Kurum duyurusu", "kurum": self.school.institution_id, "level": "info"})
        self.assertTrue(Notification.objects.filter(user=self.manager, title="Kurum duyurusu").exists())
        self.assertFalse(Notification.objects.filter(user=outsider, title="Kurum duyurusu").exists())
        self.client.post(url, {"title": "Herkese", "kurum": "", "level": "warning", "url": "http://dis.example/"})
        everyone = Notification.objects.filter(title="Herkese")
        self.assertEqual(everyone.count(), User.objects.filter(is_active=True).count())
        self.assertEqual(set(everyone.values_list("url", flat=True)), {""})  # dış bağlantı kabul edilmez
        self.assertContains(self.client.get(url), "Herkese")
