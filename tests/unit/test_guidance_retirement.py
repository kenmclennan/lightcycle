import datetime
import unittest

from lightcycle.domain.guidance.guidance import GuidanceEntry
from lightcycle.domain.guidance.retirement import (
    APPROVAL_KNOWN, APPROVAL_NONE, APPROVAL_UNKNOWN, COVERS_UNKNOWN, Approval, CoversResult,
    Flag, GuidanceRow, Thresholds, Usage, build_rows, evaluate, pr_number,
)

NOW = datetime.datetime(2026, 10, 13, 12, 0, 0, tzinfo=datetime.timezone.utc)
T = Thresholds(unused_after_deliveries=60, dormant_days=60)


def _entry(id="a/x", status="stable", **kw):
    return GuidanceEntry(
        id=id, status=status, verified="", facets=(), steps=(), body="b", **kw)


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
        self.assertEqual(row.flags[0].evidence, "never delivered")
        self.assertEqual(row.notes, ("add date unreadable, so age is not taken into account",))

    def test_added_long_ago_names_the_age_in_days_as_evidence(self):
        row = evaluate(_entry(), Usage(), T, NOW, added=_ago(days=61))
        self.assertEqual(row.flags[0].evidence, "never delivered in 61 days")

    def test_last_delivery_long_ago_names_the_age_and_the_limit_as_evidence(self):
        row = evaluate(_entry(), Usage(1, 1, _ago(days=75)), T, NOW)
        self.assertEqual(row.flags[0].evidence, "last delivered 75 days ago, more than 60")

    def test_a_naive_timestamp_is_read_as_local_time(self):
        naive = (NOW - datetime.timedelta(days=75)).astimezone().replace(tzinfo=None).isoformat()
        row = evaluate(_entry(), Usage(1, 1, naive), T, NOW)
        self.assertEqual(_names(row), ["never-delivered"])
        self.assertEqual(row.flags[0].evidence, "last delivered 75 days ago, more than 60")

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

    def test_a_date_that_parses_but_is_not_ten_characters_adds_the_same_note(self):
        row = self._row("20261001")
        self.assertEqual(_names(row), [])
        self.assertEqual(row.notes, ("stale_after is not a YYYY-MM-DD date",))

    def test_the_flag_quotes_the_date_that_passed(self):
        row = self._row("2000-01-01")
        self.assertEqual(row.flags[0].evidence, "stale_after 2000-01-01 has passed")


class TestCovers(unittest.TestCase):
    def test_closed_flags_with_evidence(self):
        row = evaluate(
            _entry(covers="https://github.com/x/y/issues/1"), Usage(1, 1, _ago(days=1)), T, NOW,
            CoversResult("CLOSED"))
        self.assertEqual(_names(row), ["covers-closed"])
        self.assertIn("closed upstream: https://github.com/x/y/issues/1", row.flags[0].evidence)
        self.assertIn("only once the fix is installed locally", row.flags[0].evidence)
        self.assertEqual(
            row.flags[0].evidence,
            "closed upstream: https://github.com/x/y/issues/1;"
            " remove only once the fix is installed locally")

    def test_a_covers_entry_with_no_result_yet_is_left_alone(self):
        row = evaluate(_entry(covers="x"), Usage(1, 1, _ago(days=1)), T, NOW)
        self.assertEqual((_names(row), row.notes), ([], ()))

    def test_a_result_for_an_entry_that_covers_nothing_is_ignored(self):
        row = evaluate(_entry(), Usage(1, 1, _ago(days=1)), T, NOW, CoversResult("CLOSED"))
        self.assertEqual((_names(row), row.notes), ([], ()))

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

    def test_deprecated_row_keeps_its_status_and_usage_figures(self):
        last = _ago(days=3)
        row = evaluate(_entry(id="a/old", status="deprecated"), Usage(7, 2, last), T, NOW)
        self.assertEqual(
            (row.id, row.status, row.deliveries, row.citations, row.last_delivered, row.opportunity),
            ("a/old", "deprecated", 7, 2, last, 0))

    def test_evaluated_row_keeps_its_status_and_usage_figures(self):
        last = _ago(days=3)
        row = evaluate(_entry(id="a/live"), Usage(7, 2, last), T, NOW)
        self.assertEqual(
            (row.id, row.status, row.deliveries, row.citations, row.last_delivered, row.opportunity),
            ("a/live", "stable", 7, 2, last, 0))

    def test_opportunity_is_passed_through_to_the_row(self):
        row = evaluate(_entry(), Usage(1, 1, _ago(days=1)), T, NOW, opportunity=5)
        self.assertEqual(row.opportunity, 5)

    def test_build_rows_defaults_a_missing_usage_and_opportunity_to_zero(self):
        (row,) = build_rows([_entry(id="a/x", status="draft")], {}, T, NOW)
        self.assertEqual((row.deliveries, row.citations, row.opportunity), (0, 0, 0))

    def test_build_rows_looks_opportunity_up_by_entry_id(self):
        rows = build_rows(
            [_entry(id="a/x", status="draft"), _entry(id="a/y", status="draft")],
            {}, T, NOW, opportunity_by_id={"a/y": 4})
        self.assertEqual([(r.id, r.opportunity) for r in rows], [("a/x", 0), ("a/y", 4)])

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


class TestApprovalAndDict(unittest.TestCase):
    def test_flag_as_dict(self):
        self.assertEqual(Flag("unused", "why").as_dict(), {"name": "unused", "evidence": "why"})

    def test_pr_number_reads_the_trailing_suffix_only(self):
        self.assertEqual(pr_number("fix thing (#123)"), "123")
        self.assertEqual(pr_number("fix (#1) thing"), "")
        self.assertEqual(pr_number(None), "")

    def test_from_git_states(self):
        self.assertEqual(Approval.from_git(None), Approval(APPROVAL_UNKNOWN))
        self.assertEqual(Approval.from_git(()), Approval(APPROVAL_NONE))
        known = Approval.from_git(("abc", "2026-10-01", "land it (#9)"))
        self.assertEqual(
            (known.state, known.sha, known.date, known.subject, known.pr),
            (APPROVAL_KNOWN, "abc", "2026-10-01", "land it (#9)", "9"))

    def test_row_as_dict_carries_every_field(self):
        row = GuidanceRow(
            "a/x", "stable", 3, 1, "2026-10-01", (Flag("stale", "e"),), ("n",), 2,
            Approval(APPROVAL_KNOWN, "abc", "2026-09-01", "s (#4)", "4"), "2026-08-01")
        self.assertEqual(row.as_dict(), {
            "id": "a/x", "status": "stable", "deliveries": 3, "citations": 1,
            "opportunity": 2, "last_delivered": "2026-10-01",
            "flags": [{"name": "stale", "evidence": "e"}], "notes": ["n"],
            "approval": {
                "state": "known", "sha": "abc", "date": "2026-09-01", "subject": "s (#4)",
                "pr": "4", "verified": "2026-08-01"},
        })

    def test_build_rows_attaches_approval_and_verified_to_each_row(self):
        entry = GuidanceEntry(
            id="a/x", status="draft", verified="2026-08-01", facets=(), steps=(), body="b")
        approval = Approval(APPROVAL_KNOWN, "abc", "2026-09-01", "s (#4)", "4")
        (row,) = build_rows([entry], {}, T, NOW, approvals={"a/x": approval})
        self.assertEqual((row.approval, row.verified), (approval, "2026-08-01"))


if __name__ == "__main__":
    unittest.main()
