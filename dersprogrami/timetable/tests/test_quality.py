"""Kalite karnesi ve "Programı iyileştir"."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import quality
from timetable.models import Card, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable
from timetable.resolve import Center
from timetable.solver import cpsat
from timetable.solver.problem import Problem, ProblemCard, TeacherLimits


def _school():
    school = School.objects.create(name="Okul", days_per_week=3)
    for i in range(4):
        Period.objects.create(school=school, index=i, name=str(i + 1))
    return school


class QualityReportTests(TestCase):
    def setUp(self):
        self.school = _school()
        self.teacher = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya")
        self.cls = SchoolClass.objects.create(school=self.school, name="1.KISIM")
        self.other = SchoolClass.objects.create(school=self.school, name="11.KISIM")
        subject = Subject.objects.create(school=self.school, name="Mat", short="MAT")
        lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=4, card_length=1)
        lesson.teachers.add(self.teacher)
        lesson.classes.add(self.cls)
        self.timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        # Pazartesi 1 ve 4 (2 saat boşluk), Salı 1 (tek ders için gelinen gün), bir kart bekliyor
        for day, period in ((0, 0), (0, 3), (1, 0), (None, None)):
            Card.objects.create(timetable=self.timetable, lesson=lesson, length=1, day=day, period=period)

    def test_teacher_metrics_and_score(self):
        data = quality.report(self.timetable, "ogretmen")
        row = next(r for r in data["rows"] if r["id"] == self.teacher.id)
        self.assertEqual((row["hours"], row["days"], row["gaps"], row["single_days"], row["unplaced"]), (3, 2, 2, 1, 1))
        self.assertEqual(row["extra_days"], 1)  # 3 saat tek güne sığardı
        self.assertEqual(row["score"], 2 * 2 + 3 * 1 + 1 * 1 + 4 * 1)
        self.assertEqual(row["level"], "kotu")  # 12 > 10
        self.assertEqual(data["summary"]["gaps"], 2)

    def test_class_rows_and_page(self):
        data = quality.report(self.timetable, "sinif")
        names = [r["name"] for r in data["rows"]]
        self.assertEqual(names, ["1.KISIM"])  # dersi olmayan 11.KISIM listelenmez
        self.assertEqual(data["rows"][0]["extra_days"], 0)  # sınıflarda "fazla gün" yok
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        page = self.client.get(reverse("timetable:quality", args=[self.timetable.pk]) + "?tur=ogretmen")
        self.assertContains(page, "Ali Kaya")
        self.assertContains(page, "Seçilenleri iyileştir")


class TeacherWeightTests(TestCase):
    def test_day_weight_packs_teacher_into_fewer_days(self):
        # Tek öğretmen, iki kart, iki gün × iki saat; gün cezası varken kartlar aynı güne toplanır.
        cards = [ProblemCard(key=k, lesson_id=k, length=1, teachers=(1,), atoms=(f"a{k}",), room_options=(),
                             universes=frozenset({(0, 0)}), starts=[(d, p) for d in range(2) for p in range(2)]) for k in range(2)]
        cards[0].starts, cards[1].starts = [(0, 0)], [(0, 1), (1, 1)]  # iki seçenekte de sınıfı geç başlar
        base = dict(days=2, periods=2, universes=frozenset({(0, 0)}), cards=cards, teacher_limits={1: TeacherLimits()})
        packed = cpsat.solve(Problem(**base, teacher_weights={1: (40, 30)}), time_limit=5, workers=1)
        self.assertEqual(packed.placements[1].day, 0)
        self.assertEqual(packed.penalties.get("teacher_day"), 30)


class ImproveTests(TestCase):
    def test_improve_reduces_gaps_with_few_moves(self):
        school = _school()
        teacher = Teacher.objects.create(school=school, first_name="Ayşe", last_name="Er")
        classes = [SchoolClass.objects.create(school=school, name=f"{n}.KISIM") for n in (1, 2)]
        subject = Subject.objects.create(school=school, name="Fizik", short="FİZ")
        timetable = Timetable.objects.create(school=school, name="t", status=Timetable.OK)
        for cls, (day, period) in zip(classes, ((0, 0), (0, 3))):
            lesson = Lesson.objects.create(school=school, subject=subject, periods_per_week=1, card_length=1)
            lesson.teachers.add(teacher)
            lesson.classes.add(cls)
            Card.objects.create(timetable=timetable, lesson=lesson, length=1, day=day, period=period)
        proposal = Center(timetable).improve(teacher_ids=[teacher.id], max_moves=2, time_limit=10)
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["new_violations_hard"], 0)
        self.assertEqual(proposal["quality"]["gaps"], [2, 0])
        self.assertEqual(proposal["count"], 1)

        # Ekrandan: öneri çözüm merkezinde gösterilir
        client = self.client
        client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        response = client.post(reverse("timetable:quality", args=[timetable.pk]),
                               {"tur": "ogretmen", "secim": [teacher.id], "en_fazla": "2", "sure": "10"})
        self.assertRedirects(response, reverse("timetable:solution_center", args=[timetable.pk]) + "?goster=1")
        page = client.get(reverse("timetable:solution_center", args=[timetable.pk]) + "?goster=1")
        self.assertContains(page, "Programı iyileştir (1 öğretmen)")
        self.assertContains(page, "İyileşme (seçilenler)")


class PendingTests(TestCase):
    def setUp(self):
        self.school = _school()
        self.teacher = Teacher.objects.create(school=self.school, first_name="Can", last_name="Ak")
        self.cls = SchoolClass.objects.create(school=self.school, name="1.KISIM")
        subject = Subject.objects.create(school=self.school, name="Kimya", short="KİM")
        self.timetable = Timetable.objects.create(school=self.school, name="t", status=Timetable.OK)
        self.lessons = []
        for _ in range(2):
            lesson = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=1, card_length=1)
            lesson.teachers.add(self.teacher)
            lesson.classes.add(self.cls)
            self.lessons.append(lesson)
        Card.objects.create(timetable=self.timetable, lesson=self.lessons[0], length=1, day=0, period=0)
        self.waiting = Card.objects.create(timetable=self.timetable, lesson=self.lessons[1], length=1)

    def test_analysis_and_direct_placement(self):
        from timetable import pending

        data = pending.analyze(self.timetable)
        row = data["rows"][0]
        self.assertEqual((row["id"], row["kind"], row["possible"], row["busy"]), (self.waiting.id, "free", 12, 1))
        self.assertEqual(len(row["free"]), 8)  # ilk 8 boş saat gösterilir
        result = pending.try_place(self.timetable, self.waiting.id)
        self.assertTrue(result["ok"], result)
        self.waiting.refresh_from_db()
        self.assertTrue(self.waiting.is_placed)

    def test_availability_reason_and_insert_request(self):
        from timetable import pending
        from timetable.models import Availability
        from timetable.resolve import Request

        for d in range(3):
            for p in range(4):
                if (d, p) != (0, 0):
                    Availability.objects.create(school=self.school, teacher=self.teacher, day=d, period=p, state="no")
        row = pending.analyze(self.timetable)["rows"][0]
        self.assertEqual(row["kind"], "conflict")  # tek açık saat dolu
        self.assertIn("Can Ak (öğretmen)", dict(row["blocked_by"]))
        self.assertFalse(pending.try_place(self.timetable, self.waiting.id)["ok"])
        # Tek açık saat öbür kartta ve o kart da başka yere gidemez: yer açılamaz
        proposals = Center(self.timetable).proposals(Request("insert", card_ids=[self.waiting.id], max_moves=4))
        self.assertEqual(proposals, [])

    def test_insert_moves_a_neighbour(self):
        from timetable.resolve import Request

        # Sınıf bütün hafta dolu değil; bekleyen kart için diğer kart kayarak yer açılabilir
        proposals = Center(self.timetable).proposals(Request("insert", card_ids=[self.waiting.id], max_moves=3))
        self.assertTrue(proposals)
        moved = next(m for m in proposals[0]["moves"] if m["card_id"] == self.waiting.id)
        self.assertEqual(moved["from"], "yerleşmemiş")

    def test_page(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        page = self.client.get(reverse("timetable:pending", args=[self.timetable.pk]))
        self.assertContains(page, "Boş görünen saat var")
        self.assertContains(page, "tur=insert")
        response = self.client.post(reverse("timetable:pending", args=[self.timetable.pk]), {"kart": self.waiting.id})
        self.assertTrue(response.json()["ok"])
