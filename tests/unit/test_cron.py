import datetime
import unittest

from lightcycle.domain.schedule.cron import next_due, parse_cron, previous_due


def at(month, day, hour=0, minute=0, year=2026):
    return datetime.datetime(year, month, day, hour, minute)


class TestAcceptanceExamples(unittest.TestCase):
    def test_previous_due_for_a_monday_nine_am(self):
        self.assertEqual(previous_due("0 9 * * 1", at(10, 14, 10)), at(10, 12, 9))

    def test_next_due_for_a_monday_nine_am(self):
        self.assertEqual(next_due("0 9 * * 1", at(10, 14, 10)), at(10, 19, 9))

    def test_previous_due_on_the_boundary_is_the_instant_itself(self):
        self.assertEqual(previous_due("0 * * * *", at(10, 14, 11)), at(10, 14, 11))

    def test_next_due_is_strictly_after(self):
        self.assertEqual(next_due("0 * * * *", at(10, 14, 11)), at(10, 14, 12))

    def test_seconds_are_truncated(self):
        self.assertEqual(
            previous_due("0 * * * *", datetime.datetime(2026, 10, 14, 11, 0, 59)), at(10, 14, 11))


class TestFields(unittest.TestCase):
    def test_lists_ranges_and_steps(self):
        self.assertEqual(next_due("0,30 9-10 * * *", at(10, 14, 9, 30)), at(10, 14, 10, 0))
        self.assertEqual(next_due("*/20 * * * *", at(10, 14, 9, 21)), at(10, 14, 9, 40))
        self.assertEqual(next_due("10-20/5 * * * *", at(10, 14, 9, 11)), at(10, 14, 9, 15))

    def test_sunday_is_zero_and_seven(self):
        sunday = at(10, 18, 9)
        self.assertEqual(next_due("0 9 * * 0", at(10, 14)), sunday)
        self.assertEqual(next_due("0 9 * * 7", at(10, 14)), sunday)

    def test_day_of_month_or_day_of_week_when_both_restricted(self):
        expr = "0 9 1 * 1"
        self.assertEqual(next_due(expr, at(10, 1, 9)), at(10, 5, 9))
        self.assertEqual(next_due(expr, at(10, 26, 9)), at(11, 1, 9))
        self.assertEqual(previous_due(expr, at(10, 31)), at(10, 26, 9))

    def test_only_day_of_week_restricted_ignores_day_of_month(self):
        self.assertEqual(next_due("0 9 * * 2", at(10, 14, 9)), at(10, 20, 9))

    def test_month_end_rollover(self):
        self.assertEqual(next_due("0 0 * * *", at(10, 31, 0)), at(11, 1, 0))
        self.assertEqual(previous_due("0 0 1 * *", at(12, 31)), at(12, 1, 0))

    def test_a_leap_day_is_found(self):
        self.assertEqual(next_due("0 0 29 2 *", at(3, 1, year=2026)), at(2, 29, year=2028))
        self.assertEqual(previous_due("0 0 29 2 *", at(3, 1, year=2026)), at(2, 29, year=2024))

    def test_matches_across_year_end(self):
        self.assertEqual(next_due("0 0 1 1 *", at(12, 31, 23, 59)), at(1, 1, year=2027))


class TestRefusals(unittest.TestCase):
    def test_unsupported_syntax_is_a_value_error(self):
        for expr in (
            "@daily", "0 9 * * mon", "0 9 * jan *", "0 0 L * *", "0 0 15W * *", "0 0 * * 1#2",
            "? * * * *", "60 * * * *", "0 24 * * *", "0 0 0 * *", "0 0 32 * *", "0 0 * 13 *",
            "0 0 * * 8", "* * * *", "* * * * * *", "5-1 * * * *", "*/0 * * * *", "5/2 * * * *",
            "", "a * * * *",
        ):
            with self.subTest(expr=expr):
                with self.assertRaises(ValueError):
                    parse_cron(expr)

    def test_a_never_matching_expression_is_a_value_error(self):
        for expr in ("0 0 30 2 *", "0 0 31 4 *"):
            with self.subTest(expr=expr):
                with self.assertRaises(ValueError):
                    parse_cron(expr)

    def test_next_due_refuses_a_bad_expression(self):
        with self.assertRaises(ValueError):
            next_due("@daily", at(10, 14))
