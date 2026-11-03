"""Güvenlik düzeltmeleri: başka kurumun hesabı, parola bağlantısının adresi, açık yönlendirme, denetim IP'si,
yedek karşılaştırmasının tekrarı."""

from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
User = get_user_model()  # KAMYOSİS: özel kullanıcı modeli
from django.core import mail
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from timetable import backup
from timetable.access import client_ip
from timetable.institutions import is_local_path
from timetable.models import Institution, Membership as M, School, Teacher


class ForeignAccountTests(TestCase):
    def setUp(self):
        self.ours = Institution.objects.create(name="A Kurumu")
        self.theirs = Institution.objects.create(name="B Kurumu")
        self.school = School.objects.create(name="MYO", institution=self.ours)
        self.manager = User.objects.create_user("yonetici", password="pw")
        M.objects.create(user=self.manager, institution=self.ours, permissions=list(M.ALL))
        self.victim = User.objects.create_user("b_mudur", password="Eski-parola-2026", email="b@x.tr")
        M.objects.create(user=self.victim, institution=self.theirs, permissions=list(M.ALL))
        self.client.force_login(self.manager)

    def test_manager_cannot_attach_user_of_another_institution(self):
        url = reverse("timetable:institution_users", args=[self.ours.pk])
        self.client.post(url, {"action": "add", "username": "b_mudur", "permissions": [M.DATA]}, follow=True)
        self.assertFalse(M.objects.filter(user=self.victim, institution=self.ours).exists())

    def test_central_admin_can_still_attach(self):
        self.client.force_login(User.objects.create_superuser("merkez", "m@x.tr", "pw"))
        url = reverse("timetable:institution_users", args=[self.ours.pk])
        self.client.post(url, {"action": "add", "username": "b_mudur", "permissions": [M.DATA]})
        self.assertTrue(M.objects.filter(user=self.victim, institution=self.ours).exists())

    def test_temporary_password_is_refused_for_foreign_account(self):
        teacher = Teacher.objects.create(school=self.school, first_name="Bora", last_name="Er", user=self.victim,
                                         email="saldirgan@x.tr")
        url = reverse("timetable:teacher_accounts", args=[self.school.pk])
        self.client.post(url, {"action": "parola", "teacher": [teacher.pk]}, follow=True)
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.check_password("Eski-parola-2026"))
        self.assertEqual(self.victim.email, "b@x.tr")  # e-postası da saldırganınkiyle değişmez

    def test_own_teacher_account_still_gets_temporary_password(self):
        teacher = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya")
        url = reverse("timetable:teacher_accounts", args=[self.school.pk])
        self.client.post(url, {"action": "parola", "teacher": [teacher.pk]})
        teacher.refresh_from_db()
        self.assertIsNotNone(teacher.user)
        self.assertTrue(teacher.user.has_usable_password())


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", ALLOWED_HOSTS=["*"], PUBLIC_URL="")
class ResetLinkHostTests(TestCase):
    def setUp(self):
        User.objects.create_user("ali", email="ali@x.tr", password="pw")
        self.url = reverse("timetable:password_forgot")

    def test_untrusted_host_gets_no_mail(self):
        response = self.client.post(self.url, {"email": "ali@x.tr"}, HTTP_HOST="evil.example.com")
        self.assertEqual(response.status_code, 302)  # yanıt aynı: hesabın varlığı sızmaz
        self.assertEqual(mail.outbox, [])

    def test_tailscale_address_is_trusted(self):
        self.client.post(self.url, {"email": "ali@x.tr"}, HTTP_HOST="100.78.183.16:8000")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("http://100.78.183.16:8000/", mail.outbox[0].body)

    @override_settings(PUBLIC_URL="https://ders.okul.edu.tr")
    def test_public_url_wins(self):
        self.client.post(self.url, {"email": "ali@x.tr"}, HTTP_HOST="evil.example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://ders.okul.edu.tr/", mail.outbox[0].body)
        self.assertNotIn("evil", mail.outbox[0].body)


class SmallFixTests(SimpleTestCase):
    def test_local_path(self):
        self.assertTrue(is_local_path("/okul/1/raporlar/"))
        for target in ("//evil.com", "/\\evil.com", "http://evil.com", "", "evil.com"):
            self.assertFalse(is_local_path(target), target)

    def test_forwarded_for_only_behind_proxy(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.5")
        self.assertEqual(client_ip(request), "10.0.0.5")
        with override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")):
            self.assertEqual(client_ip(request), "1.2.3.4")

    def test_compare_is_not_started_twice(self):
        school = mock.Mock(pk=987)
        with mock.patch.object(backup, "compare"), mock.patch("threading.Thread"):
            self.assertTrue(backup.compare_start(Path("yedek-2026-01-01-0300.json.gz"), school))
            self.assertFalse(backup.compare_start(Path("yedek-2026-01-01-0300.json.gz"), school))
        backup._running.discard(987)
