"""Müsaitlik değişince yerel onarım: yeni kapalı saate düşen kartların tespiti, uyarı ve en az değişiklikle onarım."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import access, availability_repair as ar
from timetable.models import (Availability, AvailabilityRequest, Card, Lesson, Period, School, SchoolClass, Subject,
                              Teacher, Timetable)
from timetable.resolve import ResolveError
from timetable.services import verify_timetable


def hard(tt):
    return sum(1 for v in verify_timetable(tt)[0] if v.level == "hard")


class AvailabilityRepairTests(TestCase):
    """1 gün × 3 saat. 10-A: MAT (Ahmet Er) 1. saat, FİZ (Can Ak) 2. saat; 10-B: KİM (Ali Kaya) 1. saat."""

    def setUp(self):
        self.school = School.objects.create(name="Lise", days_per_week=1)
        for i in range(3):
            Period.objects.create(school=self.school, index=i, name=f"{i + 1}. saat")
        self.a = SchoolClass.objects.create(school=self.school, name="10-A", short="10-A")
        self.b = SchoolClass.objects.create(school=self.school, name="10-B", short="10-B")
        self.ahmet = Teacher.objects.create(school=self.school, first_name="Ahmet", last_name="Er")
        self.can = Teacher.objects.create(school=self.school, first_name="Can", last_name="Ak")
        self.ali = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya")
        self.tt = Timetable.objects.create(school=self.school, name="Program", status=Timetable.OK)
        self.school.working_timetable = self.tt
        self.school.save()
        self.mat = self._card("MAT", self.a, self.ahmet, 0)
        self.fiz = self._card("FİZ", self.a, self.can, 1)
        self.kim = self._card("KİM", self.b, self.ali, 0)
        self.admin = User.objects.create_superuser("admin", "a@x.tr", "pw")
        self.client.force_login(self.admin)

    def _card(self, name, cls, teacher, period):
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name=name, short=name))
        lesson.classes.add(cls)
        lesson.teachers.add(teacher)
        return Card.objects.create(timetable=self.tt, lesson=lesson, day=0, period=period)

    def _close(self, teacher, *periods):
        for p in periods:
            Availability.objects.create(school=self.school, teacher=teacher, day=0, period=p, state=Availability.NO)

    # --- tespit ------------------------------------------------------------------------------------

    def test_detection_lists_only_newly_conflicting_cards(self):
        self._close(self.ali, 0)  # önceden de kapalı (başka varlık): yeni sayılmaz
        watch = ar.Watch(self.school, [("teacher", self.ahmet.pk), ("teacher", self.ali.pk)])
        self.assertEqual(watch.before, {self.kim.pk})
        self._close(self.ahmet, 0, 2)  # 3. saatte dersi yok
        new = watch.new_conflicts()
        self.assertEqual([c["card_id"] for c in new], [self.mat.pk])
        self.assertEqual(new[0]["text"], "Ahmet Er: Pzt 1 MAT 10-A artık kapalı saatte")
        # Varlık filtresi: Can Ak'ın müsaitliği değişmedi, FİZ listelenmez; tüm program taraması ikisini de bulur
        self.assertEqual({c["card_id"] for c in ar.conflicts(self.tt)}, {self.mat.pk, self.kim.pk})
        self.assertEqual(ar.conflicts(self.tt, {("teacher", self.can.pk)}), [])

    def test_class_and_school_wide_closures(self):
        Availability.objects.create(school=self.school, school_class=self.a, day=0, period=1, state=Availability.NO)
        self.assertEqual([c["card_id"] for c in ar.conflicts(self.tt, {("school_class", self.a.pk)})], [self.fiz.pk])
        Availability.objects.create(school=self.school, day=0, period=0, state=Availability.NO)
        self.assertEqual({c["card_id"] for c in ar.conflicts(self.tt, {("school", None)})}, {self.mat.pk, self.kim.pk})
        Availability.objects.create(school=self.school, teacher=self.can, day=0, period=2, state=Availability.MAYBE)
        self.assertNotIn(self.fiz.pk, [c["card_id"] for c in ar.conflicts(self.tt, {("teacher", self.can.pk)})])  # koşullu kapalı değil

    def test_bulk_page_shows_alert_with_repair_button(self):
        url = reverse("timetable:bulk_availability", args=[self.school.pk])
        response = self.client.post(url, {"tur": "ogretmen", "copy_to": [self.ahmet.pk], "copy_mode": "close",
                                          "availability": json.dumps({"0-0": "no"})}, follow=True)
        self.assertContains(response, "1 dersi kapalı saate düşürdü")
        self.assertContains(response, "Ahmet Er: Pzt 1 MAT 10-A artık kapalı saatte")
        self.assertContains(response, "En az değişiklikle onar")
        self.assertContains(response, f'name="kart" value="{self.mat.pk}"')
        # Kapalı olmayan saat kapatılırsa uyarı yok
        response = self.client.post(url, {"tur": "ogretmen", "copy_to": [self.can.pk], "copy_mode": "close",
                                          "availability": json.dumps({"0-0": "no"})}, follow=True)
        self.assertNotContains(response, "kapalı saate düşürdü")

    def test_entity_editor_json_returns_alert(self):
        from timetable.forms import TeacherForm

        initial = TeacherForm(instance=self.ahmet, school=self.school).initial
        data = {k: v for k, v in initial.items() if v not in (None, "", []) and k in TeacherForm._meta.fields and k != "subjects"}
        data["duty_exempt"] = "" if not data.get("duty_exempt") else "on"
        data["availability"] = json.dumps({"0-0": "no"})
        url = reverse("timetable:data_edit", args=[self.school.pk, "ogretmenler", self.ahmet.pk])
        response = self.client.post(url, data, headers={"X-Requested-With": "fetch"})
        body = response.json()
        self.assertTrue(body["ok"], body)
        self.assertIn("Ahmet Er: Pzt 1 MAT 10-A artık kapalı saatte", body["alert"])
        self.assertIn("En az değişiklikle onar", body["alert"])
        # Aynı müsaitlik yeniden kaydedilince yeni çakışma yok
        self.assertEqual(self.client.post(url, data, headers={"X-Requested-With": "fetch"}).json()["alert"], "")

    def test_request_approval_shows_alert(self):
        req = AvailabilityRequest.objects.create(school=self.school, teacher=self.can, changes=[[0, 1, "no"]])
        response = self.client.post(reverse("timetable:teacher_requests", args=[self.school.pk]),
                                    {"action": "approve", "istek": req.pk}, follow=True)
        self.assertContains(response, "Can Ak: Pzt 2 FİZ 10-A artık kapalı saatte")

    def test_main_view_warns_about_closed_cards(self):
        page = self.client.get(reverse("timetable:timetable_detail", args=[self.tt.pk]))
        self.assertNotContains(page, "ders kapalı saatte</b>")
        self._close(self.ahmet, 0)
        page = self.client.get(reverse("timetable:timetable_detail", args=[self.tt.pk]))
        self.assertContains(page, "1 ders kapalı saatte</b>")
        self.assertContains(page, reverse("timetable:availability_repair", args=[self.tt.pk]))

    # --- onarım ------------------------------------------------------------------------------------

    def _positions(self):
        return {c.pk: (c.day, c.period) for c in self.tt.cards.all()}

    def test_repair_moves_only_affected_card(self):
        self._close(self.ahmet, 0)
        before = self._positions()
        self.assertGreater(hard(self.tt), 0)
        result = ar.run(self.tt, [self.mat.pk], self.admin, time_scale=0.3)
        after = self._positions()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["tier"], ar.TIERS[0][0])
        self.assertEqual(after[self.mat.pk], (0, 2))  # tek boş saat
        self.assertEqual({k for k in after if after[k] != before[k]}, {self.mat.pk})
        self.assertEqual(hard(self.tt), 0)
        self.assertEqual(ar.conflicts(self.tt), [])
        self.assertTrue(self.tt.versions.filter(note__startswith="Müsaitlik onarımı öncesi").exists())

    def test_repair_widens_to_neighbours_when_needed(self):
        # 10-A'nın tek boş saati FİZ'in yeri olur: Ahmet 1. ve 3. saatte gelemez → MAT 2. saate, FİZ başka saate.
        self._close(self.ahmet, 0, 2)
        before = self._positions()
        result = ar.run(self.tt, None, self.admin, time_scale=0.3)
        after = self._positions()
        moved = {k for k in after if after[k] != before[k]}
        self.assertEqual(moved, {self.mat.pk, self.fiz.pk})
        self.assertEqual(after[self.kim.pk], before[self.kim.pk])  # ilgisiz ders yerinde
        self.assertEqual(after[self.mat.pk], (0, 1))
        self.assertEqual(result["count"], 2)
        self.assertNotEqual(result["tier"], ar.TIERS[0][0])
        self.assertEqual(hard(self.tt), 0)

    def test_locked_and_nothing_to_do(self):
        with self.assertRaises(ResolveError):
            ar.repair(self.tt)
        self.mat.locked = True
        self.mat.save()
        self._close(self.ahmet, 0)
        with self.assertRaisesMessage(ResolveError, "kilitli"):
            ar.repair(self.tt)

    def test_repair_view_flow(self):
        self._close(self.ahmet, 0)
        url = reverse("timetable:availability_repair", args=[self.tt.pk])
        page = self.client.get(url)
        self.assertContains(page, "Ahmet Er: Pzt 1 MAT 10-A artık kapalı saatte")
        self.assertContains(page, "En az değişiklikle onar")
        response = self.client.post(url, {"kart": [self.mat.pk]}, follow=True)
        self.assertContains(response, "Onarım sonucu: 1 kart taşındı")
        self.assertContains(response, "Versiyon geçmişi")
        self.assertContains(response, "Pzt 3")
        self.assertContains(response, "Aktif programda kapalı saate düşen ders yok")
        # Geri al: kart eski yerine döner
        self.client.post(reverse("timetable:api_undo", args=[self.tt.pk]))
        self.mat.refresh_from_db()
        self.assertEqual((self.mat.day, self.mat.period), (0, 0))

    def test_access_entries(self):
        self.assertEqual(access.TIMETABLE_ROUTES["availability_repair"], (access.M.VIEW, access.M.PROGRAM))
        self.assertIn("availability_repair", access.ACTION_LABELS)
        self.assertIn("availability_repair", access.PLACEMENT_ONLY)
