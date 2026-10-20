import unittest

from lightcycle.cli import _tick_duration_lines


class TestTickDurationLines(unittest.TestCase):
    def test_under_the_interval_returns_no_line(self):
        self.assertEqual(_tick_duration_lines(2.0, 5), [])

    def test_equal_to_the_interval_returns_no_line(self):
        self.assertEqual(_tick_duration_lines(5.0, 5), [])

    def test_over_the_interval_returns_one_line_with_one_decimal(self):
        self.assertEqual(
            _tick_duration_lines(31.04, 5),
            ["tick overran: took 31.0s against poll-seconds 5"],
        )
