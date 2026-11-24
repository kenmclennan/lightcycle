import datetime
import unittest

from lightcycle.domain.work import StepSession, session_separator

UTC = datetime.timezone.utc
STARTED = "2026-11-24T17:05:09+00:00"


class TestSessionSeparator(unittest.TestCase):
    def _sep(self, reason, started=STARTED):
        return session_separator(StepSession(2, "/l/b.log", started, None), 2, reason, local_zone=UTC)

    def test_each_known_reason_reads_in_words(self):
        expected = {
            "stalled": "stalled, killed by the pool",
            "pool-stopped": "the pool stopped",
            "died": "the worker process died",
            "reclaimed": "the claim was reclaimed",
            "claim-failed": "the claim failed",
        }
        for reason, text in expected.items():
            self.assertEqual(
                self._sep(reason),
                "--- session 2 of 2 - started 17:05:09 - previous session ended: %s ---" % text)

    def test_a_missing_or_unrecognised_reason_reads_unknown(self):
        for reason in (None, "exploded"):
            self.assertEqual(
                self._sep(reason),
                "--- session 2 of 2 - started 17:05:09 - previous session ended: unknown ---")

    def test_a_missing_start_omits_the_started_clause(self):
        self.assertEqual(
            self._sep("died", started=None),
            "--- session 2 of 2 - previous session ended: the worker process died ---")

    def test_the_start_is_shown_in_the_given_zone(self):
        zone = datetime.timezone(datetime.timedelta(hours=2))
        text = session_separator(StepSession(2, "/l", STARTED, None), 2, None, local_zone=zone)
        self.assertIn("started 19:05:09", text)
