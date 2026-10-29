"""Öğretmen hesapları: toplu açma, e-postayla davet, parola belirleme, geçici parola ve parolamı unuttum."""

import re

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable.models import Institution, Membership, School, Teacher


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TeacherAccountTests(TestCase):
    def setUp(self):
        inst = Institution.objects.create(name="Kurum")
        self.school = School.objects.create(name="MYO", institution=inst)
        self.ali = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Şahin", email="ali.sahin@okul.edu.tr")
        self.can = Teacher.objects.create(school=self.school, first_name="Can Özgür", last_name="Işık")
        self.admin = User.objects.create_superuser("admin", "a@x.tr", "pw")
        self.client.force_login(self.admin)
        self.url = reverse("timetable:teacher_accounts", args=[self.school.pk])

    def test_invite_set_password_and_login(self):
        page = self.client.post(self.url, {"action": "otomatik", "teacher": [self.ali.pk, self.can.pk]})
        self.ali.refresh_from_db()
        self.can.refresh_from_db()
        self.assertEqual((self.ali.user.username, self.can.user.username), ("ali.sahin", "can.isik"))
        self.assertFalse(self.ali.user.has_usable_password())
        # e-postası olmayan için geçici parola yalnızca bu yanıtta
        self.assertContains(page, "can.isik")
        password = re.search(r"<dt>Geçici parola</dt><dd><code>([^<]+)</code>", page.content.decode()).group(1)
        self.assertTrue(self.can.user.check_password(password))
        # davet e-postasındaki bağlantıyla parola belirleme
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://\S+/parola-belirle/\S+/", mail.outbox[0].body).group(0)
        self.client.logout()
        form = self.client.get(link, follow=True)
        self.assertContains(form, "Parolanızı belirleyin")
        done = self.client.post(form.redirect_chain[-1][0] if form.redirect_chain else link,
                                {"new_password1": "Yeni-parola-2026", "new_password2": "Yeni-parola-2026"}, follow=True)
        self.assertContains(done, "Parolanız kaydedildi")
        self.assertTrue(self.client.login(username="ali.sahin", password="Yeni-parola-2026"))
        # yalnızca öğretmen hesabı: ana sayfa kendi programına gider, okul sayfaları kapalı
        self.assertRedirects(self.client.get(reverse("timetable:school_list")), reverse("timetable:my_timetable"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])).status_code, 403)
        self.assertEqual(self.client.get(link, follow=True).status_code, 200)  # kullanılmış bağlantı: geçersiz sayfası

    def test_forgot_password_reaches_invited_account(self):
        self.client.post(self.url, {"action": "davet", "teacher": [self.ali.pk]})
        mail.outbox.clear()
        self.client.logout()
        self.client.post(reverse("timetable:password_forgot"), {"email": "ALI.SAHIN@okul.edu.tr"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ali.sahin", mail.outbox[0].body)

    def test_unlink_deletes_teacher_only_account_and_permission(self):
        self.client.post(self.url, {"action": "parola", "teacher": [self.can.pk]})
        user_id = Teacher.objects.get(pk=self.can.pk).user_id
        self.client.post(self.url, {"action": "ayir", "teacher": [self.can.pk]})
        self.assertFalse(User.objects.filter(pk=user_id).exists())
        data_user = User.objects.create_user("veri", password="pw")
        Membership.objects.create(user=data_user, institution=self.school.institution, permissions=[Membership.DATA])
        self.client.force_login(data_user)
        self.assertEqual(self.client.get(self.url).status_code, 403)  # kullanıcı yönetimi yetkisi gerekir
