import unittest

from lightcycle.cli import _tick_failure_action


class TestTickFailureAction(unittest.TestCase):
    def test_continues_below_the_cap(self):
        self.assertEqual(_tick_failure_action(1, 5), "continue")
        self.assertEqual(_tick_failure_action(4, 5), "continue")

    def test_raises_at_the_cap(self):
        self.assertEqual(_tick_failure_action(5, 5), "raise")

    def test_raises_beyond_the_cap(self):
        self.assertEqual(_tick_failure_action(6, 5), "raise")


if __name__ == "__main__":
    unittest.main()
