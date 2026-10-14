import unittest

from lightcycle.domain.feedback import ADMIT, HOLD, can_transition, standing


class TestStanding(unittest.TestCase):
    def test_a_trusted_human_is_admitted(self):
        self.assertEqual(standing("alice", {"alice"}, []), ADMIT)

    def test_an_allowlisted_bot_is_admitted(self):
        self.assertEqual(standing("copilot[bot]", set(), ["copilot[bot]"]), ADMIT)

    def test_a_bot_off_the_allowlist_is_held(self):
        self.assertEqual(standing("copilot[bot]", {"alice"}, []), HOLD)

    def test_an_untrusted_human_is_held(self):
        self.assertEqual(standing("mallory", {"alice"}, ["copilot[bot]"]), HOLD)

    def test_casing_does_not_matter(self):
        self.assertEqual(standing("Alice", {"alice"}, []), ADMIT)
        self.assertEqual(standing("alice", {"Alice"}, []), ADMIT)

    def test_empty_sets_hold_everyone(self):
        self.assertEqual(standing("alice", set(), []), HOLD)


class TestTransitions(unittest.TestCase):
    def test_only_the_documented_transitions_are_legal(self):
        self.assertTrue(can_transition("held", "approved"))
        self.assertTrue(can_transition("held", "rejected"))
        self.assertTrue(can_transition("approved", "dispatched"))
        self.assertFalse(can_transition("held", "dispatched"))
        self.assertFalse(can_transition("rejected", "approved"))
        self.assertFalse(can_transition("dispatched", "held"))
        self.assertFalse(can_transition("approved", "rejected"))
