"""Ceza dökümü: dökümün toplamı çözücünün amacına eşit olmalı; sayfa ve erişim kaydı."""

import random

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from timetable import access, penalty
from timetable.models import Card, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable
from timetable.solver import cpsat
from timetable.solver.cpsat import W_CLASS_GAP, W_CLASS_LATE_START, W_MAYBE, W_TEACHER_GAP
from timetable.solver.problem import Problem, ProblemCard, RelationshipSpec, TeacherLimits

ALL = frozenset({(0, 0)})


def card(key, teachers, atoms, days, periods, starts=None, length=1, lesson=None, maybe=()):
    if starts is None:
        starts = [(d, p) for d in range(days) for p in range(periods - length + 1)]
    return ProblemCard(key=key, lesson_id=key if lesson is None else lesson, length=length, teachers=tuple(teachers),
                       atoms=tuple(atoms), room_options=(), universes=ALL, starts=starts, maybe_slots=frozenset(maybe))


def by_kind(data):
    return {k["kind"]: k["total"] for k in data["kinds"]}


class EvaluatorMatchesSolverTests(SimpleTestCase):
    def check(self, problem, mode=cpsat.STRICT, **kwargs):
        solution = cpsat.solve(problem, time_limit=20, workers=4, mode=mode, **kwargs)
        self.assertEqual(solution.status, "optimal")
        data = penalty.breakdown(problem, solution.placements, choice=solution.teacher_choice, measure="full")
        self.assertEqual(data["mismatch"], {})
        self.assertTrue(data["exact"])
        self.assertEqual(data["total"], solution.objective)
        self.assertEqual(by_kind(data), {k: v for k, v in solution.penalties.items() if v})
        # Modelsiz (saf Python + yalnızca ilişkiler) yol da aynı toplamı vermeli
        auto = penalty.breakdown(problem, solution.placements, choice=solution.teacher_choice)
        self.assertEqual(auto["total"], solution.objective)
        return solution, data

    def test_forced_terms_are_itemised(self):
        D, P = 2, 4
        cards = [
            # Öğretmen 1 ve sınıf a: Pazartesi 1. ve 3. saat → 2. saat boşluk (öğretmen ve sınıf)
            card(0, [1], ["a|"], D, P, starts=[(0, 0)]),
            card(1, [1], ["a|"], D, P, starts=[(0, 2)]),
            # Sınıf b yalnızca Salı 2. saatte: güne geç başlama
            card(2, [2], ["b|"], D, P, starts=[(1, 1)]),
            # Koşullu hücre
            card(3, [3], ["c|"], D, P, starts=[(0, 0)], maybe={(0, 0)}),
            # Üç kart iki güne: "farklı günler" ilişkisi en az bir kez ihlal edilir
            card(4, [4], ["d|"], D, P, lesson=40),
            card(5, [4], ["d|"], D, P, lesson=40),
            card(6, [4], ["d|"], D, P, lesson=40),
        ]
        rel = RelationshipSpec("farklı gün", "different_days", 1, [[4, 5, 6]], weight=60, id=7)
        problem = Problem(days=D, periods=P, universes=ALL, cards=cards, relationships=[rel],
                          labels={"teacher": {1: "Ali Kaya"}, "class": {"a": "1A"}})
        solution, data = self.check(problem)
        kinds = by_kind(data)
        self.assertEqual(kinds["teacher_gap"], W_TEACHER_GAP)
        self.assertGreaterEqual(kinds["class_gap"], W_CLASS_GAP)
        self.assertGreaterEqual(kinds["class_late"], W_CLASS_LATE_START)
        self.assertEqual(kinds["maybe"], W_MAYBE)
        self.assertEqual(kinds["relationship"], 60)
        teacher = next(c for c in data["contributors"] if c["owner"] == "teacher" and c["owner_id"] == 1)
        detail = teacher["items"][0]["details"][0]
        self.assertEqual(detail["cells"], [(0, 1)])
        self.assertIn("2. saat boş", detail["text"])
        # 2. saat öğretmenin hiçbir dersine açık değil: boşluk müsaitlikten kaynaklanıyor
        self.assertTrue(any("müsaitlikten" in h for h in teacher["items"][0]["hints"]))
        rel_item = next(i for i in data["items"] if i["kind"] == "relationship")
        self.assertEqual((rel_item["owner_id"], rel_item["amount"], rel_item["weight"]), (7, 1, 60))
        self.assertTrue(any("kaçınılmaz" in h for h in rel_item["hints"]))

    def test_random_problems_with_relationships_and_day_weights(self):
        rng = random.Random(5)
        for seed in range(3):
            D, P = 3, 5
            cards = []
            for key in range(14):
                teacher, atom = rng.randrange(4), rng.randrange(3)
                starts = [(d, p) for d in range(D) for p in range(P) if rng.random() < 0.7]
                cards.append(card(key, [teacher], [f"{atom}|"], D, P, starts=starts or [(0, 0)], lesson=key // 2,
                                  maybe={(rng.randrange(D), rng.randrange(P))}))
            rels = [
                RelationshipSpec("aynı gün en fazla 1", "max_per_day", 1, [[0, 1, 2, 3]], weight=30, id=1),
                RelationshipSpec("aralık", "day_span_max", 2, [[4, 5, 6]], weight=20, id=2),
                RelationshipSpec("aynı anda", "same_time", 0, [[7], [8]], weight=15, id=3),
            ]
            problem = Problem(days=D, periods=P, universes=ALL, cards=cards, relationships=rels,
                              teacher_weights={0: (12, 7)}, teacher_limits={1: TeacherLimits(max_days_per_week=2)})
            with self.subTest(seed=seed):
                solution, _ = self.check(problem)
                self.assertTrue(solution.objective)

    def test_relaxed_mode_counts_broken_hard_rules(self):
        D, P = 1, 3
        cards = [card(k, [1], [f"{k}|"], D, P) for k in range(3)]
        problem = Problem(days=D, periods=P, universes=ALL, cards=cards,
                          teacher_limits={1: TeacherLimits(max_periods_per_day=2)})
        solution, data = self.check(problem, mode=cpsat.RELAXED, place_all=True)
        relaxed = next(i for i in data["items"] if i["kind"] == "relaxed")
        self.assertEqual((relaxed["owner"], relaxed["owner_id"], relaxed["amount"]), ("teacher", 1, 1))

    def test_hand_edited_clash_is_still_measured(self):
        # Çakışma (elle düzenlenmiş program) ceza modelini imkânsız yapmamalı
        D, P = 1, 3
        cards = [card(0, [1], ["a|"], D, P), card(1, [1], ["b|"], D, P), card(2, [2], ["a|"], D, P)]
        rel = RelationshipSpec("aynı anda değil", "not_simultaneous", 0, [[0, 2]], weight=40, id=1)
        problem = Problem(days=D, periods=P, universes=ALL, cards=cards, relationships=[rel])
        placements = {k: cpsat.Placement(0, 0, None) for k in range(3)}
        data = penalty.breakdown(problem, placements, measure="full")
        self.assertEqual(data["model"]["status"], "optimal")
        self.assertEqual(by_kind(data).get("relationship"), 40)


