import datetime
import unittest

from the_grid.domain.feedback import Period, Worklog
from the_grid.domain.work import Artifact

TODAY = datetime.date(2026, 6, 27)
YESTERDAY = datetime.date(2026, 6, 26)
UTC = datetime.timezone.utc


def story(
    id="s-1",
    title="Thing shipped",
    closed_at="2026-06-27T12:00:00Z",
    outcome="merged",
    artifacts=None,
):
    return {
        "id": id,
        "title": title,
        "closed_at": closed_at,
        "outcome": outcome,
        "artifacts": artifacts or [],
    }


def entries(stories, start, end):
    return Worklog(stories).entries(Period(start, end), UTC)


class TestPeriod(unittest.TestCase):
    def _bounds(self, *args):
        p = Period.resolve(list(args), TODAY)
        return (p.start, p.end)

    def test_no_args_returns_today(self):
        self.assertEqual(self._bounds(), (TODAY, TODAY))

    def test_today_keyword(self):
        self.assertEqual(self._bounds("today"), (TODAY, TODAY))

    def test_yesterday_keyword(self):
        self.assertEqual(self._bounds("yesterday"), (YESTERDAY, YESTERDAY))

    def test_iso_date_single(self):
        d = datetime.date(2026, 6, 1)
        self.assertEqual(self._bounds("2026-06-01"), (d, d))

    def test_two_iso_dates_inclusive_range(self):
        self.assertEqual(
            self._bounds("2026-06-01", "2026-06-30"),
            (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30)),
        )

    def test_keywords_in_two_arg_range(self):
        self.assertEqual(self._bounds("yesterday", "today"), (YESTERDAY, TODAY))

    def test_mixed_keyword_and_iso(self):
        self.assertEqual(self._bounds("2026-06-25", "today"), (datetime.date(2026, 6, 25), TODAY))


class TestWorklog(unittest.TestCase):
    def test_story_in_range_is_included(self):
        result = entries([story(closed_at="2026-06-27T12:00:00Z")], TODAY, TODAY)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "s-1")
        self.assertEqual(result[0]["title"], "Thing shipped")
        self.assertEqual(result[0]["outcome"], "merged")

    def test_story_before_range_excluded(self):
        self.assertEqual(entries([story(closed_at="2026-06-25T12:00:00Z")], TODAY, TODAY), [])

    def test_story_after_range_excluded(self):
        self.assertEqual(entries([story(closed_at="2026-06-28T12:00:00Z")], TODAY, TODAY), [])

    def test_range_includes_both_bounds(self):
        stories = [
            story(id="a", closed_at="2026-06-25T12:00:00Z"),
            story(id="b", closed_at="2026-06-26T12:00:00Z"),
            story(id="c", closed_at="2026-06-27T12:00:00Z"),
            story(id="d", closed_at="2026-06-28T12:00:00Z"),
            story(id="e", closed_at="2026-06-24T12:00:00Z"),
        ]
        ids = [
            e["id"]
            for e in entries(stories, datetime.date(2026, 6, 25), datetime.date(2026, 6, 27))
        ]
        self.assertEqual(ids, ["a", "b", "c"])

    def test_pr_artifact_surfaced(self):
        s = story(artifacts=[Artifact(type="pr", value="https://github.com/x/y/pull/1")])
        self.assertEqual(entries([s], TODAY, TODAY)[0]["pr"], "https://github.com/x/y/pull/1")

    def test_no_pr_artifact_gives_none(self):
        s = story(artifacts=[Artifact(type="spec", value="specs/x.md")])
        self.assertIsNone(entries([s], TODAY, TODAY)[0]["pr"])

    def test_empty_artifacts_gives_none_pr(self):
        self.assertIsNone(entries([story(artifacts=[])], TODAY, TODAY)[0]["pr"])

    def test_story_without_closed_at_skipped(self):
        s = {"id": "s-1", "title": "x", "closed_at": None, "outcome": "merged", "artifacts": []}
        self.assertEqual(entries([s], TODAY, TODAY), [])

    def test_story_missing_closed_at_key_skipped(self):
        s = {"id": "s-1", "title": "x", "outcome": "merged", "artifacts": []}
        self.assertEqual(entries([s], TODAY, TODAY), [])

    def test_multiple_stories_in_range(self):
        stories = [
            story(id="a", closed_at="2026-06-27T09:00:00Z"),
            story(id="b", closed_at="2026-06-27T14:00:00Z"),
        ]
        self.assertEqual(len(entries(stories, TODAY, TODAY)), 2)


if __name__ == "__main__":
    unittest.main()
