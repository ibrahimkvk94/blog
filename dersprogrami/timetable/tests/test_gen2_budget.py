"""Uzatma sınırları gerçek 30 dakika beklemeden, denetimli zamanlarla sınanır."""

from unittest import mock

from django.test import SimpleTestCase

from timetable.solver.gen2 import _SearchBudget, _TimedDraftRound


class Gen2BudgetTests(SimpleTestCase):
    def setUp(self):
        self.budget = _SearchBudget(100, 1800)
        self.budget.observe(17, 110)

    def test_early_improvements_do_not_accumulate_time(self):
        self.budget.observe(16, 120)
        self.budget.observe(10, 1839.99)
        self.assertEqual(self.budget.deadline, 1900)
        self.assertEqual(self.budget.extensions, 0)

    def test_last_minute_opens_only_one_extension(self):
        self.budget.observe(16, 1840)
        self.budget.observe(15, 1899)
        self.assertEqual(self.budget.deadline, 1960)
        self.assertEqual(self.budget.extensions, 1)

    def test_each_new_record_in_overtime_adds_one_minute(self):
        self.budget.observe(16, 1840)
        self.budget.observe(15, 1900)
        self.budget.observe(12, 1920)  # üç birim düşüş tek iyileşme olayıdır
        self.assertEqual(self.budget.stats(), {"budget_seconds": 1980, "extension_seconds": 180, "extensions": 3})

    def test_equal_and_worse_results_cannot_extend(self):
        self.budget.observe(16, 1840)
        self.budget.observe(16, 1901)
        self.budget.observe(17, 1910)
        self.budget.observe(16, 1920)
        self.assertEqual(self.budget.deadline, 1960)

    def test_expired_budget_cannot_be_revived(self):
        self.budget.observe(16, 1900)
        self.assertEqual(self.budget.deadline, 1900)
        self.budget.observe(15, 2000)
        self.assertEqual(self.budget.extensions, 0)

    def test_first_draft_and_zero_do_not_earn_time(self):
        budget = _SearchBudget(100, 1800)
        budget.observe(17, 1850)
        budget.observe(0, 1890)
        self.assertEqual(budget.extensions, 0)

    def test_callback_uses_event_time_and_shares_record_across_rounds(self):
        class Callback(_TimedDraftRound):
            score = 16
            stopped = False

            def ObjectiveValue(self):
                return self.score

            def StopSearch(self):
                self.stopped = True

        reports = []
        progress = lambda p: reports.append({**p, **self.budget.stats()})
        first = Callback(progress, 1, 17, self.budget)
        with mock.patch("timetable.solver.gen2.time.monotonic", return_value=1841):
            first.on_solution_callback()
        second = Callback(progress, 2, 16, self.budget)
        with mock.patch("timetable.solver.gen2.time.monotonic", return_value=1901):
            second.on_solution_callback()  # önceki rekor yeni turda tekrar raporlandı
            self.assertEqual(self.budget.extensions, 1)
            second.score = 15
            second.on_solution_callback()
            self.assertEqual(reports[-1]["extension_seconds"], 120)
            second.score = 0
            second.on_solution_callback()
            self.assertTrue(second.stopped)
            self.assertEqual(self.budget.extensions, 2)
