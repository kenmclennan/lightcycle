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
    return str(resolve_focus(FocusFacts(**facts)))


class TestResolveFocus(unittest.TestCase):
    def test_an_item_focuses_its_description(self):
        self.assertEqual(focus_of(is_item=True), "description")

    def test_a_running_agent_step_focuses_its_log(self):
        self.assertEqual(focus_of(state=State.RUNNING, role="agent"), "log")

    def test_a_running_script_is_a_queued_engine_step_with_a_log(self):
        self.assertEqual(focus_of(state=State.QUEUED, role="engine", has_log=True), "log")

    def test_a_queued_engine_step_without_a_log_falls_back_to_detail(self):
        self.assertEqual(focus_of(state=State.QUEUED, role="engine"), "detail")

    def test_a_blocked_step_focuses_its_reason(self):
        self.assertEqual(focus_of(state=State.BLOCKED, role="agent"), "reason")

    def test_a_parked_waiting_step_focuses_its_reason(self):
        self.assertEqual(focus_of(state=State.WAITING, role="agent", parked=True), "reason")

    def test_a_parked_waiting_gate_focuses_its_reason_over_what_it_presents(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", presents="pr", parked=True), "reason")

    def test_a_waiting_gate_presenting_pr_focuses_the_pr(self):
        self.assertEqual(focus_of(state=State.WAITING, role="human", presents="pr"), "pr")

    def test_a_waiting_gate_presenting_description_focuses_the_description(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", presents="description"), "description")

    def test_a_waiting_gate_presenting_an_attached_artifact_focuses_it(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", presents="artifact:findings",
                     artifact_types=frozenset(("findings",))),
            "artifact:findings")

    def test_a_done_step_producing_pr_with_a_pr_focuses_the_pr(self):
        self.assertEqual(focus_of(state=State.DONE, role="agent", produced=("pr",), has_pr=True), "pr")

    def test_a_done_step_producing_an_attached_type_focuses_the_artifact(self):
        self.assertEqual(
            focus_of(state=State.DONE, role="agent", produced=("summary",),
                     artifact_types=frozenset(("summary",))),
            "artifact:summary")

    def test_a_done_step_producing_nothing_focuses_detail(self):
        self.assertEqual(focus_of(state=State.DONE, role="agent"), "detail")

    def test_a_done_step_whose_produced_type_is_not_attached_focuses_detail(self):
        self.assertEqual(focus_of(state=State.DONE, role="agent", produced=("summary",)), "detail")

    def test_a_done_step_with_two_produced_types_resolves_to_the_attached_second(self):
        self.assertEqual(
            focus_of(state=State.DONE, role="agent", produced=("pr", "summary"),
                     artifact_types=frozenset(("summary",))),
            "artifact:summary")

    def test_a_done_step_with_neither_produced_type_attached_focuses_detail(self):
        self.assertEqual(
            focus_of(state=State.DONE, role="agent", produced=("pr", "summary")), "detail")

    def test_a_done_gate_ignores_what_it_presented(self):
        self.assertEqual(focus_of(state=State.DONE, role="human", presents="description"), "detail")


class TestFallback(unittest.TestCase):
    def test_a_gate_declaring_nothing_with_bare_detail_focuses_the_description(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", bare_detail=True), "description")

    def test_a_gate_declaring_nothing_with_more_detail_focuses_detail(self):
        self.assertEqual(focus_of(state=State.WAITING, role="human"), "detail")

    def test_a_gate_presenting_an_unattached_artifact_takes_the_same_fallback(self):
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", presents="artifact:X", bare_detail=True),
            "description")
        self.assertEqual(
            focus_of(state=State.WAITING, role="human", presents="artifact:X"), "detail")

    def test_a_queued_agent_step_focuses_detail(self):
        self.assertEqual(focus_of(state=State.QUEUED, role="agent"), "detail")


class TestPresentsParsing(unittest.TestCase):
    def test_the_three_forms_parse(self):
        self.assertEqual(parse_presents("pr"), StepFocus(FOCUS_PR))
        self.assertEqual(parse_presents("description"), StepFocus(FOCUS_DESCRIPTION))
        self.assertEqual(parse_presents("artifact:findings"), StepFocus(FOCUS_ARTIFACT, "findings"))

    def test_anything_else_does_not_parse(self):
        for bad in ("log", "artifact:", "artifact", "tab:pr", ""):
            self.assertIsNone(parse_presents(bad), bad)


class FlowStub:
    def __init__(self, presents=None, produced=None):
        self._flow = Flow({"gate": StepDef(owner="human", presents=presents)})
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
    return ResolveStepFocusUseCase(store, flow).execute(ResolveStepFocusInput(step=step)).focus


class TestResolveStepFocusUseCase(unittest.TestCase):
    def test_an_item_resolves_to_description(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertEqual(str(resolve(s, item, FlowStub())), "description")

    def test_a_waiting_gate_presenting_description_resolves_to_it(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="gate", role="human")
        self.assertEqual(str(resolve(s, step, FlowStub(presents="description"))), "description")

    def test_a_gate_presenting_a_declared_output_of_a_sibling_step_resolves_to_it(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="gate", role="human")
        sibling = s.create_step(step="audit", role="agent", parent=s.get_node(step).item)
        s.add_artifact(sibling, "findings", "text")
        flow = FlowStub(presents="artifact:findings", produced={"findings": "optional"})
        self.assertEqual(str(resolve(s, step, flow)), "artifact:findings")

    def test_a_gate_presenting_an_undeclared_attach_on_a_sibling_falls_back_to_description(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="gate", role="human")
        sibling = s.create_step(step="audit", role="agent", parent=s.get_node(step).item)
        s.add_artifact(sibling, "findings", "text")
        self.assertEqual(
            str(resolve(s, step, FlowStub(presents="artifact:findings"))), "description")

    def test_a_gate_presenting_an_artifact_not_yet_attached_falls_back_to_description(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="gate", role="human")
        self.assertEqual(
            str(resolve(s, step, FlowStub(presents="artifact:findings"))), "description")

    def test_a_running_agent_step_resolves_to_log(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(str(resolve(s, step, FlowStub())), "log")

    def test_a_queued_engine_step_with_a_log_path_resolves_to_log(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="script", role="engine")
        s.set_log(step, "/tmp/x.log")
        self.assertEqual(str(resolve(s, step, FlowStub())), "log")

    def test_a_done_step_producing_an_attached_artifact_resolves_to_it(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.add_artifact(step, "summary", "text")
        s.complete_node(step, "done")
        self.assertEqual(
            str(resolve(s, step, FlowStub(produced={"summary": "required"}))), "artifact:summary")

    def test_a_done_step_producing_nothing_resolves_to_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.complete_node(step, "done")
        self.assertEqual(str(resolve(s, step, FlowStub())), "detail")

    def test_a_dependency_blocked_step_resolves_to_reason(self):
        s = FakeStore()
        blocker = create_owned_step(s, "b", step="build", role="agent")
        step = create_owned_step(s, "s", step="build", role="agent", deps=[blocker])
        self.assertEqual(str(resolve(s, step, FlowStub())), "reason")
