import datetime
import unittest

from lightcycle.domain.guidance.guidance import GuidanceEntry
from lightcycle.domain.guidance.retirement import (
    COVERS_UNKNOWN, CoversResult, Thresholds, Usage, build_rows, evaluate,
)

NOW = datetime.datetime(2026, 10, 13, 12, 0, 0, tzinfo=datetime.timezone.utc)
T = Thresholds(unused_after_deliveries=60, dormant_days=60)


def _entry(id="a/x", status="stable", **kw):
    return GuidanceEntry(
        id=id, status=status, verified=True, facets=(), steps=(), body="b", **kw)


def _names(row):
    return [f.name for f in row.flags]


def _ago(**kw):
    return (NOW - datetime.timedelta(**kw)).isoformat()


class TestUnused(unittest.TestCase):
    def test_one_below_threshold_has_no_flag_and_a_note(self):
        row = evaluate(_entry(), Usage(59, 0, _ago(days=1)), T, NOW)
        self.assertEqual(_names(row), [])
        self.assertEqual(row.notes, ("too few deliveries to judge (59 of 60 needed)",))

    def test_at_threshold_flags_with_counts_as_evidence(self):
        row = evaluate(_entry(), Usage(60, 0, _ago(days=1)), T, NOW)
        self.assertEqual(_names(row), ["unused"])
        self.assertEqual(row.flags[0].evidence, "60 deliveries, 0 cited")
        self.assertEqual(row.notes, ())

    def test_one_citation_clears_it(self):
        row = evaluate(_entry(), Usage(60, 1, _ago(days=1)), T, NOW)
        self.assertEqual(_names(row), [])
        self.assertEqual(row.notes, ())

    def test_above_threshold_flags(self):
        row = evaluate(_entry(), Usage(61, 0, _ago(days=1)), T, NOW)
        self.assertEqual(_names(row), ["unused"])


class TestNeverDelivered(unittest.TestCase):
    def test_exactly_the_dormant_age_does_not_flag(self):
        row = evaluate(_entry(), Usage(1, 1, _ago(days=60)), T, NOW)
        self.assertEqual(_names(row), [])

    def test_one_second_older_flags(self):
        row = evaluate(_entry(), Usage(1, 1, _ago(days=60, seconds=1)), T, NOW)
        self.assertEqual(_names(row), ["never-delivered"])

    def test_younger_does_not_flag(self):
        row = evaluate(_entry(), Usage(1, 1, _ago(days=59)), T, NOW)
        self.assertEqual(_names(row), [])

    def test_never_delivered_added_before_the_dormant_age_flags(self):
        row = evaluate(_entry(), Usage(), T, NOW, added=_ago(days=60, seconds=1))
        self.assertEqual(_names(row), ["never-delivered"])
        self.assertEqual(row.notes, ())

    def test_never_delivered_added_exactly_the_dormant_age_ago_does_not_flag(self):
        row = evaluate(_entry(), Usage(), T, NOW, added=_ago(days=60))
        self.assertEqual(_names(row), [])
        self.assertEqual(row.notes, ("new - 60 of 60 days old",))

    def test_never_delivered_added_recently_carries_the_note_and_no_flag(self):
        row = evaluate(_entry(), Usage(), T, NOW, added=_ago(days=3))
        self.assertEqual(_names(row), [])
        self.assertEqual(row.notes, ("new - 3 of 60 days old",))

    def test_never_delivered_with_unreadable_add_date_flags_and_says_so(self):
        row = evaluate(_entry(), Usage(), T, NOW)
        self.assertEqual(_names(row), ["never-delivered"])
        self.assertEqual(len(row.notes), 1)
        self.assertIn("add date unreadable", row.notes[0])

    def test_delivered_entry_ignores_the_add_date(self):
        row = evaluate(_entry(), Usage(1, 1, _ago(days=1)), T, NOW, added=_ago(days=3))
        self.assertEqual(_names(row), [])
        self.assertEqual(row.notes, ())

    def test_stable_never_delivered_flags(self):
        row = evaluate(_entry(), Usage(), T, NOW)
        self.assertEqual(_names(row), ["never-delivered"])

    def test_draft_never_delivered_does_not_flag(self):
        row = evaluate(_entry(status="draft"), Usage(), T, NOW)
        self.assertEqual(_names(row), [])


class TestStale(unittest.TestCase):
    def _row(self, value):
        return evaluate(_entry(stale_after=value, status="draft"), Usage(), T, NOW)

    def test_yesterday_flags(self):
        yesterday = (NOW.astimezone().date() - datetime.timedelta(days=1)).isoformat()
        self.assertEqual(_names(self._row(yesterday)), ["stale"])

    def test_today_does_not_flag(self):
        self.assertEqual(_names(self._row(NOW.astimezone().date().isoformat())), [])

    def test_tomorrow_does_not_flag(self):
        tomorrow = (NOW.astimezone().date() + datetime.timedelta(days=1)).isoformat()
        self.assertEqual(_names(self._row(tomorrow)), [])

    def test_unparseable_adds_a_note_and_no_flag(self):
        row = self._row("not-a-date")
        self.assertEqual(_names(row), [])
        self.assertEqual(row.notes, ("stale_after is not a YYYY-MM-DD date",))


class TestCovers(unittest.TestCase):
    def test_closed_flags_with_evidence(self):
        row = evaluate(
            _entry(covers="https://github.com/x/y/issues/1"), Usage(1, 1, _ago(days=1)), T, NOW,
            CoversResult("CLOSED"))
        self.assertEqual(_names(row), ["covers-closed"])
        self.assertIn("closed upstream: https://github.com/x/y/issues/1", row.flags[0].evidence)
        self.assertIn("only once the fix is installed locally", row.flags[0].evidence)

    def test_unknown_carries_its_note_and_no_flag(self):
        row = evaluate(
            _entry(covers="x"), Usage(1, 1, _ago(days=1)), T, NOW,
            CoversResult(COVERS_UNKNOWN, "why"))
        self.assertEqual(_names(row), [])
        self.assertEqual(row.notes, ("why",))


class TestDeprecatedAndOrder(unittest.TestCase):
    def test_deprecated_with_every_condition_true_has_no_flags(self):
        e = _entry(status="deprecated", covers="c", stale_after="2000-01-01")
        row = evaluate(e, Usage(100, 0, _ago(days=500)), T, NOW, CoversResult("CLOSED"))
        self.assertEqual(row.flags, ())
        self.assertEqual(row.notes, ())

    def test_flagged_sorts_before_unflagged_with_earlier_id(self):
        clean = _entry(id="a/clean")
        flagged = _entry(id="z/flagged")
        usage = {"a/clean": Usage(1, 1, _ago(days=1)), "z/flagged": Usage(60, 0, _ago(days=1))}
        rows = build_rows([clean, flagged], usage, T, NOW)
        self.assertEqual([r.id for r in rows], ["z/flagged", "a/clean"])

    def test_flag_order_follows_the_rule_order(self):
        e = _entry(covers="c", stale_after="2000-01-01")
        row = evaluate(e, Usage(60, 0, _ago(days=100)), T, NOW, CoversResult("CLOSED"))
        self.assertEqual(_names(row), ["unused", "never-delivered", "covers-closed", "stale"])


if __name__ == "__main__":
    unittest.main()
