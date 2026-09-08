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

    def test_active_step_elapsed_since_claim_is_claim_to_now(self):
        transitions = [(State.IN_PROGRESS, "2026-01-01T10:00:00")]
        self.assertEqual(
            Duration(transitions).elapsed_since_claim("2026-01-01T10:30:00"),
            datetime.timedelta(minutes=30),
        )

    def test_unclaimed_step_elapsed_since_claim_is_unknown(self):
        transitions = [(State.READY, "2026-01-01T10:00:00")]
        self.assertIsNone(
            Duration(transitions).elapsed_since_claim("2026-01-01T10:30:00")
        )

    def test_finished_step_elapsed_since_claim_is_unknown(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.DONE, "2026-01-01T10:30:00"),
        ]
        self.assertIsNone(
            Duration(transitions).elapsed_since_claim("2026-01-01T12:00:00")
        )

    def test_reworked_step_elapsed_since_claim_is_first_claim_to_now(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.READY, "2026-01-01T10:20:00"),
            (State.IN_PROGRESS, "2026-01-01T11:00:00"),
        ]
        self.assertEqual(
            Duration(transitions).elapsed_since_claim("2026-01-01T11:30:00"),
            datetime.timedelta(hours=1, minutes=30),
        )

    def test_missing_claim_timestamp_elapsed_since_claim_is_unknown(self):
        transitions = [(State.IN_PROGRESS, None)]
        self.assertIsNone(
            Duration(transitions).elapsed_since_claim("2026-01-01T10:30:00")
        )

    def test_single_claim_still_running_elapsed_since_last_claim_is_claim_to_now(self):
        transitions = [(State.IN_PROGRESS, "2026-01-01T10:00:00")]
        self.assertEqual(
            Duration(transitions).elapsed_since_last_claim("2026-01-01T10:24:00"),
            datetime.timedelta(minutes=24),
        )

    def test_single_claim_done_elapsed_since_last_claim_is_claim_to_finished(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.DONE, "2026-01-01T10:30:00"),
        ]
        self.assertEqual(
            Duration(transitions).elapsed_since_last_claim("2026-01-01T12:00:00"),
            datetime.timedelta(minutes=30),
        )

    def test_released_and_reclaimed_still_running_elapsed_since_last_claim_is_since_second_claim(
        self,
    ):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.READY, "2026-01-01T10:20:00"),
            (State.IN_PROGRESS, "2026-01-01T11:00:00"),
        ]
        self.assertEqual(
            Duration(transitions).elapsed_since_last_claim("2026-01-01T11:24:00"),
            datetime.timedelta(minutes=24),
        )

    def test_released_and_reclaimed_done_elapsed_since_last_claim_is_since_second_claim(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.READY, "2026-01-01T10:20:00"),
            (State.IN_PROGRESS, "2026-01-01T11:00:00"),
            (State.DONE, "2026-01-01T11:30:00"),
        ]
        self.assertEqual(
            Duration(transitions).elapsed_since_last_claim("2026-01-01T12:00:00"),
            datetime.timedelta(minutes=30),
        )

    def test_no_claim_elapsed_since_last_claim_is_unknown(self):
        transitions = [(State.READY, "2026-01-01T10:00:00")]
        self.assertIsNone(
            Duration(transitions).elapsed_since_last_claim("2026-01-01T10:30:00")
        )

    def test_reopened_history_falls_through_to_still_running(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.DONE, "2026-01-01T10:30:00"),
            (State.IN_PROGRESS, "2026-01-01T11:00:00"),
        ]
        self.assertEqual(
            Duration(transitions).elapsed_since_last_claim("2026-01-01T11:10:00"),
            datetime.timedelta(minutes=10),
        )

    def test_last_release_returns_the_park_transition(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.READY, "2026-01-01T10:20:00"),
        ]
        self.assertEqual(Duration(transitions).last_release(), "2026-01-01T10:20:00")

    def test_last_release_returns_the_most_recent_of_two_parks(self):
        transitions = [
            (State.IN_PROGRESS, "2026-01-01T10:00:00"),
            (State.READY, "2026-01-01T10:20:00"),
            (State.IN_PROGRESS, "2026-01-01T11:00:00"),
            (State.READY, "2026-01-01T11:20:00"),
        ]
        self.assertEqual(Duration(transitions).last_release(), "2026-01-01T11:20:00")

    def test_last_release_is_none_without_a_ready_transition(self):
        transitions = [(State.IN_PROGRESS, "2026-01-01T10:00:00")]
        self.assertIsNone(Duration(transitions).last_release())


if __name__ == "__main__":
    unittest.main()
