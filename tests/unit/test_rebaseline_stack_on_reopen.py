import json
import unittest

from lightcycle.application.flow.rebaseline_stack_on_reopen import RebaselineStackOnReopenUseCase
from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from tests.support.stacked import STACK_URL, build_stack, with_state
from tests.unit.test_detect_stack_shape import _Rig

_FLOW = flow_from_metas({
    "watcher": {
        "model": "sonnet",
        "step": "watch-step",
        "routes": {"merged": "done-step", "stack-changed": "review-stack"},
        "on_pr_merge": "merged",
        "on_pr_stack_shape": "stack-changed",
    },
    "review-stack": {
        "step": "review-stack",
        "routes": {"reopen": "watch-step", "fold": "cut", "drop": "build"},
    },
    "cut": {"step": "cut"},
    "build": {"step": "build"},
})


def _use_case(rig):
    return RebaselineStackOnReopenUseCase(rig.store, rig.github, rig.flow)


def _review_step(rig):
    return rig.store.create_step(stage="review-stack", role="human", item=rig.item)


def _seen(rig):
    return rig.store.get_run(rig.rid).stack_seen


class TestRebaselineStackOnReopen(unittest.TestCase):
    def _fired(self):
        rig = _Rig(build_stack(3), flow=_FLOW)
        rig.tick()
        rig.change(with_state(rig.layers, 2, "closed"))
        self.assertEqual(rig.tick().shape_changed, [rig.item])
        return rig

    def test_closing_review_stack_on_reopen_records_the_live_stack_as_the_baseline(self):
        rig = self._fired()
        review = _review_step(rig)
        rig.change(with_state(rig.layers, 2, "open"))

        _use_case(rig).execute(review, "reopen")

        self.assertEqual([e["state"] for e in rig.record()], ["open", "open", "open"])
        replacement = rig.store.create_step(stage="watch-step", role="agent", item=rig.item)
        self.assertEqual(rig.tick().shape_changed, [])
        self.assertNotEqual(rig.store.get_node(replacement).state, State.DONE)

    def test_without_the_use_case_the_reopened_layer_bounces(self):
        rig = self._fired()
        rig.change(with_state(rig.layers, 2, "open"))
        rig.store.create_step(stage="watch-step", role="agent", item=rig.item)

        self.assertEqual(rig.tick().shape_changed, [rig.item])

    def test_fold_and_drop_leave_the_record_alone(self):
        rig = self._fired()
        before = _seen(rig)
        for outcome in ("fold", "drop"):
            _use_case(rig).execute(_review_step(rig), outcome)
            self.assertEqual(_seen(rig), before)

    def test_a_failed_read_clears_the_record(self):
        rig = self._fired()
        review = _review_step(rig)
        rig.github._failing_calls = {"stack_view"}

        _use_case(rig).execute(review, "reopen")

        self.assertIsNone(_seen(rig))

    def test_a_dissolved_read_clears_the_record(self):
        rig = self._fired()
        review = _review_step(rig)
        rig.github._stacks.pop(STACK_URL)

        _use_case(rig).execute(review, "reopen")

        self.assertIsNone(_seen(rig))

    def test_a_step_at_a_stage_that_is_not_a_stack_review_stage_is_left_alone(self):
        rig = self._fired()
        before = _seen(rig)
        other = rig.store.create_step(stage="build", role="agent", item=rig.item)

        _use_case(rig).execute(other, "reopen")

        self.assertEqual(_seen(rig), before)
        self.assertEqual(json.loads(before)[1]["state"], "closed")
