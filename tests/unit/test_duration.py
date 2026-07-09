import datetime
import unittest

from lightcycle.domain.feedback import Duration
from lightcycle.domain.work import State


class TestDuration(unittest.TestCase):
    def test_single_pass_elapsed_is_claim_to_done(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.DONE, "2026-01-01T10:30:00"),
        ]
        self.assertEqual(
            Duration(transitions).elapsed(), datetime.timedelta(minutes=30)
        )

    def test_rework_elapsed_is_wall_clock_first_claim_to_final_done(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.READY, "2026-01-01T10:20:00"),
            (State.IN_PROGRESS, "2026-01-01T11:00:00"),
            (State.DONE, "2026-01-01T12:00:00"),
        ]
        self.assertEqual(
            Duration(transitions).elapsed(), datetime.timedelta(hours=2)
        )

    def test_missing_claim_timestamp_is_unknown(self):
        transitions = [
            (State.IN_PROGRESS, None),
            (State.DONE, "2026-01-01T10:30:00"),
        ]
        self.assertIsNone(Duration(transitions).elapsed())

    def test_missing_done_timestamp_is_unknown(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.DONE, None),
        ]
        self.assertIsNone(Duration(transitions).elapsed())

    def test_no_claim_transition_is_unknown(self):
        transitions = [(State.DONE, "2026-01-01T10:30:00")]
        self.assertIsNone(Duration(transitions).elapsed())

    def test_no_done_transition_is_unknown(self):
        transitions = [(State.IN_PROGRESS, "2026-01-01T10:00:00")]
        self.assertIsNone(Duration(transitions).elapsed())

    def test_empty_transitions_is_unknown(self):
        self.assertIsNone(Duration([]).elapsed())


if __name__ == "__main__":
    unittest.main()
