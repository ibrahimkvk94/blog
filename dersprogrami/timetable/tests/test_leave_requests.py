"""Tarihli izin/rapor bildirimi: öğretmen bildirir, sorumlu onaylar, günler vekâlet ekranına düşer."""

import datetime

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from timetable import substitutes
from timetable.models import (Absence, Card, Institution, LeaveRequest, Lesson, Membership, Period, School, SchoolClass,
                              Subject, Teacher, Timetable)

MONDAY = datetime.date(2026, 11, 2)


class LeaveRequestTests(TestCase):
    def setUp(self):
        inst = Institution.objects.create(name="Kurum")
        self.school = School.objects.create(name="MYO", days_per_week=5, institution=inst)
        for i in range(3):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.user = User.objects.create_user("ali", password="pw")
        Membership.objects.create(user=self.user, institution=inst, permissions=[Membership.VIEW])
        self.ali = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya", user=self.user, email="ali@x.tr")
        self.can = Teacher.objects.create(school=self.school, first_name="Can", last_name="Er")
        self.manager = User.objects.create_user("mudur", password="pw")
        Membership.objects.create(user=self.manager, institution=inst, permissions=[Membership.VIEW, Membership.DATA])
        self.tt = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        self.school.active_timetable = self.tt
        self.school.save()
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="Fizik"), periods_per_week=3)
        lesson.classes.add(SchoolClass.objects.create(school=self.school, name="1A"))
        lesson.teachers.add(self.ali)
        Card.objects.create(timetable=self.tt, lesson=lesson, length=3, day=0, period=0)  # pazartesi 1-3
        self.my_url = reverse("timetable:my_requests")
        self.manage_url = reverse("timetable:teacher_requests", args=[self.school.pk])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_partial_leave_flow(self):
        self.client.force_login(self.user)
        # Pazartesi–Pazar arası, yalnızca 2. ve 3. saat (cumartesi/pazar okul günü değil)
        self.client.post(self.my_url, {"ogretmen": self.ali.pk, "action": "leave", "tur": "gorev", "baslangic": "2026-11-02",
                                       "bitis": "2026-11-08", "saat": ["1", "2"], "aciklama": "Seminer"})
        leave = LeaveRequest.objects.get()
        self.assertEqual((leave.periods, len(leave.school_days()), leave.kind), ([1, 2], 5, "gorev"))
        self.client.force_login(self.manager)
        page = self.client.get(self.manage_url)
        self.assertContains(page, "İzin ve rapor bildirimleri")
        self.assertEqual(page.context["leaves"][0]["affected"], 2)  # pazartesi 2. ve 3. saat
        self.client.post(self.manage_url, {"action": "leave_approve", "izin": leave.pk, "note": "Kolay gelsin"})
        self.assertEqual(Absence.objects.filter(teacher=self.ali).count(), 5)
        absence = Absence.objects.get(teacher=self.ali, date=MONDAY)
        self.assertEqual((absence.periods, absence.reason), ([1, 2], "Görevlendirme: Seminer"))
        self.assertIn("onaylandı", mail.outbox[0].subject)
        # Vekâlet planında yalnızca 2. ve 3. saat vekil bekler
        plan = substitutes.day_plan(self.school, self.tt, MONDAY)
        self.assertEqual([s["period"] for s in plan[0]["slots"]], [1, 2])

    def test_full_day_merges_and_validation(self):
        Absence.objects.create(school=self.school, teacher=self.ali, date=MONDAY, periods=[0])
        leave = LeaveRequest.objects.create(school=self.school, teacher=self.ali, start_date=MONDAY, end_date=MONDAY)
        from timetable import teacher_requests as tr

        tr.approve_leave(leave, self.manager)
        self.assertEqual(Absence.objects.get(teacher=self.ali, date=MONDAY).periods, [])  # tüm gün kapsar
        self.client.force_login(self.user)
        self.client.post(self.my_url, {"ogretmen": self.ali.pk, "action": "leave", "baslangic": "2026-11-05", "bitis": "2026-11-04", "tum_gun": "1"})
        self.client.post(self.my_url, {"ogretmen": self.ali.pk, "action": "leave", "baslangic": "2026-11-07", "bitis": "2026-11-08", "tum_gun": "1"})
        self.assertEqual(LeaveRequest.objects.count(), 1)  # ters aralık ve hafta sonu reddedildi
        # Öğretmen bekleyen bildirimini geri alabilir; sorumlu yetkisi olmayan onaylayamaz
        pending = LeaveRequest.objects.create(school=self.school, teacher=self.ali, start_date=MONDAY, end_date=MONDAY)
        self.assertEqual(self.client.post(self.manage_url, {"action": "leave_approve", "izin": pending.pk}).status_code, 403)
        self.client.post(self.my_url, {"ogretmen": self.ali.pk, "action": "leave_withdraw", "izin": pending.pk})
        self.assertEqual(LeaveRequest.objects.get(pk=pending.pk).status, LeaveRequest.WITHDRAWN)
