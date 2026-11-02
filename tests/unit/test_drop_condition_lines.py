import unittest

from lightcycle.domain.work import drop_condition_lines


class TestDropConditionLines(unittest.TestCase):
    def test_drops_only_lines_with_the_prefix_and_keeps_order(self):
        notes = "a\npr-feedback: x (x1, last t)\nb"

        self.assertEqual(drop_condition_lines(notes, "pr-feedback:"), "a\nb")

    def test_a_prefix_inside_a_line_is_kept(self):
        self.assertEqual(drop_condition_lines("see pr-feedback: x", "pr-feedback:"), "see pr-feedback: x")

    def test_empty_or_missing_notes_give_empty(self):
        self.assertEqual(drop_condition_lines("", "p"), "")
        self.assertEqual(drop_condition_lines(None, "p"), "")
