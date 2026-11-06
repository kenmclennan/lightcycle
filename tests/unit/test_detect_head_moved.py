import json
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
from tests.support.fake_view_freshness import AlwaysConfirmed
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
        self.uc = DetectHeadMovedUseCase(self.store, self.github, self.flow, self.complete)

    def run(self):
        return self.uc.execute(PrSyncReads(self.github))

    def item_with_pr(self, url):
        item = self.store.create_item("feature", "d")
        plant_pr(self.store, item, url)
        return item

    def ci_round(self, item, outcome, sha):
        step = self.store.create_step(stage="ci-step", role="engine", item=item)
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
        gate = h.store.create_step(stage="watch-step", role="agent", item=item)

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
        gate = h.store.create_step(stage="watch-step", role="agent", item=item)

        self.assertEqual(h.run().head_moved, [])
        self.assertEqual(h.run().head_moved, [])
        h.heads[url] = "bbb"
        self.assertEqual(h.run().head_moved, [item])
        self.assertEqual(h.state(gate), "done")

    def test_unknown_head_does_not_fire(self):
        url = _pr(11)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        h.store.create_step(stage="watch-step", role="agent", item=item)
        h.run()
        h.heads[url] = ""

        self.assertEqual(h.run().head_moved, [])

    def test_read_failure_does_not_fire(self):
        url = _pr(12)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        h.store.create_step(stage="watch-step", role="agent", item=item)
        h.run()
        h.github = FakeGitHub(head_shas={url: "bbb"}, failing_calls={"pr_sync_state"})

        self.assertEqual(h.run().head_moved, [])

    def test_open_feedback_step_defers_the_fire(self):
        url = _pr(13)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        gate = h.store.create_step(stage="watch-step", role="agent", item=item)
        h.run()
        feedback = h.store.create_step(stage="watch-step", role="agent", item=item)
        h.store.set_watched_step(feedback, gate)
        h.heads[url] = "bbb"

        self.assertEqual(h.run().head_moved, [])
        self.assertNotEqual(h.state(gate), "done")

    def test_gate_without_the_hook_is_untouched(self):
        url = _pr(14)
        h = _Harness({url: "aaa"}, flow=_PLAIN)
        item = h.item_with_pr(url)
        gate = h.store.create_step(stage="watch-step", role="agent", item=item)
        h.run()
        h.heads[url] = "bbb"

        self.assertEqual(h.run().head_moved, [])
        self.assertIsNone(_value(h.store, gate, PR_HEAD_SHA))

    def test_only_the_moved_gate_is_listed(self):
        a, b = _pr(15), _pr(16)
        h = _Harness({a: "aaa", b: "bbb"})
        item_a, item_b = h.item_with_pr(a), h.item_with_pr(b)
        h.store.create_step(stage="watch-step", role="agent", item=item_a)
        h.store.create_step(stage="watch-step", role="agent", item=item_b)
        h.run()
        h.heads[a] = "aa2"

        self.assertEqual(h.run().head_moved, [item_a])

    def test_no_complete_makes_the_use_case_a_no_op(self):
        url = _pr(17)
        h = _Harness({url: "aaa"})
        item = h.item_with_pr(url)
        h.store.create_step(stage="watch-step", role="agent", item=item)
        h.uc = DetectHeadMovedUseCase(h.store, h.github, h.flow, None)

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
        gate = store.create_step(stage="watch-step", role="agent", item=item)
        flow = _FlowAdapter(_FLOW)
        monitor = MonitorPrsUseCase(
            store, github, FakeWorktrees(), flow, CompleteStepUseCase(store, flow),
            trusted_authors=lambda: frozenset(), held_shortcode=lambda: "HLD",
            writes=InlinePrWrites(github, time.monotonic), ci_clock=time.monotonic, ci_poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, ci_wall_clock=lambda: 10000.0, ci_views=AlwaysConfirmed(),
        )

        first = monitor.execute()
        second = monitor.execute()

        self.assertEqual(first.updated, [item])
        self.assertEqual(first.head_moved, [])
        self.assertEqual(second.head_moved, [item])
        self.assertEqual(store.get_node(gate).state, "done")


class _StackedHarness:
    def __init__(self, count=3, signatures=None, with_gate=True):
        from tests.support.stacked import (
            STACK_URL, base_keys_for, build_stack, head_shas_for,
        )

        self.layers = build_stack(count)
        self.heads = head_shas_for(self.layers)
        self.signatures = dict(signatures or {})
        self.base = _Harness({})
        self.store = self.base.store
        self.github = FakeGitHub(
            stacks={STACK_URL: self.layers}, head_shas=self.heads,
            base_keys=base_keys_for(self.layers), signatures=self.signatures)
        self.base.github = self.github
        self.base.uc = DetectHeadMovedUseCase(
            self.store, self.github, self.base.flow, self.base.complete)
        self.item = self.store.create_item("feature", "d")
        rid = plant_pr(self.store, self.item, self.layers[-1].url)
        self.store.set_stack(rid, STACK_URL)
        self.gate = (
            self.store.create_step(stage="watch-step", role="agent", item=self.item)
            if with_gate else None
        )

    def run(self):
        return self.base.run()

    def move(self, number, sha):
        from tests.support.stacked import layer_url

        self.heads[layer_url(number)] = sha

    def sign(self, number, sha, signature):
        from tests.support.stacked import layer_url

        self.github._signatures[(layer_url(number), sha)] = signature

    def checks_read(self, number, sha):
        from tests.support.stacked import layer_url

        return ("check_runs", layer_url(number), sha) in self.github.calls


