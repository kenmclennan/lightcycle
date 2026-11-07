import unittest
from dataclasses import replace

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.dispatch_pr_feedback import (
    CONFLICT_BASE_TIP,
    DispatchPrFeedbackUseCase,
)
from lightcycle.domain.flow import pr_conflict_failures
from lightcycle.ports.github import ReadFailure
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.stacked import (
    STACK_URL,
    base_keys_for,
    build_stack,
    head_shas_for,
    layer_url,
    with_state,
)
from tests.unit.test_dispatch_pr_feedback import (
    _CONFLICT_FLOW,
    _TRUST,
    _FlowAdapter,
    plant_pr,
)

_CAP_FLOW = _CONFLICT_FLOW


class _ScriptedGitHub(FakeGitHub):
    def __init__(self, *args, unsettled=(), **kwargs):
        super().__init__(*args, **kwargs)
        self._unsettled = set(unsettled)

    def pr_sync_state(self, pr):
        if pr in self._failing_prs:
            return ReadFailure(1, "boom")
        sync = super().pr_sync_state(pr)
        if pr in self._unsettled:
            return replace(sync, settled=False)
        return sync


class _Rig:
    def __init__(self, conflicted=(), behind=(), strict=(), layers=None, failing=(),
                 stacked=True, flow=_CONFLICT_FLOW, overrides=None, failing_prs=(), unsettled=()):
        self.layers = layers if layers is not None else build_stack(3)
        urls = {layer_url(n) for n in range(1, 4)}
        self.github = _ScriptedGitHub(
            conflicted_prs={layer_url(n) for n in conflicted},
            behind_prs={layer_url(n) for n in behind},
            strict_bases=set(strict),
            base_keys=base_keys_for(self.layers, overrides),
            head_shas=head_shas_for(self.layers),
            stacks={STACK_URL: self.layers},
            failing_calls=failing,
            failing_prs={layer_url(n) for n in failing_prs},
            unsettled={layer_url(n) for n in unsettled},
        )
        self.store = FakeStore()
        self.item = self.store.create_item("stacked feature", "a description")
        top = (self.layers[-1].url if self.layers else layer_url(3)) if stacked else layer_url(1)
        self.rid = plant_pr(self.store, self.item, top)
        if stacked:
            self.store.set_stack(self.rid, STACK_URL)
        self.flow = flow
        self.complete = CompleteStepUseCase(self.store, _FlowAdapter(flow))
        self.dispatch = DispatchPrFeedbackUseCase(
            self.store, self.github, _FlowAdapter(flow), self.complete, **_TRUST)
        self.step = self.store.create_step(stage="watch-step", role="agent", item=self.item)
        self.urls = urls

    def tick(self):
        return self.dispatch.execute()

    def node(self):
        return self.store.get_node(self.step)

    def note(self):
        return self.node().report or ""


class TestConflictOverAStack(unittest.TestCase):
    def test_layer_two_conflicted_reports_once_naming_layer_two(self):
        rig = _Rig(conflicted=[2])

        result = rig.tick()

        self.assertEqual(result.conflicted, [rig.item])
        self.assertEqual(rig.node().outcome, "conflicted")
        self.assertIn("layer 2 of 3 (%s)" % layer_url(2), rig.note())

    def test_layers_one_and_three_conflicted_names_layer_one(self):
        rig = _Rig(conflicted=[1, 3])

        rig.tick()

        self.assertIn("layer 1 of 3 (%s)" % layer_url(1), rig.note())

    def test_layer_one_conflicted_with_layer_two_clean_names_layer_one(self):
        rig = _Rig(conflicted=[1])

        rig.tick()

        self.assertIn("layer 1 of 3", rig.note())

    def test_a_failed_lower_read_does_not_hide_a_higher_conflict(self):
        rig = _Rig(conflicted=[3], failing_prs=[1])

        rig.tick()

        self.assertIn("layer 3 of 3 (%s)" % layer_url(3), rig.note())

    def test_an_unsettled_layer_with_nothing_else_conflicted_reports_nothing(self):
        rig = _Rig(conflicted=[1], unsettled=[1])

        result = rig.tick()

        self.assertEqual(result.conflicted, [])
        self.assertNotEqual(rig.node().state, "done")

    def test_a_merged_layer_is_excluded_and_position_counts_it(self):
        layers = with_state(build_stack(3), 1, "merged")
        rig = _Rig(conflicted=[1, 2], layers=layers)

        rig.tick()

        self.assertIn("layer 2 of 3 (%s)" % layer_url(2), rig.note())

    def test_an_unread_stack_reports_nothing(self):
        rig = _Rig(conflicted=[2], failing=["stack_view"])

        self.assertEqual(rig.tick().conflicted, [])

    def test_a_dissolved_stack_reports_nothing(self):
        rig = _Rig(conflicted=[2], layers=())

        self.assertEqual(rig.tick().conflicted, [])


