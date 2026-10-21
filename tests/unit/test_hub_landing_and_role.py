import unittest

from lightcycle.adapters.tui.hub import _tab_order, display_role, landing_tab
from lightcycle.application.work.step_focus import ResolveStepFocusInput, ResolveStepFocusUseCase
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.work.step_focus import StepFocus
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


class _FlowStub:
    def __init__(self, presents):
        self._flow = Flow({
            "await-merge": StepDef(owner="human", presents=presents),
            "triage": StepDef(owner="human", presents=presents),
            "review-findings": StepDef(owner="human", presents=presents),
        })

    def flow_for(self, node):
        return self._flow

    def meta_for_step(self, stage, name=None):
        return {}

    def workflow_for(self, node):
        return "w"

    def phase_for(self, node):
        return None


def landing_of(store, node_id, presents=None):
    focus = ResolveStepFocusUseCase(store, _FlowStub(presents)).execute(
        ResolveStepFocusInput(step=node_id)).focus
    return landing_tab(focus)


class TestLandingTab(unittest.TestCase):
    def test_each_focus_maps_to_its_tab(self):
        expected = {
            "log": "log", "reason": "detail", "detail": "detail", "context": "context",
            "workflow": "workflow", "description": "description",
        }
        for kind, tab in expected.items():
            self.assertEqual(landing_tab(StepFocus(kind)), tab, kind)

    def test_item_lands_on_description(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertEqual(landing_of(s, item), "description")

    def test_active_step_lands_on_log(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(landing_of(s, step), "log")

    def test_waiting_await_merge_step_with_no_pr_yet_falls_to_context(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="await-merge", role="human")
        self.assertEqual(landing_of(s, step, presents="pr"), "context")

    def test_waiting_human_step_presenting_description_lands_on_detail_description(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="triage", role="human")
        self.assertEqual(landing_of(s, step, presents="description"), "detail")

    def test_dependency_blocked_step_lands_on_detail(self):
        s = FakeStore()
        blocker = create_owned_step(s, "b", stage="build", role="agent")
        step = create_owned_step(s, "s", stage="build", role="agent", deps=[blocker])
        self.assertEqual(landing_of(s, step), "detail")

    def test_queued_step_with_a_report_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="build", role="agent")
        s.set_report(step, "a report")
        self.assertEqual(landing_of(s, step), "detail")

    def test_done_step_with_a_report_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="build", role="agent")
        s.set_report(step, "a report")
        s.complete_node(step, "done")
        self.assertEqual(landing_of(s, step), "detail")

    def test_waiting_gate_presenting_findings_it_does_not_have_falls_to_context(self):
        s = FakeStore()
        step = create_owned_step(s, "s", stage="review-findings", role="human")
        s.add_artifact(step, "findings", "text")
        self.assertEqual(landing_of(s, step, presents="artifact:findings"), "context")


class TestStepTabOrder(unittest.TestCase):
    def test_every_step_shows_the_same_five_tabs(self):
        s = FakeStore()
        for role, stage in (("human", "await-merge"), ("agent", "build"), ("engine", "script")):
            step = create_owned_step(s, "s-" + role, stage=stage, role=role)
            self.assertEqual(
                _tab_order(s.get_node(step)), ("detail", "context", "workflow", "log", "cost"), role
            )

    def test_item_tabs_are_unchanged(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertEqual(
            _tab_order(s.get_node(item)), ("description", "outputs", "workflow", "cost"))


class TestDisplayRole(unittest.TestCase):
    def test_human_role_shown_as_human(self):
        self.assertEqual(display_role("human"), "human")

    def test_missing_role_falls_back_to_human(self):
        self.assertEqual(display_role(None), "human")

    def test_agent_role_shown_as_is(self):
        self.assertEqual(display_role("write-code"), "write-code")


if __name__ == "__main__":
    unittest.main()
