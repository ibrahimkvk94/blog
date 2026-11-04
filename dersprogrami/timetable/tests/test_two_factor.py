"""İsteğe bağlı iki adımlı giriş (doğrulama uygulaması kodu, kurtarma kodları, yönetici kaldırması)."""

import time
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from timetable import two_factor
from timetable.models import Institution, Membership, TwoFactor

User = get_user_model()  # KAMYOSİS: özel kullanıcı modeli
M = Membership
PASSWORD = "parola-123456"


def now_code(record, offset=0):
    return two_factor.code_at(record.secret, two_factor.current_step() + offset)


class TotpTests(TestCase):
    def test_rfc6238_vector(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890"
        self.assertEqual(two_factor.code_at(secret, two_factor.current_step(59)), "287082")
        self.assertEqual(two_factor.code_at(secret, two_factor.current_step(1111111109)), "081804")


class TwoFactorFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institution = Institution.objects.create(name="MYO")
        cls.manager = User.objects.create_user("mudur", password=PASSWORD)
        M.objects.create(user=cls.manager, institution=cls.institution, permissions=M.ALL)
        cls.user = User.objects.create_user("ali", password=PASSWORD)
        M.objects.create(user=cls.user, institution=cls.institution, permissions=[])

    def enable(self, user=None):
        record = two_factor.start_setup(user or self.user)
        return record, two_factor.confirm_setup(record, now_code(record))

    def login(self, next_url="/hesabim/"):
        return self.client.post(reverse("timetable:login") + f"?next={next_url}",
                                {"username": "ali", "password": PASSWORD, "next": next_url})

    def authenticated(self):
        return "_auth_user_id" in self.client.session

    def test_without_two_factor_login_is_unchanged(self):
        response = self.login()
        self.assertRedirects(response, "/hesabim/", fetch_redirect_response=False)
        self.assertTrue(self.authenticated())

    def test_setup_from_account_page(self):
        self.client.force_login(self.user)
        url = reverse("timetable:account_two_factor")
        self.assertContains(self.client.get(reverse("timetable:account")), "İki adımlı girişi aç")
        self.client.post(url, {"action": "start"})
        page = self.client.get(reverse("timetable:account")).content.decode()
        self.assertIn("<svg", page)  # karekod
        record = TwoFactor.objects.get(user=self.user)
        self.assertIsNone(record.confirmed_at)
        self.assertIn(two_factor.spaced_secret(record), page)
        self.assertFalse(two_factor.is_enabled(self.user))  # doğrulanmadan açılmaz

        self.client.post(url, {"action": "confirm", "code": "000000" if now_code(record) != "000000" else "111111"})
        self.assertFalse(two_factor.is_enabled(self.user))
        self.client.post(url, {"action": "confirm", "code": now_code(record)})
        self.assertTrue(two_factor.is_enabled(self.user))
        page = self.client.get(reverse("timetable:account")).content.decode()
        self.assertIn("Kurtarma kodlarınız", page)
        self.assertEqual(len(TwoFactor.objects.get(user=self.user).recovery_codes), two_factor.RECOVERY_COUNT)
        self.assertNotIn("Kurtarma kodlarınız", self.client.get(reverse("timetable:account")).content.decode())  # bir kez

    def test_login_asks_for_code_and_code_is_single_use(self):
        record, _ = self.enable()
        response = self.login()
        self.assertRedirects(response, reverse("timetable:login_verify"), fetch_redirect_response=False)
        self.assertFalse(self.authenticated())
        self.assertRedirects(self.client.get("/hesabim/"), reverse("timetable:login") + "?next=/hesabim/",
                             fetch_redirect_response=False)
        page = self.client.post(reverse("timetable:login_verify"), {"code": "12"})
        self.assertContains(page, "Kod hatalı")
        self.assertFalse(self.authenticated())

        code = now_code(record, 1)  # bir sonraki adımın kodu da (saat kayması) kabul edilir
        response = self.client.post(reverse("timetable:login_verify"), {"code": code[:3] + " " + code[3:]})
        self.assertRedirects(response, "/hesabim/", fetch_redirect_response=False)
        self.assertTrue(self.authenticated())

        self.client.logout()
        self.login()
        self.client.post(reverse("timetable:login_verify"), {"code": code})
        self.assertFalse(self.authenticated())  # aynı kod ikinci kez geçmez
        self.client.post(reverse("timetable:login_verify"), {"code": now_code(record)})
        self.assertFalse(self.authenticated())  # daha eski adımın kodu da geçmez

    def test_recovery_code_works_once(self):
        record, codes = self.enable()
        self.login()
        response = self.client.post(reverse("timetable:login_verify"), {"code": codes[0].lower()}, follow=True)
        self.assertTrue(self.authenticated())
        self.assertContains(response, f"{two_factor.RECOVERY_COUNT - 1} kod kaldı")
        self.client.logout()
        self.login()
        self.client.post(reverse("timetable:login_verify"), {"code": codes[0]})
        self.assertFalse(self.authenticated())

    def test_too_many_wrong_codes_and_expiry_end_the_attempt(self):
        record, _ = self.enable()
        wrong = "999999" if now_code(record) != "999999" else "888888"
        self.login()
        for _ in range(two_factor.MAX_TRIES):
            response = self.client.post(reverse("timetable:login_verify"), {"code": wrong})
        self.assertRedirects(response, reverse("timetable:login"), fetch_redirect_response=False)
        self.client.post(reverse("timetable:login_verify"), {"code": now_code(record)})
        self.assertFalse(self.authenticated())

        self.login()
        later = time.time() + two_factor.PENDING_SECONDS + 5
        with mock.patch("timetable.accounts.time.time", return_value=later):
            response = self.client.post(reverse("timetable:login_verify"), {"code": now_code(record)})
        self.assertRedirects(response, reverse("timetable:login"), fetch_redirect_response=False)
        self.assertFalse(self.authenticated())
        self.assertRedirects(self.client.get(reverse("timetable:login_verify")), reverse("timetable:login"),
                             fetch_redirect_response=False)

    def test_disable_and_new_recovery_codes_need_the_password(self):
        record, codes = self.enable()
        self.client.force_login(self.user)
        url = reverse("timetable:account_two_factor")
        self.client.post(url, {"action": "disable", "password": "yanlis"})
        self.assertTrue(two_factor.is_enabled(self.user))
        self.client.post(url, {"action": "recovery", "password": PASSWORD})
        self.assertNotIn(two_factor._digest(codes[0]), TwoFactor.objects.get(user=self.user).recovery_codes)
        self.client.post(url, {"action": "disable", "password": PASSWORD})
        self.assertFalse(TwoFactor.objects.filter(user=self.user).exists())
        self.client.logout()
        self.login()
        self.assertTrue(self.authenticated())

    def test_manager_can_remove_a_users_two_factor(self):
        self.enable()
        self.client.force_login(self.manager)
        url = reverse("timetable:institution_users", args=[self.institution.pk])
        self.assertContains(self.client.get(url), "2 adımlı")
        membership = M.objects.get(user=self.user)
        self.client.post(url, {"action": "two_factor_reset", "membership": membership.pk})
        self.assertFalse(two_factor.is_enabled(self.user))

    def test_management_command(self):
        self.enable(self.manager)
        out = StringIO()
        call_command("iki_adimli_kapat", "mudur", stdout=out)
        self.assertFalse(two_factor.is_enabled(self.manager))
        self.assertIn("kaldırıldı", out.getvalue())
