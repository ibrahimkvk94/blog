"""Ana görünümde "İhlalleri çöz": kesin ihlaller en az kartı oynatarak giderilir, geri alınabilir."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.demo import create_demo_school
from timetable.services import generate_timetable, resolve_violations, verify_timetable


def hard(tt):
    return sum(1 for v in verify_timetable(tt)[0] if v.level == "hard")


class ResolveViolationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.timetable = generate_timetable(cls.school, "t", time_limit=20)

    def _break(self):
        """Aynı sınıfın iki dersini aynı saate koyar: kesin çakışma."""
        cards = list(self.timetable.cards.filter(day__isnull=False, locked=False, length=1).select_related("lesson")
                     .prefetch_related("lesson__classes"))
        a = cards[0]
        cls = set(a.lesson.classes.all())
        b = next(c for c in cards[1:] if set(c.lesson.classes.all()) & cls and (c.day, c.period) != (a.day, a.period))
        b.day, b.period = a.day, a.period
        b.save(update_fields=["day", "period"])
        return b

    def test_resolves_with_few_moves(self):
        self.assertEqual(hard(self.timetable), 0)
        self._break()
        before = hard(self.timetable)
        self.assertGreater(before, 0)
        result = resolve_violations(self.timetable, time_limit=20)
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["before"], result["after"]), (before, 0))
        self.assertEqual(hard(self.timetable), 0)
        self.assertLessEqual(result["moved"], 6)  # tek çakışma için program baştan dağıtılmaz

    def test_nothing_to_do_and_api(self):
        self.assertEqual(resolve_violations(self.timetable, time_limit=5)["message"], "Programda kesin ihlal yok.")
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self._break()
        url = reverse("timetable:api_resolve", args=[self.timetable.pk])
        response = self.client.post(url, data='{"sure": 40}', content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["after"], 0)
        # Geri al: çakışmalı hale döner
        self.client.post(reverse("timetable:api_undo", args=[self.timetable.pk]))
        self.assertGreater(hard(self.timetable), 0)

    def test_page_has_button(self):
        self.client.force_login(User.objects.create_superuser("admin2", "b@x.tr", "pw"))
        page = self.client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk]))
        self.assertContains(page, "İhlalleri çöz")
        self.assertContains(page, 'data-resolve="90"')
