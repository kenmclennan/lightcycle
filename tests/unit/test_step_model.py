from tests.support.fake_github_budget import FakeGithubBudget
import json
import unittest

from lightcycle.application.flow import ClaimInput, ClaimStepUseCase, CompleteInput, CompleteStepUseCase
from lightcycle.application.work import ShowNodeInput, ShowNodeUseCase
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.domain.pool import Worker
from tests.support.fake_store import FakeStore
from tests.unit.test_flow_usecases import FakeConfig, FakeWorkers, FakeWorktrees, flow_for

METAS = {
    "coder": {
        "model": "sonnet", "step": "build",
        "produces": {"X": "required"}, "routes": {"done": "review"},
    },
    "reviewer": {
        "model": "opus", "step": "review", "accepts": {"X": "required"},
        "detail": "[outcome, in:X, in:report]", "routes": {"done": "gate"},
    },
    "gater": {"step": "gate", "accepts": {"X": "optional"}},
}


class Rig:
    def __init__(self, metas=None, spawn=None):
        self.store = FakeStore()
        self.flow = flow_for(metas or METAS, self.store)
        self.workers = FakeWorkers()
        self.config = FakeConfig(spawn=spawn)
        self.item = self.store.create_item("t", "the brief", workflow="spec-driven", shortcode="APP")
        self.complete = CompleteStepUseCase(self.store, self.flow)

    def claim_uc(self):
        return ClaimStepUseCase(
            self.store, self.flow, FakeWorktrees(), self.workers, self.config, FakeGithubBudget())

    def first_step(self, stage="build", role="agent"):
        return self.store.create_step(step=stage, role=role, parent=self.item)

    def claim(self):
        return self.claim_uc().execute(ClaimInput(role="agent"))

    def show(self, step):
        return ShowNodeUseCase(self.store, self.flow).execute(ShowNodeInput(step=step)).surface

    def close_build(self, step, note="the report", value="v1"):
        self.store.claim_ready("agent")
        self.store.add_artifact(step, "X", value)
        return self.complete.execute(CompleteInput(step=step, outcome="done", note=note)).next_step


class TestReportAndPredecessor(unittest.TestCase):
    def test_the_note_is_the_closing_steps_report_and_not_the_next_steps_notes(self):
        rig = Rig()
        build = rig.first_step()
        review = rig.close_build(build)
        closed = rig.store.get_node(build)
        self.assertEqual(closed.report, "the report")
        self.assertIn("outcome: done", closed.notes)
        self.assertNotIn("the report", closed.notes)
        self.assertIsNone(rig.store.get_node(review).notes)
        self.assertEqual(rig.store.get_node(review).previous_step, build)

    def test_a_hand_created_step_records_no_predecessor(self):
        rig = Rig()
        self.assertIsNone(rig.store.get_node(rig.first_step()).previous_step)

    def test_show_gives_the_report_under_outputs_and_the_shim_in_notes(self):
        rig = Rig()
        build = rig.first_step()
        review = rig.close_build(build)
        self.assertEqual(rig.show(build)["outputs"]["report"], "the report")
        surface = rig.show(review)
        self.assertEqual(surface["notes"], "from build (done): the report")
        self.assertEqual(surface["inputs"]["previous"]["report"], "the report")
        self.assertIsNone(rig.store.get_node(review).notes)

    def test_a_pre_0_7_forwarded_note_is_not_doubled_by_the_shim(self):
        rig = Rig()
        build = rig.first_step()
        review = rig.close_build(build)
        rig.store.set_notes(review, "from build (done): legacy text")
        self.assertEqual(rig.show(review)["notes"], "from build (done): legacy text")


