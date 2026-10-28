"""Kart ilişkisi düzenleyicisi: seçici verileri (teori/uygulama rozeti, gruplar) ve otomatik ad."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.data_views import _relationship_picker
from timetable.forms import RelationshipForm
from timetable.models import CardRelationship, Lesson, School, SchoolClass, Subject, Teacher


class RelationshipEditorTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO")
        self.theory = Subject.objects.create(school=self.school, name="Algoritma", short="BİL103")
        self.practical = Subject.objects.create(school=self.school, name="Algoritma (U)", short="BİL103")
        self.other = Subject.objects.create(school=self.school, name="Tarih", short="TAR101")
        self.cls = SchoolClass.objects.create(school=self.school, name="84.KISIM", short="84BİL")
        SchoolClass.objects.create(school=self.school, name="1.KISIM", short="1SVN")
        teacher = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Er", department="BİL")
        self.lessons = []
        for subject in (self.theory, self.practical):
            lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=2, card_length=2)
            lesson.classes.add(self.cls)
            lesson.teachers.add(teacher)
            self.lessons.append(lesson)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def test_picker_data(self):
        form = RelationshipForm(school=self.school)
        data = _relationship_picker(self.school, form)
        kinds = {s["name"]: s["kind"] for s in data["subjects"]}
        self.assertEqual(kinds, {"Algoritma": "T", "Algoritma (U)": "U", "Tarih": ""})
        lesson = next(s for s in data["subjects"] if s["name"] == "Algoritma")["lessons"][0]
        self.assertEqual((lesson["classes"], lesson["teachers"], lesson["blocks"]), ("84BİL", "Ali Er", 2))
        self.assertEqual({c["group"] for c in data["classes"]}, {"BİL", "SVN"})
        self.assertEqual(data["teachers"][0]["group"], "BİL")

    def test_editor_saves_with_auto_name(self):
        url = reverse("timetable:data_new", args=[self.school.pk, "kart-iliskileri"])
        page = self.client.get(url)
        self.assertContains(page, "data-rel-editor")
        self.assertContains(page, "relationship.js")
        response = self.client.post(url, {"condition": CardRelationship.CONSECUTIVE, "param": "1", "apply_to": "each_class",
                                          "importance": "strict", "lessons": [l.pk for l in self.lessons], "card_length": "",
                                          "time_map": "[]", "time_map_b": "[]", "active": "on", "note": "teori + uygulama"},
                                    HTTP_X_REQUESTED_WITH="fetch")
        self.assertTrue(response.json()["ok"], response.content)
        rel = CardRelationship.objects.get()
        self.assertTrue(rel.name.startswith("Art arda, bitişik"))
        self.assertIn("BİL103 (84BİL)", rel.name)
        self.assertEqual(rel.note, "teori + uygulama")
        page = self.client.get(reverse("timetable:data_edit", args=[self.school.pk, "kart-iliskileri", rel.pk]))
        self.assertContains(page, f'name="lessons" value="{self.lessons[0].pk}"')
