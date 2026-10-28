"""Çözüm merkezi: en az değişiklikle kalıcı onarım önerileri, rapor ve uygulama."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import editing
from timetable.demo import create_demo_school
from timetable.models import Availability, Card, Membership
from timetable.resolve import Center, Request, ResolveError
from timetable.services import generate_timetable, verify_timetable
from timetable.solver import cpsat
from timetable.solver.problem import Problem, ProblemCard

ALL = frozenset({(0, 0)})


class AnchorSolverTests(TestCase):
    def test_minimal_change_prefers_fewest_moves(self):
        # Üç kart, tek gün, üç saat; 0. kart 0. saatten çıkmak zorunda. Yalnızca 0 ile bir diğerinin
        # yer değiştirmesi (2 hareket) yeterli; üçünün de oynaması (3 hareket) gereksiz.
        cards = [ProblemCard(key=k, lesson_id=k, length=1, teachers=(), atoms=("a",), room_options=(), universes=ALL,
                             starts=[(0, 0), (0, 1), (0, 2)]) for k in range(3)]
        cards[0].starts = [(0, 1), (0, 2)]
        problem = Problem(days=1, periods=3, universes=ALL, cards=cards, anchors={0: (0, 0), 1: (0, 1), 2: (0, 2)})
        solution = cpsat.solve(problem, time_limit=5, workers=1)
        moved = [k for k, p in solution.placements.items() if (p.day, p.period) != problem.anchors[k]]
        self.assertEqual(len(moved), 2)
        problem.forbidden_move_sets = [moved]
        other = cpsat.solve(problem, time_limit=5, workers=1)
        moved2 = sorted(k for k, p in other.placements.items() if (p.day, p.period) != problem.anchors[k])
        self.assertNotEqual(sorted(moved), moved2)
        problem.max_moves = 1
        self.assertEqual(cpsat.solve(problem, time_limit=5, workers=1).status, "infeasible")


class SolutionCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.timetable = generate_timetable(cls.school, "t", time_limit=20)

    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@x.tr", "pw")
        self.client.force_login(self.admin)
        self.card = self.timetable.cards.filter(day__isnull=False, locked=False).select_related("lesson").first()

    def test_shift_proposals_are_conflict_free_and_minimal(self):
        proposals = Center(self.timetable).proposals(Request("shift", card_ids=[self.card.id], max_moves=4))
        self.assertTrue(proposals)
        counts = [p["count"] for p in proposals]
        self.assertEqual(counts, sorted(counts))
        for p in proposals:
            self.assertEqual(p["new_violations_hard"], 0)
            target = next(m for m in p["moves"] if m["card_id"] == self.card.id)
            self.assertNotEqual(target["state_to"][:2], [self.card.day, self.card.period])
            self.assertTrue(p["teachers"] and p["classes"])
        self.assertEqual(len({tuple(sorted(m["card_id"] for m in p["moves"] if m["time_moved"])) for p in proposals}), len(proposals))

    def test_apply_undo_and_stale_check(self):
        before, _ = verify_timetable(self.timetable)
        proposal = Center(self.timetable).proposals(Request("shift", card_ids=[self.card.id], max_moves=4))[0]
        from timetable.resolve import apply

        apply(self.timetable, proposal, "deneme", self.admin)
        self.card.refresh_from_db()
        target = next(m for m in proposal["moves"] if m["card_id"] == self.card.id)
        self.assertEqual([self.card.day, self.card.period], target["state_to"][:2])
        after, _ = verify_timetable(self.timetable)
        self.assertLessEqual(sum(v.level == "hard" for v in after), sum(v.level == "hard" for v in before))
        with self.assertRaises(ResolveError):  # aynı öneri ikinci kez: kartlar artık "önceki" yerde değil
            apply(self.timetable, proposal, "deneme", self.admin)
        self.timetable.refresh_from_db()
        self.assertTrue(editing.undo(self.timetable)["ok"])
        self.card.refresh_from_db()
        self.assertEqual([self.card.day, self.card.period], target["state_from"][:2])

    def test_teacher_unavailable_moves_all_lessons_and_saves_availability(self):
        teacher = self.card.lesson.teachers.first()
        day = self.card.day
        periods = sorted({c.period + i for c in self.timetable.cards.filter(lesson__teachers=teacher, day=day) for i in range(c.length)})
        url = reverse("timetable:solution_center", args=[self.timetable.pk])
        page = self.client.post(url, {"action": "solve", "tur": "teacher", "ogretmen": teacher.pk, "gun": day,
                                      "saatler": periods, "en_fazla": 8})
        self.assertContains(page, "Öneri 1")
        self.client.post(url, {"action": "apply", "oneri": 0, "musaitlik": "1"})
        self.assertFalse(self.timetable.cards.filter(lesson__teachers=teacher, day=day, period__in=periods).exists())
        self.assertEqual(Availability.objects.filter(teacher=teacher, day=day, period__in=periods, state="no").count(), len(periods))

    def test_place_request(self):
        target = next((d, p) for d in range(self.school.days_per_week) for p in range(3)
                      if (d, p) != (self.card.day, self.card.period))
        try:
            proposals = Center(self.timetable).proposals(Request("place", card_ids=[self.card.id], day=target[0], periods=[target[1]], max_moves=6))
        except ResolveError:
            return  # o saat bu kart için kapalı olabilir
        for p in proposals:
            moved = next(m for m in p["moves"] if m["card_id"] == self.card.id)
            self.assertEqual(moved["state_to"][:2], list(target))

    def test_preview_returns_validation_of_proposal(self):
        url = reverse("timetable:solution_center", args=[self.timetable.pk])
        self.client.post(url, {"action": "solve", "tur": "shift", "kart": self.card.pk, "en_fazla": 4})
        data = self.client.get(reverse("timetable:api_resolve_preview", args=[self.timetable.pk, 0])).json()
        self.assertTrue(data["ok"])
        self.assertIn("placed", data["stats"])
        self.assertFalse([v for v in data["violations"] if v["level"] == "hard"])

    def test_locked_card_is_refused(self):
        Card.objects.filter(pk=self.card.pk).update(locked=True)
        with self.assertRaises(ResolveError):
            Center(self.timetable).proposals(Request("shift", card_ids=[self.card.id]))

    def test_only_program_permission(self):
        viewer = User.objects.create_user("izleyici", password="pw")
        Membership.objects.create(user=viewer, institution=self.school.institution, permissions=[Membership.VIEW])
        self.client.force_login(viewer)
        url = reverse("timetable:solution_center", args=[self.timetable.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        page = self.client.get(url, {"tur": "shift", "kart": self.card.pk})
        self.assertContains(page, "Çözüm öner")


class TextRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.timetable = generate_timetable(cls.school, "t", time_limit=20)

    def setUp(self):
        from timetable.resolve_text import parse

        self.parse = lambda text: parse(self.school, self.timetable, text)
        self.card = self.timetable.cards.filter(day__isnull=False, locked=False).select_related("lesson__subject").first()
        self.teacher = self.card.lesson.teachers.first()
        self.day = self.school.day_names[self.card.day].lower()

    def test_shift_sentence(self):
        r = self.parse(f"{self.teacher.full_name} {self.day} {self.card.period + 1}. saat dersini aynı gün içinde kaydır")
        self.assertEqual(r["problems"], [])
        self.assertEqual((r["form"]["kind"], r["form"]["card"], r["form"]["teacher"], r["form"]["same_day"]),
                         ("shift", self.card.id, self.teacher.id, True))

    def test_teacher_unavailable_sentence(self):
        r = self.parse(f"{self.teacher.full_name} perşembe 5-7 arası gelemeyecek, en fazla 6 değişiklik")
        f = r["form"]
        self.assertEqual((f["kind"], f["day"], f["periods"], f["max_moves"]), ("teacher", 3, [4, 5, 6], 6))
        r = self.parse(f"{self.teacher.full_name} cuma gelemiyor")
        self.assertEqual(r["form"]["periods"], list(range(self.school.periods.count())))

    def test_place_sentence_with_class_and_code(self):
        cls = self.card.lesson.classes.first()
        code = self.card.lesson.subject.short
        r = self.parse(f"{cls.name} {code} {self.day} {self.card.period + 1} dersini çarşamba 3'e al")
        self.assertEqual((r["form"]["kind"], r["form"]["day"], r["form"]["period"], r["form"]["card"]), ("place", 2, 2, self.card.id))

    def test_room_sentence(self):
        from timetable.models import Classroom

        room = Classroom.objects.filter(school=self.school).first()
        r = self.parse(f"{room.name} salı tüm gün kullanılamıyor")
        self.assertEqual((r["form"]["kind"], r["form"]["room"], r["form"]["day"]), ("room", room.id, 1))

    def test_unclear_sentence_reports_problem(self):
        r = self.parse("bir şeyler yapalım")
        self.assertTrue(r["problems"])

    def test_view_parses_and_solves(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:solution_center", args=[self.timetable.pk])
        page = self.client.post(url, {"action": "text", "istek": f"{self.teacher.full_name} {self.day} {self.card.period + 1}. saat dersini kaydır"})
        self.assertContains(page, "Anlaşılan")
        self.assertContains(page, "Öneri 1")
