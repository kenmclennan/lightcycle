import datetime
import unittest

from lightcycle.domain.work.callout_runs import CLEANUP_WINDOW_SECONDS, cleanup_due

NOW = 1_800_000_000.0


def iso(seconds_before_now):
    return datetime.datetime.fromtimestamp(
        NOW - seconds_before_now, datetime.timezone.utc).isoformat()


def record(**overrides):
    base = {"status": "ok", "phase": "run", "subject": {"kind": "pr", "url": "u"}}
    base.update(overrides)
    return base


class TestCleanupDue(unittest.TestCase):
    def test_each_row_of_the_eligibility_table(self):
        rows = [
            ("ok run", iso(60), record(), True),
            ("failed run", iso(60), record(status="failed"), True),
            ("absent phase means run", iso(60), {"status": "ok", "subject": {"k": 1}}, True),
            ("running", iso(60), record(status="running"), False),
            ("preflight", iso(60), record(phase="preflight", status="failed"), False),
            ("no subject", iso(60), record(subject=None), False),
            ("old record without the key", iso(60), {"status": "ok", "phase": "run"}, False),
            ("already cleaned", iso(60), record(cleanup={"status": "ok"}), False),
            ("exactly seven days", iso(CLEANUP_WINDOW_SECONDS), record(), True),
            ("seven days and a second", iso(CLEANUP_WINDOW_SECONDS + 1), record(), False),
            ("null closed_at", None, record(), False),
            ("unparsable closed_at", "not a time", record(), False),
            ("not a dict", iso(60), "x", False),
        ]
        for name, closed_at, rec, expected in rows:
            self.assertEqual(cleanup_due(closed_at, rec, NOW), expected, name)
