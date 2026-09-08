import unittest

from lightcycle.domain.work.active_time import item_active_seconds


class _FakeStep:
    def __init__(self, active_seconds=None):
        self.active_seconds = active_seconds


class TestItemActiveSeconds(unittest.TestCase):
    def test_zero_for_an_empty_list(self):
        self.assertEqual(item_active_seconds([]), 0)

    def test_zero_for_steps_whose_active_seconds_is_none(self):
        steps = [_FakeStep(active_seconds=None), _FakeStep(active_seconds=None)]
        self.assertEqual(item_active_seconds(steps), 0)

    def test_sums_active_seconds_across_multiple_steps(self):
        steps = [_FakeStep(active_seconds=300), _FakeStep(active_seconds=540)]
        self.assertEqual(item_active_seconds(steps), 840)
