import threading
import time
import unittest

from lightcycle.adapters.github_poll_runner import GithubPollRunnerAdapter
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.github_poll import GithubPollUseCase
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.pool.pr_writes import PrWrites
from lightcycle.ports.store import StoreError
from tests.support.fake_fs import FakeFs
from tests.support.fake_github import FakeGitHub
from tests.support.fake_github_budget_status import FakeGithubBudgetStatus
from tests.support.fake_github_poll_runner import InlineGithubPollRunner
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import _FEEDBACK_FLOW, _TRUST, _FlowAdapter, plant_pr
from tests.unit.test_feedback_cutoff import _BASE, _PR, _comment

_OTHER = "https://github.com/acme/widget/pull/2"


class _Config:
    def github_poll_seconds(self):
        return 60

    def github_view_refresh_polls(self):
        return 1000


class _Process:
    def __init__(self, github, store, runner=None):
        self.github = github
        self.store = store
        self.snapshot = PrSnapshot(github)
        self.writes = PrWrites(time.monotonic)
        self.runner = runner or InlineGithubPollRunner()
        self.gate = GithubPollUseCase(
            self.snapshot, github, self.runner, _Config(), self.writes,
            FakeGithubBudgetStatus(), lambda: 1000.0, FakeFs(), store)
        self.dispatch = DispatchPrFeedbackUseCase(
            store, self.snapshot, _FlowAdapter(_FEEDBACK_FLOW), None, **_TRUST)
        self.now = 0.0

    def poll(self, *prs):
        for pr in prs or (_PR,):
            self.snapshot.head_sha(pr)
        self.now += 60.0
        self.gate.execute(self.now)
        self.gate.settle()

    def request_update(self):
        self.writes.request_update(_PR, self.snapshot.head_sha(_PR), _BASE)


class _Rig:
    def __init__(self, comments=None, store=None, **fake):
        self.github = FakeGitHub(
            updated_ats={_PR: 1.0, _OTHER: 1.0}, head_shas={_PR: "h0", _OTHER: "o0"},
            push_time=1000.0,
            timed_comments=[_comment(1500.0)] if comments is None else comments,
            strict_bases=[_BASE], behind_prs=[_PR], base_keys={_PR: _BASE},
            update_pushed_at=2000.0, **fake)
        self.store = store or FakeStore()
        self.item = self.store.create_item("feature", "d")
        plant_pr(self.store, self.item, _PR)
        self.store.create_step(step="ready-merge", role="human", parent=self.item)
        self.process = _Process(self.github, self.store)

    def restart(self, runner=None):
        self.process = _Process(self.github, self.store, runner)
        return self.process

    def feedback_steps(self):
        return [n for n in self.store.all_nodes()
                if n.type == "step" and n.stage == "handle-feedback"]

    def cutoff_artifacts(self):
        return [r.artifact.value for r in self.store.artifact_log(self.item)
                if r.artifact.type == "feedback-cutoff"]

    def push_by_hand(self, head, ts):
        self.github._head_shas[_PR] = head
        self.github._push_time = ts
        self.github.touch(_PR, ts)


class _RecordingStore(FakeStore):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.threads = []
        self.fail_saves = 0

    def _note(self, name):
        self.calls.append(name)
        self.threads.append(threading.current_thread())

    def feedback_cutoff(self, pr):
        self._note("feedback_cutoff")
        return super().feedback_cutoff(pr)

    def pool_updated_heads(self, pr):
        self._note("pool_updated_heads")
        return super().pool_updated_heads(pr)

    def record_pool_update(self, pr, head_sha):
        self._note("record_pool_update")
        return super().record_pool_update(pr, head_sha)

    def save_feedback_cutoff(self, pr, cutoff, cutoff_head):
        self._note("save_feedback_cutoff")
        if self.fail_saves:
            self.fail_saves -= 1
            raise StoreError("boom")
        return super().save_feedback_cutoff(pr, cutoff, cutoff_head)

    def prune_pr_feedback_state(self, max_age_days):
        self._note("prune_pr_feedback_state")
        return super().prune_pr_feedback_state(max_age_days)


