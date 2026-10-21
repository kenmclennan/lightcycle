import time
import unittest

from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.pr_poll import PrPoll
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.pool.pr_writes import PrWrites
from lightcycle.ports.github import Comment
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import _FEEDBACK_FLOW, _TRUST, _FlowAdapter, plant_pr

_PR = "https://github.com/acme/widget/pull/1"
_BASE = "acme/widget@main"


class _Log:
    def append_run_log(self, text):
        pass


def _comment(ts):
    return (ts, Comment(author="reviewer", body="@lc fix this", is_top_level=True,
                        id=str(ts), created_at=ts))


class _Rig:
    def __init__(self, comments, **fake):
        self.github = FakeGitHub(
            updated_ats={_PR: 1.0}, head_shas={_PR: "h0"}, push_time=1000.0,
            timed_comments=comments, **fake)
        self.snapshot = PrSnapshot(self.github)
        self.writes = PrWrites(time.monotonic)
        self.poll = PrPoll(self.github, self.snapshot, self.writes, _Log())
        self.store = FakeStore()
        self.item = self.store.create_item("feature", "d")
        plant_pr(self.store, self.item, _PR)
        self.step = self.store.create_step(stage="ready-merge", role="human", item=self.item)
        self.dispatch = DispatchPrFeedbackUseCase(
            self.store, self.snapshot, _FlowAdapter(_FEEDBACK_FLOW), None, **_TRUST)
        self.now = 0.0

    def poll_once(self):
        self.snapshot.head_sha(_PR)
        self.now += 60.0
        self.poll.run(self.snapshot.take_wanted(), self.now, 10)

    def request_update(self):
        head = self.snapshot.head_sha(_PR)
        self.writes.request_update(_PR, head, _BASE)

    def push_by_hand(self, head, ts):
        self.github._head_shas[_PR] = head
        self.github._push_time = ts
        self.github.touch(_PR, ts)

    def feedback_steps(self):
        return [n for n in self.store.all_nodes()
                if n.type == "step" and n.stage == "handle-feedback"]

    def cutoff_artifacts(self):
        return [r.artifact.value for r in self.store.artifact_log(self.item)
                if r.artifact.type == "feedback-cutoff"]


class TestFeedbackCutoff(unittest.TestCase):
    def _updating_rig(self, comments=None):
        return _Rig(
            comments if comments is not None else [_comment(1500.0)],
            strict_bases=[_BASE], behind_prs=[_PR], base_keys={_PR: _BASE},
            update_pushed_at=2000.0)

    def test_a_pool_update_does_not_drop_feedback_posted_before_it(self):
        rig = self._updating_rig()
        rig.poll_once()
        first_head = rig.snapshot.entry_of(_PR).cutoff_head
        rig.request_update()

        rig.poll_once()
        rig.dispatch.execute()

        entry = rig.snapshot.entry_of(_PR)
        self.assertEqual(entry.push_time, 1000.0)
        self.assertEqual(entry.cutoff_head, first_head + "-updated")
        self.assertEqual(len(rig.feedback_steps()), 1)
        self.assertEqual(rig.cutoff_artifacts(), ["1000.0"])

    def test_a_head_change_without_a_queued_update_moves_the_cutoff(self):
        rig = _Rig([_comment(1500.0), _comment(2500.0)])
        rig.poll_once()

        rig.push_by_hand("h1", 2000.0)
        rig.poll_once()
        rig.dispatch.execute()

        self.assertEqual(rig.snapshot.entry_of(_PR).push_time, 2000.0)
        self.assertEqual(len(rig.feedback_steps()), 1)
        self.assertEqual(rig.cutoff_artifacts(), ["2000.0"])
        run = rig.store.current_run(rig.item, None)
        self.assertEqual(run.comments_dispatched_through, "2500.0")

    def test_a_comment_at_exactly_the_carried_cutoff_is_not_dispatched(self):
        at = _Rig([_comment(1000.0)], strict_bases=[_BASE], behind_prs=[_PR],
                  base_keys={_PR: _BASE}, update_pushed_at=2000.0)
        at.poll_once()
        at.request_update()
        at.poll_once()
        at.dispatch.execute()
        self.assertEqual(at.feedback_steps(), [])

        after = self._updating_rig([_comment(1000.5)])
        after.poll_once()
        after.request_update()
        after.poll_once()
        after.dispatch.execute()
        self.assertEqual(len(after.feedback_steps()), 1)

    def test_a_chain_of_pool_updates_before_the_next_full_read_keeps_the_cutoff(self):
        rig = self._updating_rig()
        rig.poll_once()
        rig.request_update()
        rig.writes.perform(rig.github)
        rig.github._behind.add(_PR)
        second_head = rig.github._head_shas[_PR]
        rig.writes.request_update(_PR, second_head, _BASE)
        rig.writes.perform(rig.github)

        rig.poll_once()

        entry = rig.snapshot.entry_of(_PR)
        self.assertEqual(entry.push_time, 1000.0)
        self.assertEqual(entry.cutoff_head, rig.github._head_shas[_PR])

    def test_a_human_push_after_a_carried_cutoff_moves_it(self):
        rig = self._updating_rig([])
        rig.poll_once()
        rig.request_update()
        rig.poll_once()
        self.assertEqual(rig.snapshot.entry_of(_PR).push_time, 1000.0)

        rig.push_by_hand("human-head", 3000.0)
        rig.poll_once()

        self.assertEqual(rig.snapshot.entry_of(_PR).push_time, 3000.0)

    def test_a_failed_update_records_nothing_and_a_later_head_change_moves_the_cutoff(self):
        rig = _Rig([], strict_bases=[_BASE], behind_prs=[_PR], base_keys={_PR: _BASE},
                   failing_calls={"update_branch"})
        rig.poll_once()
        first_head = rig.snapshot.entry_of(_PR).cutoff_head
        rig.request_update()
        rig.poll_once()

        self.assertFalse(rig.writes.pool_updated_from(_PR, first_head))

        rig.push_by_hand("h1", 2000.0)
        rig.poll_once()

        self.assertEqual(rig.snapshot.entry_of(_PR).push_time, 2000.0)

    def test_retain_drops_the_record_for_an_unwanted_pr(self):
        rig = self._updating_rig([])
        rig.poll_once()
        first_head = rig.snapshot.entry_of(_PR).cutoff_head
        rig.request_update()
        rig.poll_once()
        self.assertTrue(rig.writes.pool_updated_from(_PR, first_head))

        rig.writes.retain(set())

        self.assertFalse(rig.writes.pool_updated_from(_PR, first_head))
