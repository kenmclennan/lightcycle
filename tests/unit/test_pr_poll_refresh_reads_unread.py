import dataclasses
import unittest

from tests.unit.test_pr_feedback_conditions import _FIRST, _SECOND, _Rig, _mention

_READS = ("last_push_time", "comments_since", "pull_comments", "reviews")


class _LaggedRig(_Rig):
    def __init__(self, prs, **fake):
        super().__init__(prs, **fake)
        self.lag = {}
        listed = self.github.list_prs

        def lagging(repo, cutoff):
            rows = listed(repo, 0.0)
            if isinstance(rows, tuple):
                rows = tuple(
                    dataclasses.replace(r, updated_at=self.lag.get(r.url, r.updated_at))
                    for r in rows)
            return rows

        self.github.list_prs = lagging

    def step(self, *prs, refresh_polls=10):
        for pr in prs:
            self.snapshot.head_sha(pr)
        self.now += 60.0
        wanted = self.snapshot.take_wanted()
        self.poll.run(wanted, self.now, refresh_polls)
        return wanted

    def calls_named(self, name, pr):
        return [c for c in self.github.calls if c[:2] == (name, pr)]

    def post_comment_behind_the_listing(self, pr, listed_at=100.0, true_at=150.0):
        self.github._timed_comments.append(_mention(1500.0))
        self.github.touch(pr, true_at)
        self.lag[pr] = listed_at


def _rig(prs=(_FIRST,), **fake):
    rig = _LaggedRig(prs, **fake)
    rig.github._updated_ats.update({pr: 100.0 for pr in prs})
    return rig


class _Base(unittest.TestCase):
    def _dispatched(self, rig, item):
        rig.dispatch.execute()
        return len(rig.feedback_steps(item))


class TestARefreshReadsActivityTheListingHidden(_Base):
    def test_an_unsettled_view_refresh_reads_a_comment_the_listing_lagged_behind(self):
        rig = _rig()
        rig.github.leave_unsettled(_FIRST, 3)
        item, _ = rig.gate(_FIRST)
        rig.step(_FIRST)
        rig.step(_FIRST)
        rig.post_comment_behind_the_listing(_FIRST)

        rig.step(_FIRST)

        self.assertEqual(self._dispatched(rig, item), 1)

    def test_a_periodic_refresh_reads_a_comment_the_listing_lagged_behind(self):
        rig = _rig()
        item, _ = rig.gate(_FIRST)
        rig.step(_FIRST, refresh_polls=1)
        rig.step(_FIRST, refresh_polls=1)
        rig.post_comment_behind_the_listing(_FIRST)

        rig.step(_FIRST, refresh_polls=1)

        self.assertEqual(self._dispatched(rig, item), 1)

    def test_a_base_moved_refresh_reads_a_comment_the_listing_lagged_behind(self):
        rig = _rig()
        item, _ = rig.gate(_FIRST)
        rig.step(_FIRST, refresh_polls=1000003)
        rig.step(_FIRST, refresh_polls=1000003)
        rig.post_comment_behind_the_listing(_FIRST)
        rig.github.advance_base("acme/code", "main")

        rig.step(_FIRST, refresh_polls=1000003)

        self.assertEqual(self._dispatched(rig, item), 1)
        self.assertEqual(rig.snapshot.entry_of(_FIRST).updated_at, 150.0)


class TestARefreshReadBudget(_Base):
    def _settled(self):
        rig = _rig()
        rig.step(_FIRST, refresh_polls=1)
        rig.step(_FIRST, refresh_polls=1)
        return rig

    def _count(self, rig, name):
        return len(rig.calls_named(name, _FIRST))

    def test_a_view_equal_to_the_entry_makes_no_full_read(self):
        rig = self._settled()
        before = {n: self._count(rig, n) for n in _READS + ("pr_view",)}

        rig.step(_FIRST, refresh_polls=1)

        for name in _READS:
            self.assertEqual(self._count(rig, name), before[name], name)
        self.assertEqual(self._count(rig, "pr_view"), before["pr_view"] + 1)

    def test_a_view_one_tick_ahead_makes_one_of_each_read_and_one_view(self):
        rig = self._settled()
        before = {n: self._count(rig, n) for n in _READS + ("pr_view",)}
        rig.github.touch(_FIRST, 101.0)
        rig.lag[_FIRST] = 100.0

        rig.step(_FIRST, refresh_polls=1)

        for name in _READS + ("pr_view",):
            self.assertEqual(self._count(rig, name), before[name] + 1, name)
        self.assertEqual(rig.snapshot.entry_of(_FIRST).updated_at, 101.0)

    def test_a_view_older_than_the_entry_leaves_the_entry_updated_at_alone(self):
        rig = self._settled()
        rig.github.touch(_FIRST, 150.0)
        rig.step(_FIRST, refresh_polls=1)
        self.assertEqual(rig.snapshot.entry_of(_FIRST).updated_at, 150.0)
        rig.github.touch(_FIRST, 120.0)
        rig.lag[_FIRST] = 150.0
        before = {n: self._count(rig, n) for n in _READS}

        rig.step(_FIRST, refresh_polls=1)

        self.assertEqual(rig.snapshot.entry_of(_FIRST).updated_at, 150.0)
        for name in _READS:
            self.assertEqual(self._count(rig, name), before[name], name)

    def test_a_failed_full_read_marks_the_entry_stale_and_is_retried(self):
        rig = self._settled()
        item, _ = rig.gate(_FIRST)
        rig.post_comment_behind_the_listing(_FIRST)
        rig.github._failing_calls.add("comments_since")

        wanted = rig.step(_FIRST, refresh_polls=1)

        self.assertTrue(rig.snapshot.is_stale(_FIRST))
        self.assertFalse(rig.snapshot.confirmed_after(_FIRST, wanted.epoch - 1))
        rig.github._failing_calls.discard("comments_since")
        rig.step(_FIRST, refresh_polls=1)
        self.assertFalse(rig.snapshot.is_stale(_FIRST))
        self.assertEqual(self._dispatched(rig, item), 1)

    def test_only_the_pr_whose_view_is_ahead_is_read_in_full(self):
        rig = _rig([_FIRST, _SECOND])
        rig.step(_FIRST, _SECOND, refresh_polls=1)
        rig.step(_FIRST, _SECOND, refresh_polls=1)
        second_before = len(rig.calls_named("comments_since", _SECOND))
        first_before = len(rig.calls_named("comments_since", _FIRST))
        rig.github._timed_comments.append(_mention(1500.0))
        rig.github.touch(_FIRST, 150.0)
        rig.lag[_FIRST] = 100.0

        rig.step(_FIRST, _SECOND, refresh_polls=1)

        self.assertEqual(len(rig.calls_named("comments_since", _FIRST)), first_before + 1)
        self.assertEqual(len(rig.calls_named("comments_since", _SECOND)), second_before)
        self.assertEqual(len(rig.snapshot.entry_of(_FIRST).comments), 1)


if __name__ == "__main__":
    unittest.main()
