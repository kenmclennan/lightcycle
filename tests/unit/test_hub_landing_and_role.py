import unittest

from lightcycle.adapters.tui.hub import display_role, landing_tab
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


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

    def test_needs_attention_human_step_lands_on_detail(self):
        s = FakeStore()
        step = create_owned_step(s, "s", step="await-merge", role="human")
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


class TestDisplayRole(unittest.TestCase):
    def test_human_role_shown_as_human(self):
        self.assertEqual(display_role("human"), "human")

    def test_missing_role_falls_back_to_human(self):
        self.assertEqual(display_role(None), "human")

    def test_agent_role_shown_as_is(self):
        self.assertEqual(display_role("write-code"), "write-code")


if __name__ == "__main__":
    unittest.main()
