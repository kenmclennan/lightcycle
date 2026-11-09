import json
import unittest
from dataclasses import replace
from tests.support.null_collaborators import NoopWorktrees

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool.detect_stack_shape import DetectStackShapeUseCase
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.stacked import (
    STACK_URL, base_keys_for, build_stack, layer_url, rederive, with_state,
)
from tests.unit.test_dispatch_pr_feedback import _FlowAdapter, plant_pr

_FLOW = flow_from_metas({
    "watcher": {
        "model": "sonnet",
        "step": "watch-step",
        "routes": {"merged": "done-step", "stack-changed": "review-stack"},
        "on_pr_merge": "merged",
        "on_pr_stack_shape": "stack-changed",
    },
    "review-stack": {"step": "review-stack"},
})

_NO_HOOK = flow_from_metas({
    "watcher": {
        "model": "sonnet", "step": "watch-step",
        "routes": {"merged": "done-step"}, "on_pr_merge": "merged",
    },
})


class _Rig:
    def __init__(self, layers, flow=_FLOW, overrides=None):
        self.layers = layers
        self.overrides = overrides or {}
        self.store = FakeStore()
        self.github = self._github(layers)
        self.flow = _FlowAdapter(flow)
        self.complete = CompleteStepUseCase(self.store, self.flow, worktrees=NoopWorktrees(), config=None)
        self.uc = DetectStackShapeUseCase(self.store, self.github, self.flow, self.complete)
        self.item = self.store.create_item("feature", "d")
        self.rid = plant_pr(self.store, self.item, layers[-1].url)
        self.store.set_stack(self.rid, STACK_URL)
        self.step = self.store.create_step(stage="watch-step", role="agent", item=self.item)

    def _github(self, layers):
        return FakeGitHub(
            stacks={STACK_URL: layers}, base_keys=base_keys_for(layers, self.overrides))

    def change(self, layers, overrides=None):
        self.layers = layers
        self.github.script_stack(STACK_URL, layers)
        self.github._base_keys = base_keys_for(layers, overrides or {})

    def tick(self):
        return self.uc.execute()

    def record(self):
        return json.loads(self.store.get_run(self.rid).stack_seen)

    def notes(self):
        return self.store.get_node(self.step).notes or ""


