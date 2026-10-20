import time
import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_writes import InlinePrWrites
from lightcycle.application.pool import MonitorPrsUseCase
from lightcycle.application.pool.detect_head_moved import (
    CI_JUDGED_SHA,
    PR_HEAD_SHA,
    DetectHeadMovedUseCase,
)
from lightcycle.application.pool.pr_sync_reads import PrSyncReads
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import _FlowAdapter, plant_pr
from tests.unit.test_monitor_prs import FakeWorktrees

_GATE = {
    "model": "sonnet",
    "step": "watch-step",
    "routes": {"merged": "done-step", "head-moved": "ci-step"},
    "on_pr_merge": "merged",
    "on_pr_head_moved": "head-moved",
}

_FLOW = flow_from_metas(
    {
        "watcher": _GATE,
        "ci": {
            "step": "ci-step",
            "routes": {"passed": "watch-step", "failed": "watch-step"},
            "on_ci_success": "passed",
            "on_ci_failure": "failed",
        },
    }
)

_PLAIN = flow_from_metas(
    {
        "watcher": {
            "model": "sonnet",
            "step": "watch-step",
            "routes": {"merged": "done-step"},
            "on_pr_merge": "merged",
        },
    }
)


def _pr(n):
    return "https://github.com/x/y/pull/%d" % n


def _value(store, step, atype):
    found = None
    for artifact in store.item_artifacts(step):
        if artifact.type == atype:
            found = artifact.value
    return found


class _Harness:
    def __init__(self, heads, flow=_FLOW):
        self.store = FakeStore()
        self.heads = heads
        self.github = FakeGitHub(head_shas=heads)
        self.flow = _FlowAdapter(flow)
        self.complete = CompleteStepUseCase(self.store, self.flow)
        self.uc = DetectHeadMovedUseCase(self.store, self.flow, self.complete)

    def run(self):
        return self.uc.execute(PrSyncReads(self.github))

    def item_with_pr(self, url):
        item = self.store.create_item("feature", "d")
        plant_pr(self.store, item, url)
        return item

    def ci_round(self, item, outcome, sha):
        step = self.store.create_step(step="ci-step", role="engine", parent=item)
        if sha is not None:
            self.store.add_artifact(step, CI_JUDGED_SHA, sha, internal=True)
        self.complete.execute(CompleteInput(step=step, outcome=outcome))
        return step

    def gate(self, item):
        for child in self.store.children(item):
            if child.stage == "watch-step" and child.state != "done":
                return child.id
        raise AssertionError("no open gate")

    def state(self, step):
        return self.store.get_node(step).state


class TestBaselineFromCi(unittest.TestCase):
    def test_push_between_ci_and_first_pass_fires(self):
        url = _pr(1)
        h = _Harness({url: "bbb"})
        item = h.item_with_pr(url)
        h.ci_round(item, "passed", "aaa")
        gate = h.gate(item)

        result = h.run()

        self.assertEqual(result.head_moved, [item])
        self.assertEqual(h.state(gate), "done")

    def test_unmoved_head_records_judged_sha_and_does_not_fire(self):
        url = _pr(2)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        h.ci_round(item, "passed", "aaa")
        gate = h.gate(item)

        result = h.run()

        self.assertEqual(result.head_moved, [])
        self.assertEqual(_value(h.store, gate, PR_HEAD_SHA), "aaa")
        self.assertNotEqual(h.state(gate), "done")

    def test_failed_round_after_green_uses_latest_round_and_does_not_fire(self):
        url = _pr(3)
        h = _Harness({url: "ccc"})
        item = h.item_with_pr(url)
        h.ci_round(item, "passed", "aaa")
        h.complete.execute(CompleteInput(step=h.gate(item), outcome="head-moved"))
        h.ci_round(item, "failed", "ccc")
        gate = h.gate(item)

        result = h.run()

        self.assertEqual(result.head_moved, [])
        self.assertEqual(_value(h.store, gate, PR_HEAD_SHA), "ccc")

    def test_failed_round_then_a_later_push_fires(self):
        url = _pr(4)
        h = _Harness({url: "ddd"})
        item = h.item_with_pr(url)
        h.ci_round(item, "failed", "ccc")

        result = h.run()

        self.assertEqual(result.head_moved, [item])

    def test_no_ci_step_records_observed_head_without_firing(self):
        url = _pr(5)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        gate = h.store.create_step(step="watch-step", role="agent", parent=item)

        result = h.run()

        self.assertEqual(result.head_moved, [])
        self.assertEqual(_value(h.store, gate, PR_HEAD_SHA), "aaa")

    def test_ci_step_without_judged_sha_records_observed_head_without_firing(self):
        url = _pr(6)
        h = _Harness({url: "zzz"})
        item = h.item_with_pr(url)
        h.ci_round(item, "passed", None)
        gate = h.gate(item)

        result = h.run()

        self.assertEqual(result.head_moved, [])
        self.assertEqual(_value(h.store, gate, PR_HEAD_SHA), "zzz")


