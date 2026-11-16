import unittest

from lightcycle.domain.pool.sleep import awake_elapsed, detect_sleep, overlaps_sleep


class TestAwakeElapsed(unittest.TestCase):
    def test_awake_elapsed_worked_values(self):
        self.assertEqual(awake_elapsed(1000, 10000, ((2000, 9200),)), 1800)
        self.assertEqual(awake_elapsed(1000, 10000, ((0, 1000),)), 9000)
        self.assertEqual(awake_elapsed(1000, 10000, ((10000, 12000),)), 9000)
        self.assertEqual(awake_elapsed(1000, 3000, ((500, 2000),)), 1000)

    def test_no_sleeps_is_the_plain_difference(self):
        self.assertEqual(awake_elapsed(10, 50), 40)

    def test_never_below_zero(self):
        self.assertEqual(awake_elapsed(100, 200, ((0, 500),)), 0)


class TestDetectSleep(unittest.TestCase):
    def test_a_long_gap_is_an_interval_ending_at_the_observation(self):
        self.assertEqual(detect_sleep((1000.0, 500.0), 8200.0, 600.0), (1100.0, 8200.0))

    def test_a_short_gap_is_ignored(self):
        self.assertIsNone(detect_sleep((1000.0, 500.0), 1105.0, 600.0))

    def test_exactly_the_slack_is_ignored_and_one_more_second_is_not(self):
        self.assertIsNone(detect_sleep((1000.0, 500.0), 1010.0, 500.0))
        self.assertEqual(detect_sleep((1000.0, 500.0), 1011.0, 500.0), (1000.0, 1011.0))

    def test_an_awake_clock_that_goes_backwards_records_nothing(self):
        self.assertIsNone(detect_sleep((1000.0, 500.0), 9000.0, 100.0))

    def test_a_wall_clock_that_goes_backwards_records_nothing(self):
        self.assertIsNone(detect_sleep((1000.0, 500.0), 900.0, 600.0))

    def test_no_sample_records_nothing(self):
        self.assertIsNone(detect_sleep(None, 1000.0, 500.0))


class TestOverlapsSleep(unittest.TestCase):
    def test_touching_an_endpoint_is_not_overlap(self):
        self.assertFalse(overlaps_sleep(100, 200, ((0, 100),)))
        self.assertFalse(overlaps_sleep(100, 200, ((200, 300),)))

    def test_one_second_of_overlap_is_overlap(self):
        self.assertTrue(overlaps_sleep(100, 200, ((199, 300),)))

    def test_no_sleeps_never_overlaps(self):
        self.assertFalse(overlaps_sleep(100, 200))


if __name__ == "__main__":
    unittest.main()
