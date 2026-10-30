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
