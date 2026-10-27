"""Program üzerinde çalışma: geri al / yinele, toplu işlemler, karşılaştırma ve istatistikler."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import analysis, editing
from timetable.models import Card, Classroom, Lesson, Period, School, SchoolClass, Subject, Teacher
from timetable.services import generate_timetable


def build_school():
    school = School.objects.create(name="İşlem okulu", days_per_week=5)
    for i in range(6):
        Period.objects.create(school=school, index=i, name=f"{i + 1}. saat")
    teachers = [Teacher.objects.create(school=school, first_name=f"Öğretmen{i}", last_name="Test") for i in range(3)]
    for i, name in enumerate(["9-A", "9-B"]):
        room = Classroom.objects.create(school=school, name=f"Derslik {name}")
        cls = SchoolClass.objects.create(school=school, name=name, home_classroom=room)
        for j, (subject_name, hours, length) in enumerate([("Matematik", 4, 2), ("Türkçe", 4, 1), ("Fizik", 2, 1)]):
            subject, _ = Subject.objects.get_or_create(school=school, name=subject_name)
            lesson = Lesson.objects.create(school=school, subject=subject, periods_per_week=hours, card_length=length)
            lesson.classes.set([cls])
            lesson.teachers.set([teachers[(i + j) % 3]])
    return school


class OperationTests(TestCase):
    def setUp(self):
        self.school = build_school()
        self.timetable = generate_timetable(self.school, "ilk", time_limit=10)
        self.assertTrue(self.timetable.has_grid)

    def positions(self, timetable=None):
        tt = timetable or self.timetable
        return {c.id: (c.day, c.period, c.classroom_id, c.locked) for c in tt.cards.all()}

    def test_undo_redo_move(self):
        before = self.positions()
        card = self.timetable.cards.filter(length=1).first()
        board = editing.Board(self.timetable)
        target = next(o for o in board.options(card.id) if o["status"] in ("free", "warn", "conflict") and (o["day"], o["period"]) != (card.day, card.period))
        self.assertTrue(editing.move_card(card, target["day"], target["period"])["ok"])
        moved = self.positions()
        self.assertNotEqual(moved, before)
        self.timetable.refresh_from_db()
        self.assertIn("taşındı", editing.history_info(self.timetable)["undo"])

        self.assertTrue(editing.undo(self.timetable)["ok"])
        self.assertEqual(self.positions(), before)
        self.timetable.refresh_from_db()
        self.assertIsNone(editing.history_info(self.timetable)["undo"])
        self.assertTrue(editing.redo(self.timetable)["ok"])
        self.assertEqual(self.positions(), moved)
        self.timetable.refresh_from_db()
        self.assertFalse(editing.redo(self.timetable)["ok"])

    def test_swap_days_and_undo(self):
        before = self.positions()
        monday = {cid for cid, (d, *_rest) in before.items() if d == 0}
        tuesday = {cid for cid, (d, *_rest) in before.items() if d == 1}
        result = editing.bulk_action(self.timetable, "swap_days", 0, 1)
        self.assertTrue(result["ok"], result)
        after = self.positions()
        self.assertEqual({cid for cid, (d, *_rest) in after.items() if d == 1}, monday)
        self.assertEqual({cid for cid, (d, *_rest) in after.items() if d == 0}, tuesday)
        self.timetable.refresh_from_db()
        editing.undo(self.timetable)
        self.assertEqual(self.positions(), before)

    def test_swap_periods_keeps_blocks(self):
        before = self.positions()
        result = editing.bulk_action(self.timetable, "swap_periods", 0, 5)
        self.assertTrue(result["ok"])
        for card in self.timetable.cards.all():
            day, period, *_ = before[card.id]
            if card.length > 1 or period not in (0, 5):
                self.assertEqual(card.period, period)
            else:
                self.assertEqual(card.period, 5 if period == 0 else 0)
        self.assertFalse(editing.bulk_action(self.timetable, "swap_periods", 2, 2)["ok"])

    def test_lock_and_unplace(self):
        editing.bulk_action(self.timetable, "lock_all")
        self.assertFalse(self.timetable.cards.filter(locked=False, day__isnull=False).exists())
        first = self.timetable.cards.first()
        first.locked = False
        first.save()
        result = editing.bulk_action(self.timetable, "unplace_unlocked")
        self.assertTrue(result["ok"])
        self.assertEqual(list(self.timetable.cards.filter(day__isnull=True)), [first])
        self.timetable.refresh_from_db()
        editing.undo(self.timetable)
        self.assertFalse(self.timetable.cards.filter(day__isnull=True).exists())

    def test_compare_versions(self):
        other = generate_timetable(self.school, "ikinci", time_limit=10)
        same = analysis.compare(self.timetable, self.timetable)
        self.assertEqual(same["changed"], [])
        editing.bulk_action(other, "swap_days", 0, 1)
        result = analysis.compare(other, self.timetable)
        self.assertTrue(result["changed"])
        moved = {c.id for c in other.cards.filter(day__in=[0, 1])}
        self.assertTrue(set(result["changed"]) <= {c.id for c in other.cards.all()})
        self.assertTrue(set(result["changed"]) & moved)

    def test_statistics(self):
        stats = analysis.statistics(self.timetable)
        self.assertEqual(stats["totals"]["unplaced"], 0)
        self.assertEqual(sum(r["hours"] for r in stats["classes"]), 20)
        self.assertEqual(sum(r["hours"] for r in stats["teachers"]), 20)
        self.assertEqual(sum(r["hours"] for r in stats["rooms"]), 20)
        for row in stats["teachers"]:
            self.assertEqual(sum(row["per_day"]), row["hours"])


class OperationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = build_school()
        cls.timetable = generate_timetable(cls.school, "ilk", time_limit=10)
        cls.other = generate_timetable(cls.school, "ikinci", time_limit=10)
        cls.user = User.objects.create_user("islem", password="parola-123456")

    def setUp(self):
        self.client.force_login(self.user)

    def post(self, name, body=None):
        return self.client.post(reverse(f"timetable:{name}", args=[self.timetable.pk]), json.dumps(body or {}), content_type="application/json")

    def test_pages_and_apis(self):
        page = self.client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk]))
        self.assertContains(page, "Geri al")
        self.assertContains(page, "Karşılaştır")
        self.assertContains(self.client.get(reverse("timetable:statistics", args=[self.timetable.pk])), "Derslikler")

        self.assertEqual(self.post("api_undo").status_code, 400)
        response = self.post("api_bulk", {"action": "swap_days", "a": 0, "b": 4})
        self.assertEqual(response.status_code, 200, response.content)
        grid = self.client.get(reverse("timetable:api_grid", args=[self.timetable.pk]) + f"?karsilastir={self.other.pk}").json()
        self.assertIn("Cuma", grid["history"]["undo"])
        self.assertIn("compare", grid)
        self.assertEqual(self.post("api_undo").status_code, 200)
        self.assertEqual(self.post("api_redo").status_code, 200)
        self.assertEqual(self.post("api_bulk", {"action": "nope"}).status_code, 400)

        card = Card.objects.filter(timetable=self.timetable).first()
        self.client.post(reverse("timetable:api_card_lock", args=[card.pk]))
        grid = self.client.get(reverse("timetable:api_grid", args=[self.timetable.pk])).json()
        self.assertIn("kilit", grid["history"]["undo"])
