"""Öğretmen istek formu: öğretmen bildirir, program sorumlusu onaylar, müsaitliğe yazılır."""

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable import teacher_requests as tr
from timetable.models import (Availability, AvailabilityRequest, Card, Institution, Lesson, Membership, Period, School,
                              SchoolClass, Subject, Teacher, Timetable)

R = AvailabilityRequest


class TeacherRequestTests(TestCase):
    def setUp(self):
        inst = Institution.objects.create(name="Kurum")
        self.school = School.objects.create(name="MYO", days_per_week=2, institution=inst)
        for i in range(3):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        Availability.objects.create(school=self.school, day=1, period=2, state=Availability.NO)  # okul geneli kapalı
        self.user = User.objects.create_user("ali", password="pw", first_name="Ali", last_name="Kaya")
        Membership.objects.create(user=self.user, institution=inst, permissions=[Membership.VIEW])
        self.teacher = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya", email="ali@x.tr")
        Availability.objects.create(school=self.school, teacher=self.teacher, day=1, period=0, state=Availability.NO)
        self.manager = User.objects.create_user("mudur", password="pw")
        Membership.objects.create(user=self.manager, institution=inst, permissions=[Membership.VIEW, Membership.DATA])
        self.manage_url = reverse("timetable:teacher_requests", args=[self.school.pk])
        self.my_url = reverse("timetable:my_requests")

    def test_unlinked_user_sees_hint(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.my_url), "bir öğretmen kartına bağlı değil")

    def test_manager_links_account_and_suggestion(self):
        self.client.force_login(self.manager)
        page = self.client.get(self.manage_url)
        self.assertContains(page, f'data-suggest="{self.user.pk}"')
        self.client.post(self.manage_url, {"action": "link", f"hesap-{self.teacher.pk}": self.user.pk})
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.user, self.user)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_submit_approve_flow(self):
        self.teacher.user = self.user
        self.teacher.save()
        self.client.force_login(self.user)
        # Pzt 1 gelemem, Pzt 2 tercih etmem, Salı 1 (kayıtlı yasak) artık gelebilirim; Salı 3 okul geneli kapalı → yok sayılır
        self.client.post(self.my_url, {"ogretmen": self.teacher.pk, "h-0-0": "no", "h-0-1": "maybe", "h-1-0": "", "h-1-2": "no",
                                       "reason": "Hastane"})
        req = R.objects.get()
        self.assertEqual((req.status, req.reason), (R.PENDING, "Hastane"))
        self.assertEqual(sorted(map(tuple, req.changes)), [(0, 0, "no"), (0, 1, "maybe"), (1, 0, "")])
        # Yeniden gönderim bekleyen isteği günceller
        self.client.post(self.my_url, {"ogretmen": self.teacher.pk, "h-0-0": "no", "h-1-0": "no"})
        self.assertEqual(R.objects.count(), 1)
        self.assertEqual(R.objects.get().changes, [[0, 0, "no"]])
        # Öğretmen başka bir isteği onaylayamaz (yetkisi yok)
        self.assertEqual(self.client.post(self.manage_url, {"action": "approve", "istek": req.pk}).status_code, 403)
        # Sorumlu onaylar → müsaitlik yazılır, e-posta gider
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(self.manage_url), "Ali Kaya")
        self.client.post(self.manage_url, {"action": "approve", "istek": req.pk, "note": "Tamam"})
        req.refresh_from_db()
        self.assertEqual((req.status, req.decided_by, req.note), (R.APPROVED, self.manager, "Tamam"))
        self.assertEqual(set(self.teacher.availabilities.values_list("day", "period", "state")), {(0, 0, "no"), (1, 0, "no")})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("onaylandı", mail.outbox[0].subject)

    def test_free_request_removes_restriction_and_reject(self):
        req, _ = tr.submit(self.teacher, self.user, {}, "")  # Salı 1 kısıtını kaldır
        self.assertEqual(req.changes, [[1, 0, ""]])
        tr.approve(req, self.manager)
        self.assertFalse(self.teacher.availabilities.exists())
        req2, _ = tr.submit(self.teacher, self.user, {(0, 2): "no"}, "")
        tr.reject(req2, self.manager, "Olmaz")
        self.assertFalse(self.teacher.availabilities.exists())
        self.assertEqual(R.objects.get(pk=req2.pk).status, R.REJECTED)

    def test_no_change_withdraws_pending(self):
        tr.submit(self.teacher, self.user, {(0, 0): "no", (1, 0): "no"}, "")
        req, message = tr.submit(self.teacher, self.user, {(1, 0): "no"}, "")
        self.assertIsNone(req)
        self.assertEqual(R.objects.get().status, R.WITHDRAWN)

    def test_conflicts_with_timetable(self):
        cls = SchoolClass.objects.create(school=self.school, name="1A")
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Fizik"), periods_per_week=2)
        lesson.classes.set([cls])
        lesson.teachers.set([self.teacher])
        timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        Card.objects.create(timetable=timetable, lesson=lesson, length=2, day=0, period=0)
        req, _ = tr.submit(self.teacher, self.user, {(0, 1): "no", (1, 0): "no"}, "")
        self.assertEqual(tr.conflicts(req, timetable), ["Pazartesi 2. saat: Fizik (1A)"])