class BreakdownPageTests(TestCase):
    def setUp(self):
        school = School.objects.create(name="Okul", days_per_week=2)
        for i in range(4):
            Period.objects.create(school=school, index=i, name=str(i + 1))
        teacher = Teacher.objects.create(school=school, first_name="Ali", last_name="Kaya")
        cls = SchoolClass.objects.create(school=school, name="1A")
        self.timetable = Timetable.objects.create(school=school, name="t", status=Timetable.OK, objective=999)
        for name, period in (("Mat", 0), ("Fiz", 3)):  # Pazartesi 1. ve 4. saat: 2 saat boşluk (öğretmen ve sınıf)
            subject = Subject.objects.create(school=school, name=name, short=name.upper())
            lesson = Lesson.objects.create(school=school, subject=subject, periods_per_week=1, card_length=1)
            lesson.teachers.add(teacher)
            lesson.classes.add(cls)
            Card.objects.create(timetable=self.timetable, lesson=lesson, length=1, day=0, period=period)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def test_page_renders_items_and_links(self):
        url = reverse("timetable:penalty_breakdown", args=[self.timetable.pk])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        expected = 2 * W_TEACHER_GAP + 2 * W_CLASS_GAP
        self.assertEqual(page.context["data"]["total"], expected)
        self.assertContains(page, "Ceza dökümü")
        self.assertContains(page, "Ali Kaya")
        self.assertContains(page, "Pazartesi: 2.–3. saat boş")
        self.assertContains(page, "Ne yapılabilir?")
        self.assertContains(page, "kayarsa bu günün boşluğu 2 → 0 olur")  # tek kart kaydırma ipucu
        self.assertContains(page, "?tur=ogretmen&amp;ara=Ali%20Kaya")
        self.assertTrue(page.context["differs"])  # bildirilen 999, döküm farklı
        center = self.client.get(reverse("timetable:solution_center", args=[self.timetable.pk]))
        self.assertContains(center, url)

    def test_access_entry(self):
        self.assertIn("penalty_breakdown", access.TIMETABLE_ROUTES)
        self.assertIn("penalty_breakdown", access.ACTION_LABELS)
