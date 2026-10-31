"""aSc uyum denetimi: aSc'den içe aktarılan programın da sağlamadığı kurallar işaretlenir ve tercihe çevrilebilir."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import input_diff
from timetable.demo import create_demo_school
from timetable.models import CardRelationship, Timetable
from timetable.services import _asc_mismatch, generate_timetable


class AscMismatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.asc = generate_timetable(cls.school, "x", time_limit=20)
        Timetable.objects.filter(pk=cls.asc.pk).update(name=input_diff.ASC_TIMETABLE)
        # aSc'nin programının kesinlikle sağlamadığı kural: her öğretmen tüm saatlerde günde en fazla 1 ders.
        cls.rel = CardRelationship.objects.create(
            school=cls.school, name="aSc 58: deneme", condition=CardRelationship.RANGE_MAX_PER_DAY, param=1,
            apply_to="each_teacher", importance=CardRelationship.STRICT,
            time_map=[f"{d}-{p}" for d in range(cls.school.days_per_week) for p in range(cls.school.periods.count())])

    def test_helper_finds_rule(self):
        tt, found = input_diff.asc_mismatches(self.school)
        self.assertEqual(tt.pk, self.asc.pk)
        self.assertIn(self.rel.pk, found)
        report = _asc_mismatch(self.school)
        self.assertEqual(report["rules"][0][0], "aSc 58: deneme")

    def test_audit_flags_and_softens(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:relation_audit", args=[self.school.pk])
        page = self.client.get(url + "?durum=asc")
        self.assertContains(page, "aSc'nin kendi programında da sağlanmıyor")
        self.assertContains(page, "aSc 58: deneme")
        self.client.post(url, {"islem": "soften", "iliski": [self.rel.pk]})
        self.rel.refresh_from_db()
        self.assertEqual(self.rel.importance, CardRelationship.HIGH)


class BestHintTests(TestCase):
    """Üretim ipucu: adaylar (son başarılı, aSc çözümü, aktif/yayındaki) arasından bugünkü veriyle en az ihlalli olan."""

    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.good = generate_timetable(cls.school, "iyi", time_limit=20)
        cls.bad = generate_timetable(cls.school, "kötü", time_limit=20)
        Timetable.objects.filter(pk=cls.bad.pk).update(name=input_diff.ASC_TIMETABLE)
        ids = list(cls.bad.cards.values_list("pk", flat=True)[:5])
        cls.bad.cards.filter(pk__in=ids).update(day=None, period=None)  # 5 kart yerleşmemiş: 5 kesin ihlal

    def test_picks_fewest_violations_and_solver_repairs_from_it(self):
        target = Timetable.objects.create(school=self.school, name="yeni", status=Timetable.RUNNING)
        hint, hard = input_diff.best_hint(target)
        self.assertEqual((hint.pk, hard), (self.good.pk, 0))

        from timetable.solver import cpsat
        from timetable.solver.builder import build_problem

        problem = build_problem(self.school, base=hint, lock_base=False)
        solution = cpsat.solve(problem, time_limit=30, two_phase=True)
        self.assertTrue(solution.ok, solution.status)
        self.assertIn("from_hint", solution.stats["phase1"])
        self.assertEqual(solution.stats["phase1"]["from_hint"]["violations"], 0)
