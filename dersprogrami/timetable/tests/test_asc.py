"""aSc kılavuzundan eklenen kuralların veritabanı → problem dönüşümü ve form testleri."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.demo import create_demo_school
from timetable.models import CardRelationship, Classroom, Lesson, Subject
from timetable.solver.builder import build_problem


class AscBuilderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()

    def subject(self, short):
        return Subject.objects.get(school=self.school, short=short)

    def rel(self, condition, **kwargs):
        m2m = {k: kwargs.pop(k) for k in list(kwargs) if k in ("subjects", "lessons", "subjects_b", "lessons_b", "classes", "classrooms")}
        rel = CardRelationship.objects.create(school=self.school, name="test", condition=condition, **kwargs)
        for name, values in m2m.items():
            getattr(rel, name).set(values)
        return rel

    def spec(self, rel):
        return next(s for s in build_problem(self.school).relationships if s.id == rel.id)

    def test_long_break_blocks_doubles(self):
        period = self.school.periods.get(index=3)
        period.long_break_after = True
        period.save()
        problem = build_problem(self.school)
        doubles = [c for c in problem.cards if c.length == 2]
        self.assertTrue(doubles)
        for card in doubles:
            self.assertNotIn(3, {p for _, p in card.starts})
        singles = [c for c in problem.cards if c.length == 1 and not c.fixed]
        self.assertTrue(any(p == 3 for c in singles for _, p in c.starts))

    def test_room_capacity_filters_rooms(self):
        cls = self.school.classes.get(name="9-A")
        cls.student_count = 30
        cls.save()
        Classroom.objects.filter(school=self.school, name="Fen Lab 1").update(capacity=20)
        problem = build_problem(self.school)
        lab1 = Classroom.objects.get(school=self.school, name="Fen Lab 1").id
        chemistry = Lesson.objects.get(school=self.school, subject__short="KİM", classes=cls)
        card = next(c for c in problem.cards if c.lesson_id == chemistry.id)
        self.assertNotIn(lab1, card.room_options)
        self.assertTrue(card.room_options)
        # Fizik yalnızca Fen Lab 1'de: sığacak derslik kalmaz ve not düşülür.
        self.assertTrue(any(n[1] == "room_capacity" for n in problem.notes))

    def test_apply_to_variants(self):
        sub = [self.subject("MAT")]
        by_class = self.spec(self.rel(CardRelationship.MAX_PER_DAY, apply_to=CardRelationship.EACH_CLASS, subjects=sub))
        by_grade = self.spec(self.rel(CardRelationship.MAX_PER_DAY, apply_to=CardRelationship.EACH_GRADE, subjects=sub))
        by_subject_class = self.spec(self.rel(CardRelationship.MAX_PER_DAY, apply_to=CardRelationship.EACH_SUBJECT_CLASS, subjects=sub))
        overall = self.spec(self.rel(CardRelationship.MAX_PER_DAY, apply_to=CardRelationship.ALL, subjects=sub))
        self.assertEqual(len(by_class.groups), 4)
        self.assertEqual(len(by_grade.groups), 2)
        self.assertEqual(len(by_subject_class.groups), 4)
        self.assertEqual(len(overall.groups), 1)
        self.assertEqual(sum(len(g) for g in by_class.groups), len(overall.groups[0]))

    def test_card_length_filter(self):
        rel = self.rel(CardRelationship.MAX_PER_DAY, apply_to=CardRelationship.ALL, card_length=2)
        problem = build_problem(self.school)
        spec = next(s for s in problem.relationships if s.id == rel.id)
        lengths = {c.key: c.length for c in problem.cards}
        self.assertTrue(spec.groups[0])
        self.assertEqual({lengths[k] for k in spec.groups[0]}, {2})

    def test_two_sided_groups_match_owners(self):
        rel = self.rel(
            CardRelationship.AB_NOT_SAME_DAY, apply_to=CardRelationship.EACH_CLASS,
            subjects=[self.subject("KİM")], subjects_b=[self.subject("BİY")], time_map=["0-0", "1-1"],
        )
        problem = build_problem(self.school)
        spec = next(s for s in problem.relationships if s.id == rel.id)
        lessons = {c.key: c.lesson_id for c in problem.cards}
        self.assertEqual(len(spec.groups), len(spec.groups_b))
        for a, b in zip(spec.groups, spec.groups_b):
            classes_a = {tuple(Lesson.objects.get(pk=lessons[k]).classes.values_list("id", flat=True)) for k in a}
            classes_b = {tuple(Lesson.objects.get(pk=lessons[k]).classes.values_list("id", flat=True)) for k in b}
            self.assertEqual(classes_a, classes_b)
        self.assertEqual(spec.cells, {(0, 0), (1, 1)})


class RelationshipFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.user = User.objects.create_superuser("iliski", password="parola-123456")

    def setUp(self):
        self.client.force_login(self.user)

    def post(self, data):
        base = {"name": "Öğle arası", "active": "on", "apply_to": "each_class", "importance": "strict", "param": "1"}
        return self.client.post(reverse("timetable:data_new", args=[self.school.pk, "kart-iliskileri"]), {**base, **data})

    def test_saves_time_map(self):
        response = self.post({
            "condition": CardRelationship.RANGE_MAX_PER_DAY, "param": "2",
            "time_map": json.dumps(["1-4", "0-3", "0-3", "9-9", "x"]),
        })
        self.assertRedirects(response, reverse("timetable:data_list", args=[self.school.pk, "kart-iliskileri"]))
        rel = CardRelationship.objects.get(school=self.school, name="Öğle arası")
        self.assertEqual(rel.time_map, ["0-3", "1-4"])
        page = self.client.get(reverse("timetable:data_list", args=[self.school.pk, "kart-iliskileri"]))
        self.assertContains(page, "2 saat işaretli")
        edit = self.client.get(reverse("timetable:data_edit", args=[self.school.pk, "kart-iliskileri", rel.pk]))
        self.assertContains(edit, "data-time-map")
        self.assertContains(edit, 'id="time-map-meta"')

    def test_required_inputs(self):
        response = self.post({"condition": CardRelationship.MAP_MIN_WEEK, "time_map": "[]"})
        self.assertContains(response, "zaman haritasında en az bir hücre")
        response = self.post({"condition": CardRelationship.AB_NOT_CONSECUTIVE, "subjects": [Subject.objects.filter(school=self.school).first().pk]})
        self.assertContains(response, "B tarafında")
        response = self.post({"condition": CardRelationship.ROOM_MIN_WEEK})
        self.assertContains(response, "en az bir derslik")
