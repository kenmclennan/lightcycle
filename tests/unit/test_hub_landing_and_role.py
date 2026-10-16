import unittest

from lightcycle.adapters.tui.hub import NodeHubScreen, _tab_order, display_role, landing_tab
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step
from tests.support.tui_harness import launch, make_test_container


class TestLandingTab(unittest.TestCase):
    def test_item_lands_on_description(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        self.assertEqual(landing_tab(s.get_node(item)), "description")

    def test_active_step_lands_on_log(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.claim_ready("agent")
        self.assertEqual(landing_tab(s.get_node(step)), "log")

    def test_waiting_human_step_lands_on_description(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="await-merge", role="human")
        self.assertEqual(landing_tab(s.get_node(step)), "description")

    def test_done_human_step_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="await-merge", role="human")
        s.complete_node(step, "done")
        self.assertEqual(landing_tab(s.get_node(step)), "detail")

    def test_dependency_blocked_step_lands_on_detail(self):
        s = FakeStore()
        blocker = create_owned_step(s, "b", step="build", role="agent")
        step = create_owned_step(s, "s", step="build", role="agent", deps=[blocker])
        self.assertEqual(landing_tab(s.get_node(step)), "detail")

    def test_queued_step_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        self.assertEqual(landing_tab(s.get_node(step)), "detail")

    def test_done_step_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="build", role="agent")
        s.complete_node(step, "done")
        self.assertEqual(landing_tab(s.get_node(step)), "detail")


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
