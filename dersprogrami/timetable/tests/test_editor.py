"""Kayıt düzenleyici (sayfadan çıkmadan kaydetme, doğal sıralama), ana görünümde değişen kartların
gönderilmesi ve okul problemi önbelleği."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import problem_cache
from timetable.demo import create_demo_school
from timetable.models import Lesson, Period, School, SchoolClass, Teacher
from timetable.services import generate_timetable
from timetable.textsort import natural_key

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class NaturalSortTests(TestCase):
    def test_numbers_and_turkish_letters(self):
        names = ["10.KISIM", "2.KISIM", "1.KISIM", "Çağrı", "Can", "İnşaat 10", "İnşaat 2", "Işık", "Zeki"]
        self.assertEqual(sorted(names, key=natural_key),
                         ["1.KISIM", "2.KISIM", "10.KISIM", "Can", "Çağrı", "Işık", "İnşaat 2", "İnşaat 10", "Zeki"])


class EditorTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(8):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        for name in ("10.KISIM", "2.KISIM", "1.KISIM"):
            SchoolClass.objects.create(school=self.school, name=name)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def url(self, name, *args):
        return reverse(f"timetable:{name}", args=[self.school.pk, *args])

    def test_class_list_and_navigator_are_naturally_sorted(self):
        html = self.client.get(self.url("data_list", "siniflar")).content.decode()
        self.assertLess(html.index("1.KISIM"), html.index("2.KISIM"))
        self.assertLess(html.index("2.KISIM"), html.index("10.KISIM"))
        cls = SchoolClass.objects.get(name="2.KISIM")
        page = self.client.get(self.url("data_edit", "siniflar", cls.pk))
        self.assertEqual([i["label"] for i in page.context["navigator"]["items"]], ["1.KISIM", "2.KISIM", "10.KISIM"])
        self.assertEqual(page.context["navigator"]["position"], "2 / 3")
        self.assertEqual([t["key"] for t in page.context["tabs"]], ["genel", "kisitlar", "bolunmeler", "musaitlik"])

    def test_save_without_leaving_the_page(self):
        cls = SchoolClass.objects.get(name="1.KISIM")
        response = self.client.post(self.url("data_edit", "siniflar", cls.pk), {"name": "1.KISIM", "short": "1SVN",
                                    "availability": json.dumps({"4-7": "no"}), "divisions": "[]"}, **FETCH)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["reload"])
        self.assertEqual(data["title"], "1.KISIM")
        cls.refresh_from_db()
        self.assertEqual(cls.short, "1SVN")
        self.assertEqual(list(cls.availabilities.values_list("day", "period")), [(4, 7)])

    def test_errors_come_back_per_field(self):
        cls = SchoolClass.objects.get(name="1.KISIM")
        response = self.client.post(self.url("data_edit", "siniflar", cls.pk), {"name": "", "divisions": "[]"}, **FETCH)
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["errors"])

    def test_new_record_and_new_divisions_reload_to_their_page(self):
        response = self.client.post(self.url("data_new", "ogretmenler"), {"first_name": "Ali", "last_name": "Kaya"}, **FETCH)
        teacher = Teacher.objects.get(last_name="Kaya")
        self.assertEqual((response.json()["reload"], response.json()["url"]), (True, self.url("data_edit", "ogretmenler", teacher.pk)))
        cls = SchoolClass.objects.get(name="1.KISIM")
        divisions = json.dumps([{"id": None, "name": "Dil", "groups": [{"id": None, "name": "A"}, {"id": None, "name": "B"}]}])
        response = self.client.post(self.url("data_edit", "siniflar", cls.pk), {"name": cls.name, "divisions": divisions}, **FETCH)
        self.assertTrue(response.json()["reload"])  # gruplar kimlik aldı: sayfa güncel kimliklerle açılmalı

    def test_lesson_editor(self):
        subject = self.school.subjects.create(name="Matematik", short="MAT")
        cls = SchoolClass.objects.get(name="1.KISIM")
        response = self.client.post(self.url("lesson_new"), {"subject": subject.pk, "classes": [cls.pk], "periods_per_week": "3",
                                                             "card_length": "1"}, **FETCH)
        lesson = Lesson.objects.get(subject=subject)
        self.assertEqual(response.json()["url"], self.url("lesson_edit", lesson.pk))
        page = self.client.get(self.url("lesson_edit", lesson.pk))
        self.assertEqual(page.context["navigator"]["title"], "1.KISIM dersleri")
        self.assertEqual(len(page.context["navigator"]["items"]), 1)


class GridDeltaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.timetable = generate_timetable(cls.school, "t", time_limit=20)

    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def test_move_returns_only_changed_cards(self):
        card = self.timetable.cards.filter(day__isnull=False, locked=False).first()
        options = self.client.get(reverse("timetable:api_card_options", args=[card.pk])).json()["options"]
        free = next(o for o in options if o["status"] == "free")
        response = self.client.post(reverse("timetable:api_card_move", args=[card.pk]),
                                    json.dumps({"day": free["day"], "period": free["period"]}),
                                    content_type="application/json", HTTP_X_GRID_KIND="ogretmen")
        delta = response.json()["delta"]
        self.assertEqual(delta["kind"], "ogretmen")
        moved = next(c for c in delta["cards"] if c["id"] == card.pk)
        self.assertEqual((moved["day"], moved["period"]), (free["day"], free["period"]))
        self.assertLess(len(delta["cards"]), self.timetable.cards.count())
        self.assertIn("placed", delta["stats"])
        self.assertTrue(delta["history"]["undo"])
        undo = self.client.post(reverse("timetable:api_undo", args=[self.timetable.pk]), HTTP_X_GRID_KIND="ogretmen").json()
        back = next(c for c in undo["delta"]["cards"] if c["id"] == card.pk)
        self.assertEqual((back["day"], back["period"]), (card.day, card.period))
        # Başlıksız istek (eski istemci) değişmeden çalışır
        plain = self.client.post(reverse("timetable:api_redo", args=[self.timetable.pk])).json()
        self.assertNotIn("delta", plain)

    def test_school_problem_cache_follows_data_changes(self):
        first = problem_cache.school_problem(self.school)
        self.assertIs(problem_cache.school_problem(self.school), first)
        teacher = self.school.teachers.first()
        teacher.max_days_per_week = 2
        teacher.save()  # yönetim paneli ya da kabuktan yapılmış gibi (veri sürümü artmadan)
        self.assertIsNot(problem_cache.school_problem(self.school), first)
