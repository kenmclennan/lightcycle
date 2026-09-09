import unittest

from lightcycle.adapters.tui.hub import COST_NOT_RECORDED, hierarchy_usage_text
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


class TestHierarchyUsageText(unittest.TestCase):
    def test_a_human_step_is_blank_for_both_turns_and_cost(self):
        store = FakeStore()
        step = create_owned_step(store, "await merge", step="code-await-merge", role="human")
        node = store.get_node(step)

        self.assertEqual(hierarchy_usage_text(node), ("", ""))

    def test_an_item_root_is_blank_for_both_turns_and_cost(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        node = store.get_node(item)

        self.assertEqual(hierarchy_usage_text(node), ("", ""))

    def test_an_agent_step_that_has_not_run_is_blank_for_both(self):
        store = FakeStore()
        step = create_owned_step(store, "queued build", step="build", role="agent")
        node = store.get_node(step)

        self.assertEqual(hierarchy_usage_text(node), ("", ""))

    def test_an_agent_step_with_turns_but_no_recorded_cost_shows_turns_and_the_not_recorded_placeholder(
        self,
    ):
        store = FakeStore()
        step = create_owned_step(store, "building", step="build", role="agent")
        store.record_attribution(step, 246, {})
        node = store.get_node(step)

        self.assertEqual(hierarchy_usage_text(node), ("246 turns", COST_NOT_RECORDED))

    def test_an_agent_step_with_recorded_cost_shows_both_turns_and_cost(self):
        store = FakeStore()
        step = create_owned_step(store, "building", step="build", role="agent")
        store.record_usage(step, 100, 10, 0, 0, 2.91, "list", None)
        store.record_attribution(step, 50, {})
        node = store.get_node(step)

        self.assertEqual(hierarchy_usage_text(node), ("50 turns", "$2.91"))

    def test_an_agent_step_with_a_recorded_basis_but_zero_cost_shows_the_not_recorded_placeholder(
        self,
    ):
        store = FakeStore()
        step = create_owned_step(store, "building", step="build", role="agent")
        store.record_usage(step, 0, 0, 0, 0, 0.0, "list", None)
        store.record_attribution(step, 50, {})
        node = store.get_node(step)

        self.assertEqual(hierarchy_usage_text(node), ("50 turns", COST_NOT_RECORDED))

    def test_a_single_turn_is_singular(self):
        store = FakeStore()
        step = create_owned_step(store, "building", step="build", role="agent")
        store.record_attribution(step, 1, {})
        node = store.get_node(step)

        self.assertEqual(hierarchy_usage_text(node), ("1 turn", COST_NOT_RECORDED))


if __name__ == "__main__":
    unittest.main()
