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


class SolutionCenterFixTests(TestCase):
    """Çözüm merkezinde "İhlalleri düzelt": öneri, rapor, korunan dersler ve uygulama."""

    @classmethod
    def setUpTestData(cls):
        cls.school = create_demo_school()
        cls.timetable = generate_timetable(cls.school, "t", time_limit=20)

    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        self.url = reverse("timetable:solution_center", args=[self.timetable.pk])

    def _break(self):
        return ResolveViolationsTests._break(self)

    def test_propose_then_apply(self):
        self._break()
        before = hard(self.timetable)
        page = self.client.post(self.url, {"action": "solve", "tur": "fix", "sure": "40"})
        proposals = page.context["proposals"]
        self.assertEqual(len(proposals), 1, page.context["error"])
        self.assertEqual(proposals[0]["violations"], (before, 0))
        self.assertContains(page, "program ihlalsiz olur")
        self.assertGreater(hard(self.timetable), 0)  # öneri uygulanmadan program değişmez
        self.client.post(self.url, {"action": "apply", "oneri": "0"})
        self.assertEqual(hard(self.timetable), 0)

    def test_no_violations_message(self):
        page = self.client.post(self.url, {"action": "solve", "tur": "fix"})
        self.assertEqual(page.context["error"], "Programda kesin ihlal yok.")

    def test_protected_lessons_stay(self):
        from timetable.resolve import Center, ResolveError, subject_code

        # Aynı sınıfın farklı kodlu iki dersini aynı saate koy: biri korunur, öteki taşınmalı.
        cards = list(self.timetable.cards.filter(day__isnull=False, locked=False, length=1)
                     .select_related("lesson__subject").prefetch_related("lesson__classes"))
        sitting, moved = next((a, b) for a in cards for b in cards
                              if set(a.lesson.classes.all()) & set(b.lesson.classes.all())
                              and subject_code(a.lesson.subject) != subject_code(b.lesson.subject)
                              and (a.day, a.period) != (b.day, b.period))
        moved.day, moved.period = sitting.day, sitting.period
        moved.save(update_fields=["day", "period"])
        code = subject_code(sitting.lesson.subject)
        proposals = Center(self.timetable).fix_violations(20, protected=[code])
        cards = {c.id: c for c in self.timetable.cards.select_related("lesson__subject")}
        self.assertFalse([m for m in proposals[0]["moves"] if m["time_moved"]
                          and subject_code(cards[m["card_id"]].lesson.subject) == code])
        # İki çakışan ders de korunursa düzeltme imkânsız: nedeni söylenir
        with self.assertRaisesMessage(ResolveError, "kendi aralarında çakışıyor"):
            Center(self.timetable).fix_violations(20, protected=[code, subject_code(moved.lesson.subject)])
