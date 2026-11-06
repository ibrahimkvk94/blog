"""Kart ilişkisinin kapsamı: seçilen ders kendi ders adını temsil eder; sınıf / öğretmen süzgeci yoksa kural o
dersin okutulduğu bütün kısımlara uygulanır."""

from django.test import TestCase

from timetable.models import CardRelationship, Lesson, Period, School, SchoolClass, Subject, Teacher
from timetable.solver import cpsat
from timetable.solver.builder import build_problem
from timetable.solver.validate import validate

R = CardRelationship


class RelationScopeTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=2)
        for i in range(6):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.tbe = Subject.objects.create(school=self.school, name="Temel Beden", short="TBE201")
        self.sbe = Subject.objects.create(school=self.school, name="Savaş Beden", short="SBE201")
        self.classes, self.lessons = [], {}
        for n in range(3):
            cls = SchoolClass.objects.create(school=self.school, name=f"{n + 1}SVN")
            self.classes.append(cls)
            for subject, length in ((self.tbe, 2), (self.sbe, 1)):
                lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=length, card_length=length)
                lesson.classes.set([cls])
                lesson.teachers.set([Teacher.objects.create(school=self.school, first_name=f"{subject.short}{n}", last_name="H")])
                self.lessons[(subject.short, n)] = lesson

    def rel(self, lessons, classes=(), condition=R.CONSECUTIVE_ORDERED, name="TBE → SBE"):
        rel = R.objects.create(school=self.school, name=name, condition=condition)
        rel.lessons.set(lessons)
        rel.classes.set(classes)
        return rel

    def specs(self):
        return [s for s in build_problem(self.school).relationships]

    def test_one_section_rule_applies_to_every_section(self):
        self.rel([self.lessons[("TBE201", 0)], self.lessons[("SBE201", 0)]])
        problem = build_problem(self.school)
        self.assertEqual(len(problem.relationships), 3)  # her kısım için ayrı eşleştirme
        lesson_of = {c.key: c.lesson_id for c in problem.cards}
        for spec in problem.relationships:
            first, second = spec.groups
            a, b = lesson_of[first[0]], lesson_of[second[0]]
            self.assertEqual(Lesson.objects.get(pk=a).subject, self.tbe)  # önce TBE201
            self.assertEqual(Lesson.objects.get(pk=b).subject, self.sbe)
            self.assertEqual(set(Lesson.objects.get(pk=a).classes.all()), set(Lesson.objects.get(pk=b).classes.all()))
        solution = cpsat.solve(problem, time_limit=10, workers=1)
        self.assertTrue(solution.ok)
        self.assertEqual(validate(problem, solution.placements)[0], [])
        for key_a, key_b in ((s.groups[0][0], s.groups[1][0]) for s in problem.relationships):
            pa, pb = solution.placements[key_a], solution.placements[key_b]
            self.assertEqual((pa.day, pa.period + 2), (pb.day, pb.period))

    def test_class_filter_limits_sections(self):
        self.rel([self.lessons[("TBE201", 0)], self.lessons[("SBE201", 0)]], classes=[self.classes[1]])
        specs = self.specs()
        self.assertEqual(len(specs), 1)
        self.assertIn("2SVN", Lesson.objects.get(pk=build_problem(self.school).cards[specs[0].groups[0][0]].lesson_id).classes.get().name)

    def test_section_copies_collapse_into_one(self):
        for n in range(3):  # aSc'den kısım kısım gelmiş kopyalar
            self.rel([self.lessons[("TBE201", n)], self.lessons[("SBE201", n)]], name=f"aSc 59 ({n + 1}SVN)")
        self.assertEqual(len(self.specs()), 3)

    def test_cross_class_same_time_stays_explicit(self):
        self.rel([self.lessons[("TBE201", 0)], self.lessons[("SBE201", 1)]], condition=R.SAME_TIME, name="iki sınıf aynı anda")
        specs = self.specs()
        self.assertEqual(len(specs), 1)
        self.assertEqual([len(g) for g in specs[0].groups], [1, 1])

    def test_subject_selection_is_enough_for_paired(self):
        rel = R.objects.create(school=self.school, name="adla", condition=R.CONSECUTIVE_ORDERED)
        rel.subjects.set([self.tbe, self.sbe])
        self.assertEqual(len(self.specs()), 3)

    def test_non_paired_rule_reaches_all_sections(self):
        rel = R.objects.create(school=self.school, name="günde 1", condition=R.MAX_PER_DAY, param=1, apply_to=R.EACH_CLASS)
        rel.lessons.set([self.lessons[("SBE201", 0)]])
        spec = self.specs()[0]
        self.assertEqual(len(spec.groups), 3)