class TestHeadMovedOverAStack(unittest.TestCase):
    def test_a_cascaded_head_updates_the_record_and_rereads_checks_only(self):
        h = _StackedHarness()
        h.sign(2, "sha-2", "same")
        h.run()
        h.move(2, "sha-2-rebased")
        h.sign(2, "sha-2-rebased", "same")

        result = h.run()

        self.assertEqual(result.head_moved, [])
        self.assertNotEqual(h.base.state(h.gate), "done")
        self.assertTrue(h.checks_read(2, "sha-2-rebased"))
        recorded = json.loads(_value(h.store, h.gate, "pr-layer-heads"))
        self.assertEqual(recorded[_pr_layer(2)], "sha-2-rebased")

    def test_a_pushed_head_fires_naming_the_layer(self):
        h = _StackedHarness()
        h.sign(2, "sha-2", "before")
        h.run()
        h.move(2, "sha-2-pushed")
        h.sign(2, "sha-2-pushed", "after")

        result = h.run()

        self.assertEqual(result.head_moved, [h.item])
        node = h.store.get_node(h.gate)
        self.assertEqual(node.state, "done")
        self.assertIn("head of layer 2 of 3 (%s) moved from sha-2 to sha-2-pushed" % _pr_layer(2),
                      node.report)

    def test_an_unknown_old_signature_fires(self):
        h = _StackedHarness()
        h.run()
        h.move(2, "sha-2-new")
        h.sign(2, "sha-2-new", "after")

        self.assertEqual(h.run().head_moved, [h.item])

    def test_an_unreadable_new_signature_counts_as_a_push(self):
        h = _StackedHarness()
        h.sign(2, "sha-2", "before")
        h.run()
        h.move(2, "sha-2-new")

        self.assertEqual(h.run().head_moved, [h.item])

    def test_a_new_signature_not_yet_read_waits_then_resolves(self):
        from lightcycle.ports.github import NotYetRead

        h = _StackedHarness()
        h.sign(2, "sha-2", "same")
        h.run()
        h.move(2, "sha-2-rebased")
        h.sign(2, "sha-2-rebased", NotYetRead())

        self.assertEqual(h.run().head_moved, [])
        recorded = json.loads(_value(h.store, h.gate, "pr-layer-heads"))
        self.assertEqual(recorded[_pr_layer(2)], "sha-2")

        h.sign(2, "sha-2-rebased", "same")

        self.assertEqual(h.run().head_moved, [])
        recorded = json.loads(_value(h.store, h.gate, "pr-layer-heads"))
        self.assertEqual(recorded[_pr_layer(2)], "sha-2-rebased")
        self.assertNotEqual(h.base.state(h.gate), "done")

    def test_two_moved_layers_fire_once_naming_only_the_pushed_one(self):
        h = _StackedHarness()
        h.sign(1, "sha-1", "one")
        h.sign(3, "sha-3", "three")
        h.run()
        h.move(1, "sha-1-rebased")
        h.sign(1, "sha-1-rebased", "one")
        h.move(3, "sha-3-pushed")
        h.sign(3, "sha-3-pushed", "other")

        result = h.run()

        self.assertEqual(result.head_moved, [h.item])
        report = h.store.get_node(h.gate).report
        self.assertIn("layer 3 of 3", report)
        self.assertNotIn("layer 1 of 3", report)

    def test_a_layer_with_no_recorded_head_is_recorded_silently(self):
        h = _StackedHarness(count=2)
        h.run()
        from tests.support.stacked import build_stack, head_shas_for, base_keys_for, STACK_URL

        bigger = build_stack(3)
        h.heads.update(head_shas_for(bigger))
        h.github.script_stack(STACK_URL, bigger)
        h.github._base_keys = base_keys_for(bigger)

        self.assertEqual(h.run().head_moved, [])
        recorded = json.loads(_value(h.store, h.gate, "pr-layer-heads"))
        self.assertIn(_pr_layer(3), recorded)

    def test_the_record_is_seeded_from_the_judged_layers_of_the_last_ci_round(self):
        h = _StackedHarness(with_gate=False)
        judged = {_pr_layer(n): "sha-%d" % n for n in (1, 2, 3)}
        judged[_pr_layer(2)] = "older"
        step = h.store.create_step(stage="ci-step", role="engine", item=h.item)
        h.store.add_artifact(step, "ci-judged-layers", json.dumps(judged), internal=True)
        h.base.complete.execute(CompleteInput(step=step, outcome="passed"))
        gate = h.base.gate(h.item)
        h.sign(2, "sha-2", "now")

        result = h.run()

        self.assertEqual(result.head_moved, [h.item])
        self.assertEqual(h.base.state(gate), "done")


def _pr_layer(n):
    from tests.support.stacked import layer_url

    return layer_url(n)
