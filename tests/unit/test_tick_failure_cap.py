import unittest

from lightcycle.cli import _advance_tick_state, _tick_failure_action


class TestTickFailureAction(unittest.TestCase):
    def test_continues_below_the_cap(self):
        self.assertEqual(_tick_failure_action(1, 5), "continue")
        self.assertEqual(_tick_failure_action(4, 5), "continue")

    def test_raises_at_the_cap(self):
        self.assertEqual(_tick_failure_action(5, 5), "raise")

    def test_raises_beyond_the_cap(self):
        self.assertEqual(_tick_failure_action(6, 5), "raise")


class TestAdvanceTickState(unittest.TestCase):
    def test_failure_below_the_cap_counts_and_keeps_prev_now(self):
        self.assertEqual(
            _advance_tick_state(100.0, 1, 130.0, False, 5), (100.0, 2, "continue"))

    def test_success_resets_the_count_and_advances_prev_now(self):
        self.assertEqual(
            _advance_tick_state(100.0, 3, 130.0, True, 5), (130.0, 0, "continue"))

    def test_failure_reaching_the_cap_raises_without_advancing_prev_now(self):
        self.assertEqual(
            _advance_tick_state(100.0, 4, 130.0, False, 5), (100.0, 5, "raise"))

    def test_success_after_failures_covers_the_window_the_failed_tick_missed(self):
        prev_now, failures, _ = _advance_tick_state(100.0, 0, 130.0, False, 5)
        prev_now, failures, _ = _advance_tick_state(prev_now, failures, 160.0, False, 5)
        self.assertEqual(prev_now, 100.0)
        prev_now, failures, _ = _advance_tick_state(prev_now, failures, 190.0, True, 5)
        self.assertEqual((prev_now, failures), (190.0, 0))


if __name__ == "__main__":
    unittest.main()
