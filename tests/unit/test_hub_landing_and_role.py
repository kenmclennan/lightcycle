import unittest
from types import SimpleNamespace

from lightcycle.adapters.tui.hub import NodeHubScreen, _tab_order, detail_fields, display_role, landing_tab
from lightcycle.application.work.step_detail import StepDetail
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.application.work.step_focus import ResolveStepFocusInput, ResolveStepFocusUseCase
from lightcycle.domain.flow import Flow
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.work.step_focus import FOCUS_ARTIFACT, StepFocus
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step
from tests.support.tui_harness import launch, make_test_container


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
            "log": "log", "reason": "detail", "pr": "detail", "detail": "detail",
            "description": "description",
        }
        for kind, tab in expected.items():
            self.assertEqual(landing_tab(StepFocus(kind)), tab, kind)
        self.assertEqual(landing_tab(StepFocus(FOCUS_ARTIFACT, "findings")), "artifacts")

    def test_item_lands_on_description(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertEqual(landing_of(s, item), "description")

    def test_active_step_lands_on_log(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(landing_of(s, step), "log")

    def test_waiting_await_merge_step_declaring_pr_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="await-merge", role="human")
        self.assertEqual(landing_of(s, step, presents="pr"), "detail")

    def test_waiting_human_step_with_only_stage_state_role_lands_on_description(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="triage", role="human")
        step_inputs = StepInputs(s, _FlowStub(None))
        entries, _presents = StepDetail(s, _FlowStub(None)).resolve(
            s.get_node(step), step_inputs.read(s.get_node(step)),
            step_inputs.entry_dicts_for_step(s.get_node(step)),
            run=SimpleNamespace(pr=None, branch=None))
        fields = detail_fields(entries)
        self.assertEqual(fields, [("outcome", ""), ("report", "")])
        self.assertEqual(landing_of(s, step), "description")

    def test_done_human_step_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="await-merge", role="human")
        s.complete_node(step, "done")
        self.assertEqual(landing_of(s, step, presents="pr"), "detail")

    def test_dependency_blocked_step_lands_on_detail(self):
        s = FakeStore()
        blocker = create_owned_step(s, "b", step="build", role="agent")
        step = create_owned_step(s, "s", step="build", role="agent", deps=[blocker])
        self.assertEqual(landing_of(s, step), "detail")

    def test_queued_step_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        self.assertEqual(landing_of(s, step), "detail")

    def test_done_step_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.complete_node(step, "done")
        self.assertEqual(landing_of(s, step), "detail")

    def test_waiting_gate_presenting_a_findings_artifact_lands_on_artifacts(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="review-findings", role="human")
        s.add_artifact(step, "findings", "text")
        self.assertEqual(landing_of(s, step, presents="artifact:findings"), "artifacts")


class TestStepTabOrder(unittest.TestCase):
    def test_human_step_tabs_start_with_description(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="await-merge", role="human")
        self.assertEqual(
            _tab_order(s.get_node(step)), ("description", "detail", "workflow", "log", "cost")
        )

    def test_agent_step_tabs_are_unchanged(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        self.assertEqual(_tab_order(s.get_node(step)), ("detail", "workflow", "log", "cost"))


class TestHumanStepDescriptionTab(unittest.TestCase):
    def _hub(self, store, step):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        session.run(
            lambda: session.app.push_screen(
                NodeHubScreen(session.app.container, step, session.app._now)
            )
        )
        session.pause()
        return session.app.screen

    def test_waiting_human_step_shows_parent_item_description(self):
        s = FakeStore()
        item = s.create_item("item", "triage these issues", shortcode="OWN")
        step = s.create_step(step="triage", role="human", parent=item)
        screen = self._hub(s, step)
        self.assertEqual(screen._active_tab, "description")
        self.assertEqual(screen._description_text, "triage these issues")

    def test_empty_item_description_shows_empty_message(self):
        s = FakeStore()
        item = s.create_item("item", "", shortcode="OWN")
        step = s.create_step(step="triage", role="human", parent=item)
        screen = self._hub(s, step)
        self.assertFalse(screen._has_description)


class TestDisplayRole(unittest.TestCase):
    def test_human_role_shown_as_human(self):
        self.assertEqual(display_role("human"), "human")

    def test_missing_role_falls_back_to_human(self):
        self.assertEqual(display_role(None), "human")

    def test_agent_role_shown_as_is(self):
        self.assertEqual(display_role("write-code"), "write-code")


if __name__ == "__main__":
    unittest.main()
