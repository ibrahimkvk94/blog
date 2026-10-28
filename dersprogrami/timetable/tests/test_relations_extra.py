"""Gelişmiş kart ilişkileri: çözücü kısıtı ile doğrulayıcı aynı şeyi mi söylüyor?

Küçük rastgele problemlerde tüm yerleşimler tek tek denenir: kural ancak doğrulayıcının ihlalsiz
bulduğu en az bir yerleşim varsa çözülebilir olmalı; çözücünün bulduğu yerleşim de ihlalsiz olmalı.
"""

import itertools
import random

from django.test import SimpleTestCase

from timetable.solver import cpsat, relations_extra
from timetable.solver.cpsat import Placement
from timetable.solver.problem import Problem, ProblemCard, RelationshipSpec

ALL = frozenset({(0, 0)})


def problem(n_cards, days, periods, rng, lengths=(1,), rooms=False, subjects=2, teachers=3):
    cards = []
    for k in range(n_cards):
        length = rng.choice(lengths)
        starts = [(d, p) for d in range(days) for p in range(periods - length + 1)]
        starts = rng.sample(starts, max(1, len(starts) * 2 // 3))
        cards.append(ProblemCard(
            key=k, lesson_id=k, length=length, teachers=(rng.randrange(teachers),), atoms=(f"a{k}",),
            room_options=(2 * k, 2 * k + 1) if rooms else (), universes=ALL, starts=sorted(starts),
            subject=rng.randrange(subjects),
        ))
    building = {r: rng.randrange(3) for k in range(n_cards) for r in (2 * k, 2 * k + 1)} if rooms else {}
    # Öğretmen çakışması doğrulanmasın diye her kartın öğretmeni ayrı kaynak sayılmaz: atomlar ayrı,
    # öğretmenler yalnızca "farklı öğretmen" sayımında kullanılır; aynı öğretmenli kartlar çakışamaz.
    return Problem(days=days, periods=periods, universes=ALL, cards=cards, room_building=building)


def placements_of(prob):
    options = []
    for c in prob.cards:
        rooms = c.room_options or (None,)
        options.append([Placement(d, p, r) for (d, p) in c.starts for r in rooms])
    for combo in itertools.product(*options):
        yield dict(enumerate(combo))


def no_conflicts(prob, pl):
    """Aynı öğretmenin kartları çakışmasın (çözücünün kaynak kuralı)."""
    seen = set()
    for k, place in pl.items():
        for cell in prob.cards[k].cells(place.day, place.period):
            key = (prob.cards[k].teachers[0], cell)
            if key in seen:
                return False
            seen.add(key)
    return True


def brute_feasible(prob, rel):
    for pl in placements_of(prob):
        if not no_conflicts(prob, pl):
            continue
        broken = []
        for g, keys in enumerate(rel.groups):
            relations_extra.check(prob, pl, rel, keys, rel.groups_b[g] if rel.groups_b else [], broken.append)
        if not broken:
            return True
    return False


CASES = [
    # (koşul, N, iki taraflı, derslik, harita, kart uzunlukları)
    ("day_span_max", 3, False, False, False, (1,)),
    ("day_span_min", 3, False, False, False, (1,)),
    ("min_per_day", 1, False, False, False, (1,)),
    ("min_gap_length", 2, False, False, False, (1,)),
    ("min_distance", 1, False, False, False, (1, 2)),
    ("gaps_from_start", 1, False, False, False, (1,)),
    ("gaps_to_end", 1, False, False, False, (1,)),
    ("max_gaps_week", 1, False, False, False, (1,)),
    ("gaps_week_from_start", 1, False, False, False, (1,)),
    ("gaps_week_to_end", 2, False, False, False, (1,)),
    ("max_consec_days", 1, False, False, False, (1,)),
    ("max_free_days", 0, False, False, False, (1,)),
    ("ab_after", 1, True, False, False, (1,)),
    ("ab_before", 1, True, False, False, (1,)),
    ("ab_not_mixed", 1, True, False, False, (1,)),
    ("ab_week_before", 1, True, False, False, (1,)),
    ("ab_day_before", 1, True, False, False, (1,)),
    ("ab_max_consecutive", 2, True, False, False, (1, 2)),
    ("ab_fill_gaps", 1, True, False, False, (1,)),
    ("ab_a_first", 1, True, False, False, (1,)),
    ("ab_b_after", 1, True, False, False, (1,)),
    ("ab_not_followed", 1, True, False, False, (1,)),
    ("only_in_map", 1, False, False, True, (1, 2)),
    ("no_start_at", 1, False, False, True, (1, 2)),
    ("no_end_at", 1, False, False, True, (1, 2)),
    ("first_or_last", 1, False, False, False, (1, 2)),
    ("reserve", 1, True, False, True, (1,)),
    ("max_subjects_week", 1, False, False, True, (1,)),
    ("max_subjects_day", 1, False, False, False, (1,)),
    ("max_teachers_day", 1, False, False, False, (1,)),
    ("max_rooms_day", 1, False, True, False, (1,)),
    ("max_room_changes", 0, False, True, False, (1,)),
    ("max_building_changes", 0, False, True, False, (1,)),
    ("max_buildings_week", 1, False, True, False, (1,)),
    ("max_rooms_position", 1, False, True, False, (1,)),
]


class AdvancedRelationshipTests(SimpleTestCase):
    def test_every_condition_is_covered(self):
        self.assertEqual({c[0] for c in CASES}, relations_extra.ALL)

    def test_solver_matches_brute_force(self):
        for cond, n, two_sided, rooms, with_map, lengths in CASES:
            for seed in range(6):
                rng = random.Random(f"{cond}-{seed}")
                days, periods = (3, 3) if cond in ("max_consec_days", "max_free_days", "ab_day_before") else (2, 4)
                prob = problem(4 if two_sided else 3, days, periods, rng, lengths=lengths, rooms=rooms)
                keys = [0, 1] if two_sided else [0, 1, 2]
                cells = frozenset(rng.sample([(d, p) for d in range(days) for p in range(periods)], 3)) if with_map else None
                spec = RelationshipSpec(cond, cond, n, [keys], None, cells, groups_b=[[2, 3]] if two_sided else [])
                prob.relationships = [spec]
                with self.subTest(cond=cond, seed=seed):
                    expected = brute_feasible(prob, spec)
                    solution = cpsat.solve(prob, time_limit=10, workers=1)
                    self.assertEqual(solution.ok, expected, f"{cond} seed={seed}: çözücü {solution.status}, deneme {expected}")
                    if solution.ok:
                        broken = []
                        relations_extra.check(prob, solution.placements, spec, keys, [2, 3] if two_sided else [], broken.append)
                        self.assertEqual(broken, [])

    def test_soft_rule_is_penalised_not_forbidden(self):
        rng = random.Random("soft")
        prob = problem(3, 1, 3, rng)
        for c in prob.cards:
            c.starts = [(0, 0), (0, 1), (0, 2)]
            c.teachers = (0,)  # aynı öğretmen: üç kart üç ayrı saate düşer, aralık 3 olur
        prob.relationships = [RelationshipSpec("aralık", "day_span_max", 2, [[0, 1, 2]], weight=60)]
        solution = cpsat.solve(prob, time_limit=10, workers=1)
        self.assertTrue(solution.ok)
        self.assertGreaterEqual(solution.penalties.get("relationship", 0), 60)


class ReserveFromDatabaseTests(SimpleTestCase):
    databases = {"default"}

    def test_reserve_keeps_marked_cells_for_selected_lessons(self):
        from timetable.models import CardRelationship, Lesson, Period, School, SchoolClass, Subject, Teacher
        from timetable.solver.builder import build_problem
        from timetable.solver.validate import validate

        school = School.objects.create(name="R", days_per_week=1)
        for i in range(4):
            Period.objects.create(school=school, index=i, name=str(i + 1))
        cls = SchoolClass.objects.create(school=school, name="9A")
        lessons = []
        for name in ("Lab", "Mat", "Fiz"):
            subject = Subject.objects.create(school=school, name=name)
            lesson = Lesson.objects.create(school=school, subject=subject)
            lesson.classes.set([cls])
            lesson.teachers.set([Teacher.objects.create(school=school, first_name=name, last_name="H")])
            lessons.append(lesson)
        rel = CardRelationship.objects.create(school=school, name="lab saati", condition="reserve", time_map=["0-0", "0-1"])
        rel.lessons.set([lessons[0]])
        problem = build_problem(school)
        solution = cpsat.solve(problem, time_limit=10, workers=1)
        self.assertTrue(solution.ok)
        by_lesson = {problem.cards[k].lesson_id: p for k, p in solution.placements.items()}
        # 1–2. saatler Lab'a ayrıldı: Mat ve Fiz 3–4. saatlere düşer
        self.assertEqual({by_lesson[lessons[1].id].period, by_lesson[lessons[2].id].period}, {2, 3})
        self.assertEqual(validate(problem, solution.placements)[0], [])
        school.delete()
