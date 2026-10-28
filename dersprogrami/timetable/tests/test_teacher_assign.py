"""Öğretmen atama sayfası ve ders formundaki öğretmen önerileri."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.data_views import _teacher_hints
from timetable.models import Lesson, School, SchoolClass, Subject, Teacher


class TeacherAssignTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO")
        self.math = Subject.objects.create(school=self.school, name="Matematik")
        self.ahmet = Teacher.objects.create(school=self.school, first_name="Ahmet", last_name="Er")
        self.mehmet = Teacher.objects.create(school=self.school, first_name="Mehmet", last_name="Kaya")
        self.ayse = Teacher.objects.create(school=self.school, first_name="Ayşe", last_name="Ak")
        self.ayse.subjects.add(self.math)
        self.lessons = []
        for name, teachers in (("2.KISIM", [self.ahmet]), ("10.KISIM", []), ("3.KISIM", [self.ahmet, self.mehmet])):
            lesson = Lesson.objects.create(school=self.school, subject=self.math, periods_per_week=3)
            lesson.classes.add(SchoolClass.objects.create(school=self.school, name=name))
            lesson.teachers.set(teachers)
            self.lessons.append(lesson)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:teacher_assign", args=[self.school.pk])

    def test_page_lists_sections_and_saves(self):
        page = self.client.get(self.url)
        self.assertContains(page, "1 öğretmensiz")
        rows = [r["classes"] for r in page.context["rows"]]
        self.assertEqual(rows, ["2.KISIM", "3.KISIM", "10.KISIM"])  # doğal sıralama
        data = page.context["options_json"]
        self.assertEqual([t["name"] for t in data["teaching"]], ["Ahmet Er", "Mehmet Kaya"])
        self.assertEqual([t["name"] for t in data["branch"]], ["Ayşe Ak"])
        l2, l10, l3 = self.lessons
        self.client.post(self.url, {"ders": self.math.pk, "action": "save", f"ogretmen-{l2.pk}": self.mehmet.pk, f"kilit-{l2.pk}": "on",
                                    f"ogretmen-{l10.pk}": self.ayse.pk, f"ogretmen-{l3.pk}": ""})
        self.assertEqual(list(l2.teachers.all()), [self.mehmet])
        l2.refresh_from_db()
        self.assertTrue(l2.teacher_locked)
        self.assertEqual(list(l10.teachers.all()), [self.ayse])
        self.assertEqual(l3.teachers.count(), 2)  # çok öğretmenli derse dokunulmaz

    def test_lesson_form_hints(self):
        hints = _teacher_hints(self.school)
        self.assertEqual(hints["teaching"][self.math.pk], sorted([self.ahmet.pk, self.mehmet.pk]))
        self.assertEqual(hints["branch"][self.math.pk], [self.ayse.pk])
        self.assertEqual(hints["loads"][self.ahmet.pk], 6)
        page = self.client.get(reverse("timetable:lesson_edit", args=[self.school.pk, self.lessons[0].pk]))
        self.assertContains(page, 'id="teacher-hints"')


class BulkDistributeTests(TestCase):
    """Toplu dağıtım: kotalar, bloklar, mevcut atamayı koruma ve aynı saatteki kısımlar."""

    def setUp(self):
        from timetable.models import Card, Period, Timetable

        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.math = Subject.objects.create(school=self.school, name="Matematik", short="TEM100")
        self.t = [Teacher.objects.create(school=self.school, first_name=n, last_name="Hoca") for n in ("Ali", "Can", "Ece")]
        self.timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        self.school.active_timetable = self.timetable
        self.school.save()
        self.lessons = []
        for i in range(6):
            lesson = Lesson.objects.create(school=self.school, subject=self.math, periods_per_week=1)
            lesson.classes.add(SchoolClass.objects.create(school=self.school, name=f"{i + 1}.KISIM"))
            self.lessons.append(lesson)
            # 1-2-3. kısımlar pazartesi 1. saatte aynı anda; diğerleri farklı saatlerde
            Card.objects.create(timetable=self.timetable, lesson=lesson, length=1, day=0 if i < 3 else 1, period=0 if i < 3 else i)

    def test_quotas_blocks_and_parallel_sections(self):
        from collections import Counter

        from timetable import bulk_assign

        result, notes = bulk_assign.distribute(self.school, self.lessons, {self.t[0].id: 2, self.t[1].id: 2, self.t[2].id: 2})
        self.assertEqual(Counter(result.values()), Counter({t.id: 2 for t in self.t}))
        # aynı saatteki üç kısım üç farklı öğretmende
        self.assertEqual(len({result[l.id] for l in self.lessons[:3]}), 3)
        self.assertIn("6 kısım dağıtıldı", notes[0])
        # Kota toplamı tutmazsa hata; aynı saatte 3 kısım ama 2 öğretmen varsa hata
        with self.assertRaises(bulk_assign.DistributeError):
            bulk_assign.distribute(self.school, self.lessons, {self.t[0].id: 2})
        with self.assertRaises(bulk_assign.DistributeError):
            bulk_assign.distribute(self.school, self.lessons, {self.t[0].id: 3, self.t[1].id: 3})
        # Programı yok sayınca blok halinde sıralı dağılır
        plain, _ = bulk_assign.distribute(self.school, self.lessons, {self.t[0].id: 3, self.t[1].id: 3}, use_timetable=False)
        self.assertEqual([plain[l.id] for l in self.lessons], [self.t[0].id] * 3 + [self.t[1].id] * 3)

    def test_keeps_current_assignment_and_preview_page(self):
        from timetable import bulk_assign

        for lesson, teacher in zip(self.lessons, [self.t[2], self.t[1], self.t[0], self.t[2], self.t[1], self.t[0]]):
            lesson.teachers.add(teacher)
        result, notes = bulk_assign.distribute(self.school, self.lessons, {t.id: 2 for t in self.t})
        self.assertEqual(result, {l.id: l.teachers.first().id for l in self.lessons})  # hiçbir şey değişmez
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:teacher_assign", args=[self.school.pk])
        page = self.client.post(url, {"ders": self.math.pk, "action": "distribute", "program": "1",
                                      "kota-ogretmen": [t.id for t in self.t], "kota-sayi": ["2", "2", "2"]})
        self.assertContains(page, "data-proposed")
        self.assertContains(page, "6 kısım dağıtıldı")
        self.assertEqual(self.lessons[0].teachers.first(), self.t[2])  # önizleme kaydetmez


class TeacherPoolPageTests(TestCase):
    def setUp(self):
        from timetable.models import Card, Period, Timetable

        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.math = Subject.objects.create(school=self.school, name="Matematik", short="TEM100")
        self.t = [Teacher.objects.create(school=self.school, first_name=n, last_name="Hoca") for n in ("Ali", "Can", "Ece")]
        self.timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        self.lessons = []
        for i in range(6):
            lesson = Lesson.objects.create(school=self.school, subject=self.math, periods_per_week=1)
            lesson.classes.add(SchoolClass.objects.create(school=self.school, name=f"{i + 1}.KISIM"))
            self.lessons.append(lesson)
            Card.objects.create(timetable=self.timetable, lesson=lesson, length=1, day=0 if i < 3 else 1, period=0 if i < 3 else i - 3)
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:teacher_assign", args=[self.school.pk])

    def test_save_quotas_status_and_clear(self):
        from timetable.models import TeacherQuota

        post = {"ders": self.math.pk, "action": "save_quotas", "kota-ogretmen": [t.id for t in self.t], "kota-sayi": ["2", "2", "2"]}
        self.client.post(self.url, post)
        self.assertEqual(TeacherQuota.objects.count(), 3)
        page = self.client.get(self.url + f"?ders={self.math.pk}")
        self.assertTrue(page.context["pool"]["ok"])
        self.assertContains(page, "üretimde 6 kısım dağıtılır")
        # Sabit kısım öğretmenin kotasından düşer
        self.lessons[0].teachers.add(self.t[0])
        self.lessons[0].teacher_locked = True
        self.lessons[0].save()
        self.assertEqual(self.client.get(self.url + f"?ders={self.math.pk}").context["pool"]["free"], 5)
        # Tutmayan kota uyarısı
        self.client.post(self.url, {**post, "kota-sayi": ["1", "2", "2"]})
        self.assertFalse(self.client.get(self.url + f"?ders={self.math.pk}").context["pool"]["ok"])
        self.client.post(self.url, {"ders": self.math.pk, "action": "save_quotas"})
        self.assertFalse(TeacherQuota.objects.exists())

    def test_preview_distribution_respects_parallel_sections_and_lock(self):
        from collections import Counter

        from timetable import bulk_assign

        self.lessons[0].teachers.add(self.t[2])
        self.lessons[0].teacher_locked = True
        self.lessons[0].save()
        result, notes = bulk_assign.distribute(self.school, self.lessons, {t.id: 2 for t in self.t})
        self.assertEqual(result[self.lessons[0].id], self.t[2].id)
        self.assertEqual(len({result[l.id] for l in self.lessons[:3]}), 3)  # aynı saatteki 3 kısım
        self.assertEqual(Counter(result.values()), Counter({t.id: 2 for t in self.t}))
        with self.assertRaises(bulk_assign.DistributeError):
            bulk_assign.distribute(self.school, self.lessons, {self.t[0].id: 3, self.t[1].id: 3})
        page = self.client.post(self.url, {"ders": self.math.pk, "action": "distribute", "program": "1",
                                           "kota-ogretmen": [t.id for t in self.t], "kota-sayi": ["2", "2", "2"]})
        self.assertContains(page, "data-proposed")
