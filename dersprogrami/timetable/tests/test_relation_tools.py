"""Teori + uygulama ilişki sihirbazı ve ilişki denetimi."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import relation_wizard as rw
from timetable.models import Card, CardRelationship as R, Lesson, Period, School, SchoolClass, Subject, Timetable


class RelationToolTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=2)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        theory = Subject.objects.create(school=self.school, name="Algoritma", short="BİL103")
        practical = Subject.objects.create(school=self.school, name="Algoritma (U)", short="BİL103")
        # "Uygulamaları" ad içinde geçse de uygulama dersi sayılmaz
        Subject.objects.create(school=self.school, name="Temel Bilgi Teknolojileri ve Uygulamaları", short="BİL110")
        lonely = Subject.objects.create(school=self.school, name="Yapı Resmi (U)", short="İNŞ101")
        self.lessons = {}
        for cls_name in ("1A", "1B"):
            cls = SchoolClass.objects.create(school=self.school, name=cls_name)
            for subject in (theory, practical):
                lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=1)
                lesson.classes.add(cls)
                self.lessons[(cls_name, subject.name)] = lesson
        orphan = Lesson.objects.create(school=self.school, subject=lonely, periods_per_week=1)
        orphan.classes.add(SchoolClass.objects.get(name="1A"))
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))

    def test_wizard_detects_and_applies(self):
        data = rw.analyze(self.school)
        self.assertEqual(data["summary"], {"pairs": 2, "missing": 2, "ok": 0, "duplicate": 0, "unpaired": 1})
        url = reverse("timetable:relation_wizard", args=[self.school.pk])
        keys = [p["key"] for p in data["pairs"]]
        self.client.post(url, {"cift": keys, "kosul": R.CONSECUTIVE_ORDERED, "onem": "strict", "islem": "create"})
        self.assertEqual(R.objects.count(), 2)
        rel = R.objects.first()
        self.assertEqual(rel.condition, R.CONSECUTIVE_ORDERED)
        self.assertTrue(rel.name.startswith("Teori + uygulama"))
        # Kopya oluşturup temizle; sonra hepsini aynı güne çevir
        copy = R.objects.create(school=self.school, name="kopya", condition=R.CONSECUTIVE)
        copy.lessons.set(rel.lessons.all())
        self.assertEqual(rw.analyze(self.school)["summary"]["duplicate"], 1)
        self.client.post(url, {"cift": keys, "kosul": R.SAME_DAY, "onem": "high", "islem": "update"})
        self.assertEqual(R.objects.count(), 2)
        self.assertEqual(set(R.objects.values_list("condition", "importance")), {(R.SAME_DAY, "high")})
        self.client.post(url, {"cift": keys[:1], "kosul": R.SAME_DAY, "islem": "remove"})
        self.assertEqual(R.objects.count(), 1)

    def test_audit_counts_and_bulk_actions(self):
        tt = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        self.school.active_timetable = tt
        self.school.save()
        t, u = self.lessons[("1A", "Algoritma")], self.lessons[("1A", "Algoritma (U)")]
        Card.objects.create(timetable=tt, lesson=t, length=1, day=0, period=0)
        Card.objects.create(timetable=tt, lesson=u, length=1, day=1, period=0)  # art arda değil → ihlal
        broken = R.objects.create(school=self.school, name="art arda", condition=R.CONSECUTIVE)
        broken.lessons.set([t, u])
        twin = R.objects.create(school=self.school, name="ikiz", condition=R.CONSECUTIVE)
        twin.lessons.set([t, u])
        empty = R.objects.create(school=self.school, name="boş", condition=R.MAX_PER_DAY,
                                 apply_to=R.EACH_CLASS)
        empty.classes.set([SchoolClass.objects.get(name="1B")])  # 1B'nin programda kartı yok
        url = reverse("timetable:relation_audit", args=[self.school.pk])
        page = self.client.get(url)
        rows = {r["rel"].name: r for r in page.context["rows"]}
        self.assertIn("violated", rows["art arda"]["flags"])
        self.assertEqual(rows["art arda"]["cards"], 2)
        self.assertIn("duplicate", rows["ikiz"]["flags"])
        self.assertTrue(rows["art arda"]["keep"])
        self.assertIn("empty", rows["boş"]["flags"])
        self.client.post(url, {"iliski": [twin.pk, empty.pk], "islem": "disable"})
        self.assertEqual(R.objects.filter(active=False).count(), 2)
        self.client.post(url, {"iliski": [twin.pk], "islem": "delete"})
        self.assertFalse(R.objects.filter(pk=twin.pk).exists())
