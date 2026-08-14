import unittest

from lightcycle.domain.feedback.format_elapsed import format_elapsed


class TestFormatElapsed(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(format_elapsed(45), "45s")

    def test_minutes(self):
        self.assertEqual(format_elapsed(840), "14m")

    def test_hours_and_minutes(self):
        self.assertEqual(format_elapsed(4020), "1h 7m")

    def test_sixty_seconds_is_one_minute_not_sixty_seconds(self):
        self.assertEqual(format_elapsed(60), "1m")

    def test_thirty_six_hundred_seconds_is_one_hour_not_sixty_minutes(self):
        self.assertEqual(format_elapsed(3600), "1h 0m")
