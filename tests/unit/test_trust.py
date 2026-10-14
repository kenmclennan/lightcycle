import unittest

from lightcycle.domain.feedback import ADMIT, HOLD, can_transition, standing


_BOT = "copilot-pull-request-reviewer[bot]"


class TestStanding(unittest.TestCase):
    def test_a_trusted_human_is_admitted(self):
        self.assertEqual(standing("alice", {"alice"}), ADMIT)

    def test_a_bot_in_trusted_is_admitted(self):
        self.assertEqual(standing(_BOT, {_BOT}), ADMIT)

    def test_a_bot_not_in_trusted_is_held(self):
        self.assertEqual(standing(_BOT, {"alice"}), HOLD)
        self.assertEqual(standing(_BOT, set()), HOLD)

    def test_an_untrusted_human_is_held(self):
        self.assertEqual(standing("mallory", {"alice", _BOT}), HOLD)

    def test_casing_does_not_matter(self):
        self.assertEqual(standing("Alice", {"alice"}), ADMIT)
        self.assertEqual(standing("alice", {"Alice"}), ADMIT)
        self.assertEqual(standing(_BOT.title(), {_BOT}), ADMIT)
        self.assertEqual(standing(_BOT, {_BOT.title()}), ADMIT)

    def test_empty_sets_hold_everyone(self):
        self.assertEqual(standing("alice", set()), HOLD)


class TestTransitions(unittest.TestCase):
    def test_only_the_documented_transitions_are_legal(self):
        self.assertTrue(can_transition("held", "approved"))
        self.assertTrue(can_transition("held", "rejected"))
        self.assertTrue(can_transition("approved", "dispatched"))
        self.assertFalse(can_transition("held", "dispatched"))
        self.assertFalse(can_transition("rejected", "approved"))
        self.assertFalse(can_transition("dispatched", "held"))
        self.assertFalse(can_transition("approved", "rejected"))