class TestInputs(unittest.TestCase):
    def test_a_claim_lists_the_producing_steps_output_and_report(self):
        rig = Rig()
        build = rig.first_step()
        review = rig.close_build(build)
        response = rig.claim()
        self.assertEqual(response.view.step.id, review)
        inputs = response.surface["inputs"]
        item_x = [e for e in inputs["item"] if e["name"] == "X"]
        self.assertEqual([(e["value"], e["step"]) for e in item_x], [("v1", build)])
        self.assertEqual(inputs["previous"]["step"], build)
        self.assertEqual([e["value"] for e in inputs["previous"]["outputs"]], ["v1"])
        self.assertEqual(inputs["previous"]["report"], "the report")
        self.assertTrue(inputs["frozen"])
        self.assertEqual(inputs["context"]["description"], "the brief")

    def test_the_declared_output_satisfies_the_claims_accepts_check(self):
        rig = Rig()
        build = rig.first_step()
        rig.close_build(build)
        self.assertIsNotNone(rig.claim())

    def test_inputs_are_identical_after_a_newer_version_and_an_edited_description(self):
        rig = Rig()
        build = rig.first_step()
        review = rig.close_build(build)
        rig.claim()
        before = rig.show(review)["inputs"]
        rig.store.edit_node(rig.item, description="changed")
        other = rig.first_step()
        rig.store.add_artifact(other, "X", "v2")
        after = rig.show(review)["inputs"]
        self.assertEqual(before, after)
        self.assertEqual(after["context"]["description"], "the brief")

    def test_a_newer_version_is_current_and_the_older_is_history_in_a_later_claim(self):
        rig = Rig()
        build = rig.first_step()
        rig.close_build(build)
        rework = rig.first_step()
        rig.store.add_artifact(rework, "X", "v2")
        outputs = StepInputs(rig.store, rig.flow).build(rig.store.get_node(rework))
        x = [e for e in outputs["item"] if e["name"] == "X"][0]
        self.assertEqual(x["value"], "v2")
        self.assertEqual([h["value"] for h in x["history"]], ["v1"])

    def test_a_never_claimed_step_returns_live_inputs_unfrozen(self):
        rig = Rig()
        step = rig.first_step()
        inputs = rig.show(step)["inputs"]
        self.assertFalse(inputs["frozen"])
        self.assertEqual(inputs["context"]["description"], "the brief")

    def test_a_closed_step_with_no_frozen_row_returns_reconstructed_inputs_without_storing_a_row(self):
        rig = Rig()
        step = rig.first_step()
        rig.store.claim_ready("agent")
        rig.store.add_artifact(step, "X", "v")
        rig.complete.execute(CompleteInput(step=step, outcome="done"))
        self.assertIsNone(rig.store.step_inputs(step))
        inputs = rig.show(step)["inputs"]
        self.assertFalse(inputs["frozen"])
        self.assertIsNone(inputs["frozen_at"])
        self.assertEqual(inputs["context"]["description"], "the brief")
        self.assertIsNone(rig.store.step_inputs(step))

    def test_a_closed_step_with_a_frozen_row_returns_the_row(self):
        rig = Rig()
        build = rig.first_step()
        review = rig.close_build(build)
        rig.claim()
        rig.complete.execute(CompleteInput(step=review, outcome="done"))
        row = rig.store.step_inputs(review)
        inputs = rig.show(review)["inputs"]
        self.assertTrue(inputs["frozen"])
        self.assertEqual(inputs["frozen_at"], row[0])
        self.assertEqual(rig.store.step_inputs(review), row)

    def test_a_human_step_created_by_a_transition_has_frozen_inputs(self):
        rig = Rig()
        build = rig.first_step()
        review = rig.close_build(build)
        rig.claim()
        rig.store.add_artifact(review, "X", "v1b")
        gate = rig.complete.execute(CompleteInput(step=review, outcome="done")).next_step
        self.assertIsNotNone(rig.store.step_inputs(gate))
        self.assertTrue(rig.show(gate)["inputs"]["frozen"])

    def test_a_reclaim_then_a_fresh_claim_replaces_the_row_but_a_resume_does_not(self):
        rig = Rig(spawn="sp1")
        build = rig.first_step()
        review = rig.close_build(build)
        rig.claim()
        first = rig.store.step_inputs(review)
        rig.store.edit_node(rig.item, description="changed")
        resumed = rig.claim()
        self.assertEqual(resumed.view.step.id, review)
        self.assertEqual(rig.store.step_inputs(review), first)
        rig.store.reclaim(review)
        rig.workers = FakeWorkers()
        rig.claim()
        replaced = json.loads(rig.store.step_inputs(review)[1])
        self.assertEqual(replaced["context"]["description"], "changed")

    def test_records_and_bookkeeping_stay_out_of_outputs_and_inputs(self):
        rig = Rig()
        build = rig.first_step()
        rig.store.claim_ready("agent")
        rig.store.add_artifact(build, "X", "v1")
        rig.store.add_artifact(build, "reflection", "note", internal=True)
        rig.store.add_artifact(build, "session-id", "abc", internal=True)
        rig.store.add_artifact(build, "checks-run", "ok")
        rig.complete.execute(CompleteInput(step=build, outcome="done"))
        surface = rig.show(build)
        self.assertEqual([a["name"] for a in surface["outputs"]["artifacts"]], ["X"])
        self.assertEqual(
            sorted(r["type"] for r in surface["records"]), ["checks-run", "reflection"])


class TestDetail(unittest.TestCase):
    def test_a_declared_detail_returns_exactly_those_entries(self):
        rig = Rig()
        build = rig.first_step()
        review = rig.close_build(build)
        rig.claim()
        surface = rig.show(review)
        self.assertEqual(
            [(e["key"], e["kind"]) for e in surface["detail"]],
            [("outcome", "field"), ("in:X", "input"), ("in:report", "input")])
        values = {e["key"]: e["value"] for e in surface["detail"]}
        self.assertEqual(values["in:X"], "v1")
        self.assertEqual(values["in:report"], "the report")
        self.assertEqual(surface["detail_presents"], "outcome")

    def test_a_step_without_detail_gets_the_default_list(self):
        rig = Rig()
        build = rig.first_step()
        surface = rig.show(build)
        self.assertEqual([e["key"] for e in surface["detail"]], ["outcome", "report"])

    def test_a_parked_step_leads_with_reason_and_needs(self):
        rig = Rig()
        build = rig.first_step()
        rig.store.update_metadata(build, {"needs": "n", "reason": "r"})
        keys = [e["key"] for e in rig.show(build)["detail"]]
        self.assertEqual(keys, ["reason", "needs", "outcome", "report"])


class TestLog(unittest.TestCase):
    def test_a_pool_claim_records_the_workers_log_and_a_manual_claim_none(self):
        rig = Rig(spawn="sp1")
        rig.workers.state = [Worker(spawnid="sp1", log="/logs/w.log")]
        step = rig.first_step()
        rig.claim()
        self.assertEqual(rig.store.get_node(step).log_path, "/logs/w.log")
        manual = Rig()
        other = manual.first_step()
        manual.claim()
        self.assertIsNone(manual.store.get_node(other).log_path)
        self.assertEqual(manual.show(other)["log"], None)


class TestItemOutputs(unittest.TestCase):
    def test_lc_show_item_returns_outputs_with_history_and_pass(self):
        rig = Rig()
        build = rig.first_step()
        rig.close_build(build)
        rework = rig.first_step()
        rig.store.add_artifact(rework, "X", "v2")
        outputs = rig.show(rig.item)["outputs"]["artifacts"]
        x = [e for e in outputs if e["name"] == "X"][0]
        self.assertEqual(x["value"], "v2")
        self.assertEqual(x["step"], rework)
        self.assertEqual([h["value"] for h in x["history"]], ["v1"])


if __name__ == "__main__":
    unittest.main()