class TestDetection(unittest.TestCase):
    def test_first_sight_records_then_changed_head_fires(self):
        url = _pr(10)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        gate = h.store.create_step(step="watch-step", role="agent", parent=item)

        self.assertEqual(h.run().head_moved, [])
        self.assertEqual(h.run().head_moved, [])
        h.heads[url] = "bbb"
        self.assertEqual(h.run().head_moved, [item])
        self.assertEqual(h.state(gate), "done")

    def test_unknown_head_does_not_fire(self):
        url = _pr(11)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        h.store.create_step(step="watch-step", role="agent", parent=item)
        h.run()
        h.heads[url] = ""

        self.assertEqual(h.run().head_moved, [])

    def test_read_failure_does_not_fire(self):
        url = _pr(12)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        h.store.create_step(step="watch-step", role="agent", parent=item)
        h.run()
        h.github = FakeGitHub(head_shas={url: "bbb"}, failing_calls={"pr_sync_state"})

        self.assertEqual(h.run().head_moved, [])

    def test_open_feedback_step_defers_the_fire(self):
        url = _pr(13)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        gate = h.store.create_step(step="watch-step", role="agent", parent=item)
        h.run()
        feedback = h.store.create_step(step="watch-step", role="agent", parent=item)
        h.store.set_watched_step(feedback, gate)
        h.heads[url] = "bbb"

        self.assertEqual(h.run().head_moved, [])
        self.assertNotEqual(h.state(gate), "done")

    def test_gate_without_the_hook_is_untouched(self):
        url = _pr(14)
        h = _Harness({url: "aaa"}, flow=_PLAIN)
        item = h.item_with_pr(url)
        gate = h.store.create_step(step="watch-step", role="agent", parent=item)
        h.run()
        h.heads[url] = "bbb"

        self.assertEqual(h.run().head_moved, [])
        self.assertIsNone(_value(h.store, gate, PR_HEAD_SHA))

    def test_only_the_moved_gate_is_listed(self):
        a, b = _pr(15), _pr(16)
        h = _Harness({a: "aaa", b: "bbb"})
        item_a, item_b = h.item_with_pr(a), h.item_with_pr(b)
        h.store.create_step(step="watch-step", role="agent", parent=item_a)
        h.store.create_step(step="watch-step", role="agent", parent=item_b)
        h.run()
        h.heads[a] = "aa2"

        self.assertEqual(h.run().head_moved, [item_a])

    def test_no_complete_makes_the_use_case_a_no_op(self):
        url = _pr(17)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        h.store.create_step(step="watch-step", role="agent", parent=item)
        h.uc = DetectHeadMovedUseCase(h.store, h.flow, None)

        self.assertEqual(h.run().head_moved, [])


class TestMonitorWiring(unittest.TestCase):
    def test_update_branch_cause_fires_on_the_next_pass(self):
        url = _pr(20)
        github = FakeGitHub(
            behind_prs={url}, head_shas={url: "sha1"}, strict_bases={"acme/widget@main"}
        )
        store = FakeStore()
        item = store.create_item("feature", "d")
        plant_pr(store, item, url)
        gate = store.create_step(step="watch-step", role="agent", parent=item)
        flow = _FlowAdapter(_FLOW)
        monitor = MonitorPrsUseCase(
            store, github, FakeWorktrees(), flow, CompleteStepUseCase(store, flow),
            trusted_authors=lambda: frozenset(), held_shortcode=lambda: "HLD",
            writes=InlinePrWrites(github, time.monotonic), ci_clock=time.monotonic, ci_poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, ci_wall_clock=lambda: 10000.0,
        )

        first = monitor.execute()
        second = monitor.execute()

        self.assertEqual(first.updated, [item])
        self.assertEqual(first.head_moved, [])
        self.assertEqual(second.head_moved, [item])
        self.assertEqual(store.get_node(gate).state, "done")
