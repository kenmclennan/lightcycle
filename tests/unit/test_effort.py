import unittest

from lightcycle.domain.work.effort import EFFORT_LEVELS, effort_problem


class TestEffortProblem(unittest.TestCase):
    def test_every_level_is_valid(self):
        for level in EFFORT_LEVELS:
            self.assertIsNone(effort_problem(level))

    def test_anything_else_names_the_value(self):
        for bad in ("extreme", "", "Low"):
            self.assertIn(repr(bad), effort_problem(bad))