class TestFeedbackCutoffAcrossARestart(unittest.TestCase):
    def _rebased(self, rig):
        first = rig.process
        first.poll()
        first.request_update()
        first.poll()
        return first

    def test_a_restart_after_a_pool_update_still_dispatches_the_earlier_comment(self):
        rig = _Rig()
        self._rebased(rig)

        restarted = rig.restart()
        restarted.poll()
        restarted.dispatch.execute()

        self.assertEqual(restarted.snapshot.entry_of(_PR).push_time, 1000.0)
        self.assertEqual(len(rig.feedback_steps()), 1)
        self.assertEqual(rig.cutoff_artifacts(), ["1000.0"])

    def test_a_head_change_with_no_recorded_pool_update_moves_the_cutoff_across_a_restart(self):
        rig = _Rig([_comment(1500.0), _comment(2500.0)])
        rig.process.poll()
        rig.push_by_hand("h1", 2000.0)

        restarted = rig.restart()
        restarted.poll()
        restarted.dispatch.execute()

        self.assertEqual(restarted.snapshot.entry_of(_PR).push_time, 2000.0)
        self.assertEqual(len(rig.feedback_steps()), 1)
        self.assertEqual(rig.cutoff_artifacts(), ["2000.0"])

    def test_a_restart_with_nothing_moved_keeps_the_cutoff(self):
        rig = _Rig()
        rig.process.poll()

        restarted = rig.restart()
        restarted.poll()

        self.assertEqual(restarted.snapshot.entry_of(_PR).push_time, 1000.0)
        self.assertEqual(restarted.snapshot.entry_of(_PR).cutoff_head, "h0")

    def test_a_chain_of_pool_updates_survives_a_restart(self):
        rig = _Rig()
        first = rig.process
        first.poll()
        first.request_update()
        first.writes.perform(rig.github)
        rig.github._behind.add(_PR)
        first.writes.request_update(_PR, rig.github._head_shas[_PR], _BASE)
        first.writes.perform(rig.github)
        first.poll()
        self.assertEqual(sorted(rig.store.pool_updated_heads(_PR)), ["h0", "h0-updated"])

        restarted = rig.restart()
        restarted.poll()

        self.assertEqual(restarted.snapshot.entry_of(_PR).push_time, 1000.0)

    def test_only_a_pr_with_a_stored_cutoff_is_seeded(self):
        rig = _Rig()
        rig.process.poll()
        self.assertIsNone(rig.store.feedback_cutoff(_OTHER))
        rig.github._push_time = 3000.0

        restarted = rig.restart()
        restarted.poll(_PR, _OTHER)

        self.assertEqual(restarted.snapshot.seed_of(_PR), (1000.0, "h0"))
        self.assertIsNone(restarted.snapshot.seed_of(_OTHER))
        self.assertEqual(restarted.snapshot.entry_of(_PR).push_time, 1000.0)
        self.assertEqual(restarted.snapshot.entry_of(_OTHER).push_time, 3000.0)

    def test_a_comment_at_the_persisted_cutoff_is_not_dispatched_and_one_after_it_is(self):
        at = _Rig([_comment(1000.0)])
        self._rebased(at)
        restarted = at.restart()
        restarted.poll()
        restarted.dispatch.execute()
        self.assertEqual(at.feedback_steps(), [])

        after = _Rig([_comment(1000.5)])
        self._rebased(after)
        restarted = after.restart()
        restarted.poll()
        restarted.dispatch.execute()
        self.assertEqual(len(after.feedback_steps()), 1)


class TestFeedbackCutoffFlush(unittest.TestCase):
    def _rig(self):
        rig = _Rig(store=_RecordingStore())
        return rig

    def test_a_failed_write_is_retried_on_the_next_execute_and_does_not_raise(self):
        rig = self._rig()
        rig.store.fail_saves = 1
        process = rig.process

        process.poll()
        self.assertIsNone(rig.store.feedback_cutoff(_PR))

        process.now += 60.0
        process.gate.execute(process.now)

        self.assertEqual(rig.store.feedback_cutoff(_PR), (1000.0, "h0"))

    def test_a_pool_update_is_written_before_the_cutoff_in_one_flush(self):
        rig = self._rig()
        process = rig.process
        process.poll()
        process.request_update()
        rig.store.calls.clear()

        process.poll()

        writes = [c for c in rig.store.calls if c in ("record_pool_update", "save_feedback_cutoff")]
        self.assertEqual(writes[:2], ["record_pool_update", "save_feedback_cutoff"])

    def test_the_first_execute_prunes_and_later_ones_do_not(self):
        rig = self._rig()
        process = rig.process
        process.poll()
        process.poll()
        process.poll()
        self.assertEqual(rig.store.calls.count("prune_pr_feedback_state"), 1)

    def test_the_poll_thread_never_calls_the_store(self):
        rig = self._rig()
        runner = GithubPollRunnerAdapter(FakeFs())
        process = rig.restart(runner)
        process.poll()
        process.request_update()
        process.poll()
        process.poll()

        self.assertTrue(rig.store.threads)
        self.assertEqual({t for t in rig.store.threads}, {threading.current_thread()})


if __name__ == "__main__":
    unittest.main()
