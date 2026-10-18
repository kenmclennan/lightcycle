import unittest

from lightcycle.application.work.step_focus import ResolveStepFocusInput, ResolveStepFocusUseCase
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.work import State
from lightcycle.domain.work.step_focus import (
    FOCUS_ARTIFACT,
    FOCUS_DESCRIPTION,
    FOCUS_PR,
    FocusFacts,
    StepFocus,
    parse_presents,
    resolve_focus,
)
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


def focus_of(**facts):
    focus = resolve_focus(FocusFacts(**facts))
    return "%s:%s" % (focus.kind, focus.name) if focus.name else focus.kind


class TestResolveFocus(unittest.TestCase):
    def test_an_item_focuses_its_description(self):
        self.assertEqual(focus_of(is_item=True), "description")

    def test_a_running_agent_step_focuses_its_log(self):
        self.assertEqual(focus_of(state=State.RUNNING, role="agent"), "log")

    def test_a_running_script_is_a_queued_engine_step_with_a_log(self):
        self.assertEqual(focus_of(state=State.QUEUED, role="engine", has_log=True), "log")

    def test_a_blocked_step_focuses_its_reason_entry(self):
        self.assertEqual(
            focus_of(state=State.BLOCKED, role="agent", has_reason=True), "reason:reason")

    def test_a_parked_step_without_a_reason_focuses_its_needs_entry(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="agent", parked=True), "reason:needs")

    def test_a_parked_waiting_gate_focuses_its_reason_over_what_it_presents(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", presents_key="pr", parked=True,
                     has_reason=True),
            "reason:reason")

    def test_a_waiting_gate_lands_on_the_detail_entry_it_presents(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", presents_key="in:findings"),
            "detail:in:findings")

    def test_a_waiting_gate_presenting_description_lands_on_the_description_input(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", presents_key="in:description"),
            "detail:in:description")

    def test_a_gate_whose_presented_entry_is_null_falls_past_the_presents_rule(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", first_value_key="outcome"),
            "detail:outcome")

    def test_a_done_step_with_a_pr_lands_on_the_pr_entry(self):
        self.assertEqual(
            focus_of(state=State.DONE, role="agent", has_pr=True, produced_outputs=("summary",)),
            "detail:pr")

    def test_a_done_step_with_outputs_lands_on_the_first_in_context(self):
        self.assertEqual(
            focus_of(state=State.DONE, role="agent", produced_outputs=("summary", "notes"),
                     first_value_key="outcome"),
            "context:summary")

    def test_a_done_step_producing_nothing_lands_on_the_first_valued_entry(self):
        self.assertEqual(
            focus_of(state=State.DONE, role="agent", first_value_key="outcome"), "detail:outcome")

    def test_a_done_gate_ignores_what_it_presented(self):
        self.assertEqual(
            focus_of(state=State.DONE, role="human", presents_key="in:description",
                     first_value_key="outcome"),
            "detail:outcome")

    def test_a_queued_engine_step_without_a_log_falls_through(self):
        self.assertEqual(
            focus_of(state=State.QUEUED, role="engine", first_value_key="outcome"),
            "detail:outcome")

    def test_a_queued_agent_step_falls_through(self):
        self.assertEqual(
            focus_of(state=State.QUEUED, role="agent", first_value_key="outcome"),
            "detail:outcome")

    def test_with_no_valued_entry_it_falls_to_context(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", context_rows=3), "context")

    def test_with_nothing_at_all_it_falls_to_workflow(self):
        self.assertEqual(focus_of(state=State.WAITING, role="human"), "workflow")


class TestPresentsParsing(unittest.TestCase):
    def test_the_three_forms_parse(self):
        self.assertEqual(parse_presents("pr"), StepFocus(FOCUS_PR))
        self.assertEqual(parse_presents("description"), StepFocus(FOCUS_DESCRIPTION))
        self.assertEqual(parse_presents("artifact:findings"), StepFocus(FOCUS_ARTIFACT, "findings"))

    def test_anything_else_does_not_parse(self):
        for bad in ("log", "artifact:", "artifact", "tab:pr", ""):
            self.assertIsNone(parse_presents(bad), bad)


class FlowStub:
    def __init__(self, presents=None, produced=None, detail=None):
        self._flow = Flow({"gate": StepDef(owner="human", presents=presents, detail=detail)})
        self._meta = {"produces": produced} if produced else {}

    def flow_for(self, node):
        return self._flow

    def meta_for_step(self, stage, name=None):
        return self._meta

    def workflow_for(self, node):
        return "w"

    def phase_for(self, node):
        return None


def resolve(store, step, flow):
    focus = ResolveStepFocusUseCase(store, flow).execute(ResolveStepFocusInput(step=step)).focus
    return "%s:%s" % (focus.kind, focus.name) if focus.name else focus.kind


class TestResolveStepFocusUseCase(unittest.TestCase):
    def test_an_item_resolves_to_description(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertEqual(resolve(s, item, FlowStub()), "description")

    def test_a_gate_presenting_a_declared_output_of_a_sibling_step_lands_on_its_input_entry(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="gate", role="human")
        sibling = s.create_step(step="audit", role="agent", parent=s.get_node(step).item)
        s.add_artifact(sibling, "findings", "text")
        flow = FlowStub(presents="artifact:findings", produced={"findings": "optional"})
        self.assertEqual(resolve(s, step, flow), "detail:in:findings")

    def test_a_gate_declaring_detail_lands_on_its_presents_entry(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="gate", role="human")
        sibling = s.create_step(step="audit", role="agent", parent=s.get_node(step).item)
        s.add_artifact(sibling, "findings", "text")
        flow = FlowStub(
            presents="artifact:findings", produced={"findings": "optional"},
            detail=("outcome", "in:findings"))
        self.assertEqual(resolve(s, step, flow), "detail:in:findings")

    def test_a_gate_presenting_an_artifact_not_yet_attached_falls_past_it(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="gate", role="human")
        self.assertNotEqual(
            resolve(s, step, FlowStub(presents="artifact:findings")), "detail:in:findings")

    def test_a_running_agent_step_resolves_to_log(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(resolve(s, step, FlowStub()), "log")

    def test_a_queued_engine_step_with_a_log_path_resolves_to_log(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="script", role="engine")
        s.set_log(step, "/tmp/x.log")
        self.assertEqual(resolve(s, step, FlowStub()), "log")

    def test_a_done_step_producing_an_attached_artifact_lands_on_it_in_context(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.add_artifact(step, "summary", "text")
        s.complete_node(step, "done")
        self.assertEqual(
            resolve(s, step, FlowStub(produced={"summary": "required"})), "context:summary")

    def test_a_dependency_blocked_step_resolves_to_reason(self):
        s = FakeStore()
        blocker = create_owned_step(s, "b", step="build", role="agent")
        step = create_owned_step(s, "s", step="build", role="agent", deps=[blocker])
        self.assertEqual(resolve(s, step, FlowStub()).split(":")[0], "reason")