class TestDetectStackShape(unittest.TestCase):
    def _fires_once(self, rig, fragment):
        first = rig.tick()
        self.assertEqual(first.shape_changed, [rig.item])
        node = rig.store.get_node(rig.step)
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "stack-changed")
        self.assertTrue(node.report.startswith("stack shape changed: "))
        self.assertIn(fragment, node.report)
        return node

    def _baselined(self, count=3, **kwargs):
        rig = _Rig(build_stack(count), **kwargs)
        self.assertEqual(rig.tick().shape_changed, [])
        return rig

    def test_the_first_read_is_a_silent_baseline(self):
        rig = _Rig(build_stack(3))

        self.assertEqual(rig.tick().shape_changed, [])
        self.assertEqual([e["number"] for e in rig.record()], [1, 2, 3])
        self.assertNotEqual(rig.store.get_node(rig.step).state, State.DONE)

    def test_a_layer_closed_unmerged_fires_naming_the_layer(self):
        rig = self._baselined()
        rig.change(with_state(rig.layers, 2, "closed"))

        self._fires_once(rig, "layer 2 of 3 (%s) closed without merging" % layer_url(2))

    def test_a_layer_retargeted_onto_an_unrelated_base_fires(self):
        rig = self._baselined()
        rig.change(rig.layers, overrides={2: "feature-x"})

        self._fires_once(rig, "layer 2 of 3 (%s) was retargeted onto feature-x" % layer_url(2))

    def test_a_layer_added_fires(self):
        rig = self._baselined(2)
        rig.change(build_stack(3))

        self._fires_once(rig, "layer 3 of 3 (%s) was added" % layer_url(3))

    def test_a_layer_removed_fires(self):
        rig = self._baselined(3)
        rig.change(rederive(build_stack(3)[:2]))

        self._fires_once(rig, "layer 3 of 3 (#3) was removed")

    def test_layers_reordered_fire(self):
        rig = self._baselined(3)
        a, b, c = build_stack(3)
        rig.change(rederive((b, a, c)))

        self._fires_once(rig, "the layers were reordered")

    def test_a_dissolved_stack_fires_for_an_empty_tuple(self):
        rig = self._baselined()
        rig.change(())

        self._fires_once(rig, "the stack was dissolved")

    def test_a_dissolved_stack_fires_for_http_404(self):
        rig = self._baselined()
        rig.github._stacks.pop(STACK_URL)

        self._fires_once(rig, "the stack was dissolved")

    def test_a_closed_layer_that_reopens_fires(self):
        rig = self._baselined()
        rig.change(with_state(rig.layers, 2, "closed"))
        rig.tick()
        replacement = rig.store.create_step(stage="watch-step", role="agent", item=rig.item)
        rig.step = replacement
        rig.change(with_state(rig.layers, 2, "open"))

        self._fires_once(rig, "changed state from closed to open")

    def test_each_difference_fires_once_across_further_ticks(self):
        rig = self._baselined()
        rig.change(with_state(rig.layers, 3, "closed"))
        rig.tick()
        replacement = rig.store.create_step(stage="watch-step", role="agent", item=rig.item)

        self.assertEqual(rig.tick().shape_changed, [])
        self.assertEqual(rig.tick().shape_changed, [])
        self.assertNotEqual(rig.store.get_node(replacement).state, State.DONE)

    def test_a_lower_merge_with_the_cascade_in_flight_is_not_a_shape_change(self):
        rig = self._baselined()
        merged = rederive(with_state(rig.layers, 1, "merged"))
        rig.change(merged, overrides={2: "layer-1"})

        self.assertEqual(rig.tick().shape_changed, [])

        rig.change(merged)
        self.assertEqual(rig.tick().shape_changed, [])
        self.assertNotEqual(rig.store.get_node(rig.step).state, State.DONE)

    def test_a_newly_merged_lower_layer_writes_the_progress_note_once(self):
        rig = self._baselined()
        rig.change(with_state(rig.layers, 1, "merged"))

        rig.tick()
        rig.tick()

        self.assertEqual(
            rig.notes().count(
                "stack progress: layer 1 of 3 (%s) merged; 2 layers remain" % layer_url(1)),
            1,
        )
        self.assertEqual(
            [e["state"] for e in rig.record()], ["merged", "open", "open"])

    def test_a_head_sha_change_is_not_a_shape_change(self):
        rig = self._baselined()
        rig.change(tuple(replace(l, head_sha=l.head_sha + "x") for l in rig.layers))

        self.assertEqual(rig.tick().shape_changed, [])

    def test_a_transient_read_failure_changes_nothing(self):
        rig = self._baselined()
        rig.github._stacks[STACK_URL] = ()
        rig.github._failing_calls = {"stack_view"}

        self.assertEqual(rig.tick().shape_changed, [])
        self.assertNotEqual(rig.store.get_node(rig.step).state, State.DONE)
        self.assertEqual([e["number"] for e in rig.record()], [1, 2, 3])

    def test_a_base_not_yet_read_is_skipped_and_the_previous_base_carried(self):
        rig = self._baselined()
        before = rig.record()
        rig.github._failing_calls = {"pr_sync_state"}

        self.assertEqual(rig.tick().shape_changed, [])
        self.assertEqual(rig.record(), before)

    def test_reattaching_the_stack_resets_the_baseline_silently(self):
        rig = self._baselined()
        rig.store.set_stack(rig.rid, STACK_URL)
        rig.change(with_state(rig.layers, 2, "closed"))

        self.assertEqual(rig.tick().shape_changed, [])
        self.assertIsNotNone(rig.store.get_run(rig.rid).stack_seen)

    def test_a_step_without_the_hook_records_nothing_and_the_difference_waits(self):
        rig = _Rig(build_stack(3), flow=_NO_HOOK)
        rig.tick()
        baseline = rig.store.get_run(rig.rid).stack_seen
        rig.change(with_state(rig.layers, 2, "closed"))

        self.assertEqual(rig.tick().shape_changed, [])
        self.assertEqual(rig.store.get_run(rig.rid).stack_seen, baseline)

        declaring = _FlowAdapter(_FLOW)
        rig.uc = DetectStackShapeUseCase(
            rig.store, rig.github, declaring, CompleteStepUseCase(rig.store, declaring, worktrees=NoopWorktrees(), config=None))

        self.assertEqual(rig.tick().shape_changed, [rig.item])

    def test_an_unstacked_run_is_ignored(self):
        store = FakeStore()
        item = store.create_item("feature", "d")
        plant_pr(store, item, layer_url(1))
        store.create_step(stage="watch-step", role="agent", item=item)
        flow = _FlowAdapter(_FLOW)
        github = FakeGitHub()
        uc = DetectStackShapeUseCase(store, github, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None))

        self.assertEqual(uc.execute().shape_changed, [])
        self.assertNotIn("stack_view", [c[0] for c in github.calls])

    def test_a_read_failure_other_than_404_is_not_dissolution(self):
        rig = self._baselined()
        rig.github._failing_calls = {"stack_view"}
        self.assertIsInstance(rig.github.stack_view(STACK_URL), ReadFailure)

        self.assertEqual(rig.tick().shape_changed, [])
