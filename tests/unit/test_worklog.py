import datetime
import unittest

from the_grid.domain.worklog import resolve_period, worklog

TODAY = datetime.date(2026, 6, 27)
YESTERDAY = datetime.date(2026, 6, 26)


def story(id="s-1", title="Thing shipped", closed_at="2026-06-27T12:00:00Z",
          outcome="merged", artifacts=None):
    return {"id": id, "title": title, "closed_at": closed_at,
            "outcome": outcome, "artifacts": artifacts or []}


class TestResolvePeriod(unittest.TestCase):
    def test_no_args_returns_today(self):
        self.assertEqual(resolve_period([], TODAY), (TODAY, TODAY))

    def test_today_keyword(self):
        self.assertEqual(resolve_period(["today"], TODAY), (TODAY, TODAY))

    def test_yesterday_keyword(self):
        self.assertEqual(resolve_period(["yesterday"], TODAY), (YESTERDAY, YESTERDAY))

    def test_iso_date_single(self):
        d = datetime.date(2026, 6, 1)
        self.assertEqual(resolve_period(["2026-06-01"], TODAY), (d, d))

    def test_two_iso_dates_inclusive_range(self):
        start = datetime.date(2026, 6, 1)
        end = datetime.date(2026, 6, 30)
        self.assertEqual(resolve_period(["2026-06-01", "2026-06-30"], TODAY), (start, end))

    def test_keywords_in_two_arg_range(self):
        start, end = resolve_period(["yesterday", "today"], TODAY)
        self.assertEqual(start, YESTERDAY)
        self.assertEqual(end, TODAY)

    def test_mixed_keyword_and_iso(self):
        d = datetime.date(2026, 6, 25)
        start, end = resolve_period(["2026-06-25", "today"], TODAY)
        self.assertEqual(start, d)
        self.assertEqual(end, TODAY)


class TestWorklog(unittest.TestCase):
    def test_story_in_range_is_included(self):
        s = story(closed_at="2026-06-27T12:00:00Z")
        result = worklog([s], TODAY, TODAY)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "s-1")
        self.assertEqual(result[0]["title"], "Thing shipped")
        self.assertEqual(result[0]["outcome"], "merged")

    def test_story_before_range_excluded(self):
        s = story(closed_at="2026-06-25T12:00:00Z")
        result = worklog([s], TODAY, TODAY)
        self.assertEqual(result, [])

    def test_story_after_range_excluded(self):
        s = story(closed_at="2026-06-28T12:00:00Z")
        result = worklog([s], TODAY, TODAY)
        self.assertEqual(result, [])

    def test_range_includes_both_bounds(self):
        start = datetime.date(2026, 6, 25)
        end = datetime.date(2026, 6, 27)
        stories = [
            story(id="a", closed_at="2026-06-25T12:00:00Z"),
            story(id="b", closed_at="2026-06-26T12:00:00Z"),
            story(id="c", closed_at="2026-06-27T12:00:00Z"),
            story(id="d", closed_at="2026-06-28T12:00:00Z"),
            story(id="e", closed_at="2026-06-24T12:00:00Z"),
        ]
        result = worklog(stories, start, end)
        ids = [e["id"] for e in result]
        self.assertIn("a", ids)
        self.assertIn("b", ids)
        self.assertIn("c", ids)
        self.assertNotIn("d", ids)
        self.assertNotIn("e", ids)

    def test_pr_artifact_surfaced(self):
        s = story(artifacts=[{"type": "pr", "value": "https://github.com/x/y/pull/1"}])
        result = worklog([s], TODAY, TODAY)
        self.assertEqual(result[0]["pr"], "https://github.com/x/y/pull/1")

    def test_no_pr_artifact_gives_none(self):
        s = story(artifacts=[{"type": "spec", "value": "specs/x.md"}])
        result = worklog([s], TODAY, TODAY)
        self.assertIsNone(result[0]["pr"])

    def test_empty_artifacts_gives_none_pr(self):
        s = story(artifacts=[])
        result = worklog([s], TODAY, TODAY)
        self.assertIsNone(result[0]["pr"])

    def test_story_without_closed_at_skipped(self):
        s = {"id": "s-1", "title": "x", "closed_at": None, "outcome": "merged", "artifacts": []}
        result = worklog([s], TODAY, TODAY)
        self.assertEqual(result, [])

    def test_story_missing_closed_at_key_skipped(self):
        s = {"id": "s-1", "title": "x", "outcome": "merged", "artifacts": []}
        result = worklog([s], TODAY, TODAY)
        self.assertEqual(result, [])

    def test_multiple_stories_in_range(self):
        stories = [
            story(id="a", closed_at="2026-06-27T09:00:00Z"),
            story(id="b", closed_at="2026-06-27T14:00:00Z"),
        ]
        result = worklog(stories, TODAY, TODAY)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