class TestBehindOverAStack(unittest.TestCase):
    _STRICT = ["acme/widget@main"]

    def test_behind_on_a_strict_base_reports_with_the_behind_reason(self):
        rig = _Rig(behind=[1], strict=self._STRICT)

        result = rig.tick()

        self.assertEqual(result.conflicted, [rig.item])
        self.assertEqual(rig.node().outcome, "conflicted")
        self.assertIn("layer 1 of 3 (%s) is behind its base" % layer_url(1), rig.note())

    def test_behind_on_a_base_that_is_not_strict_reports_nothing(self):
        rig = _Rig(behind=[1])

        self.assertEqual(rig.tick().conflicted, [])

    def test_a_failing_rule_read_reports_nothing(self):
        rig = _Rig(behind=[1], strict=self._STRICT, failing=["requires_up_to_date"])

        self.assertEqual(rig.tick().conflicted, [])

    def test_behind_and_conflicted_reports_the_conflict(self):
        rig = _Rig(behind=[1], conflicted=[2], strict=self._STRICT)

        rig.tick()

        self.assertIn("layer 2 of 3 (%s) conflicts" % layer_url(2), rig.note())
        self.assertEqual(rig.github.requires_calls, [])

    def test_a_layer_behind_a_feature_branch_reports_nothing(self):
        rig = _Rig(behind=[2], strict=self._STRICT)

        self.assertEqual(rig.tick().conflicted, [])
        self.assertEqual(rig.github.requires_calls, ["acme/widget@layer-1"])


class TestCapsOverAStack(unittest.TestCase):
    def _recorded(self, rig, step_id):
        found = None
        for artifact in rig.store.item_artifacts(step_id):
            if artifact.type == CONFLICT_BASE_TIP:
                found = artifact.value
        return found

    def _resolve(self, rig, step_id):
        fix = next(n for n in rig.store.steps_at_step("fix-step") if n.state != "done")
        rig.complete.execute(
            CompleteInput(step=fix.id, outcome="resolved"))
        return next(n for n in rig.store.steps_at_step("watch-step") if n.state != "done")

    def test_the_recorded_tip_is_the_trunk_tip_even_when_layer_three_is_reported(self):
        rig = _Rig(conflicted=[3], flow=_CAP_FLOW)

        rig.tick()

        self.assertEqual(self._recorded(rig, rig.step), "tip-0")
        self.assertIn(("branch_tip", "acme/widget", "main"), rig.github.calls)

    def test_two_reports_at_the_same_trunk_tip_count_one_failure(self):
        rig = _Rig(conflicted=[3], flow=_CAP_FLOW)
        rig.tick()
        second = self._resolve(rig, rig.step)
        rig.step = second.id

        rig.tick()

        history = [n for n in rig.store.steps_at_step("watch-step")
                   if n.state == "done" and n.outcome == "conflicted"]
        tips = [self._recorded(rig, n.id) for n in history]
        self.assertEqual(tips, ["tip-0", "tip-0"])
        self.assertEqual(pr_conflict_failures(tips[:1], tips[1], 0), 1)

    def test_an_unreadable_lowest_layer_records_no_tip(self):
        rig = _Rig(conflicted=[3], failing_prs=[1], flow=_CAP_FLOW)

        rig.tick()

        self.assertIsNone(self._recorded(rig, rig.step))
        self.assertEqual(rig.node().outcome, "conflicted")

    def test_hitting_the_cap_escalates_with_the_stack_worded_note(self):
        rig = _Rig(conflicted=[2], flow=_CAP_FLOW)
        rig.tick()
        rig.step = self._resolve(rig, rig.step).id
        rig.tick()
        rig.step = self._resolve(rig, rig.step).id

        rig.tick()

        (escalated,) = rig.store.steps_at_step("escalate-step")
        self.assertIn("gh stack rebase", escalated.notes or "")
        self.assertIn("push with a lease", escalated.notes or "")


class TestUnstackedUnchanged(unittest.TestCase):
    def test_a_single_pr_conflict_reports_once_without_a_layer_note(self):
        rig = _Rig(conflicted=[1], stacked=False)

        result = rig.tick()

        self.assertEqual(result.conflicted, [rig.item])
        self.assertNotIn("layer", rig.note())

    def test_an_unstacked_cap_note_keeps_the_branch_wording(self):
        rig = _Rig(conflicted=[1], stacked=False)
        note = rig.dispatch._conflict_cap_note("pr_conflict_cap", 2, 1, "watch-step", "S-1")

        self.assertIn("rebase the branch onto main", note)
