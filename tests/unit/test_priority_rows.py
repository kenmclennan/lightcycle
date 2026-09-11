import unittest

from lightcycle.application.work.priority_rows import select_priority_rows
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step

_FLOW = flow_from_metas(
    {
        "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
        "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    }
)


class _FixedFlowService:
    def flow_for(self, node):
        return _FLOW


class TestSelectPriorityRowsDedupe(unittest.TestCase):
    def test_a_node_already_selected_in_attention_is_not_selected_again_in_active_or_queued(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        gate = store.create_step("await merge", step="ready-merge", role="human", parent=item)
        active_sibling = store.create_step("building", step="build", role="agent", parent=item)
        lanes = {
            "inbox": [store.get_node(gate)],
            "active": [store.get_node(active_sibling)],
            "queue": [],
        }

        selection = select_priority_rows(store, lanes, _FixedFlowService())

        self.assertEqual(len(selection.attention), 1)
        self.assertEqual(selection.active, [])
        self.assertEqual(selection.queued, [])

    def test_escalation_sorts_before_gate_regardless_of_lane_order(self):
        store = FakeStore()
        gate = create_owned_step(store, "await merge", step="ready-merge", role="human")
        escalation = create_owned_step(store, "stuck build", step="build", role="human")
        lanes = {
            "inbox": [store.get_node(gate), store.get_node(escalation)],
            "active": [],
            "queue": [],
        }

        selection = select_priority_rows(store, lanes, _FixedFlowService())

        self.assertEqual(
            [s.node.id for s in selection.attention], [escalation, gate]
        )

    def test_a_mixed_lane_selects_the_resolvable_ones_and_leaves_the_rest_out(self):
        store = FakeStore()
        item_a = store.create_item("a", "a description")
        item_b = store.create_item("b", "a description")
        step_a = store.create_step("building", step="build", role="agent", parent=item_a)
        step_b1 = store.create_step("s1", step="build", role="agent", parent=item_b)
        step_b2 = store.create_step("s2", step="build", role="agent", parent=item_b)
        lanes = {
            "inbox": [],
            "active": [store.get_node(step_a), store.get_node(step_b1), store.get_node(step_b2)],
            "queue": [],
        }

        selection = select_priority_rows(store, lanes, _FixedFlowService())

        self.assertEqual(
            sorted(s.owning_node.id for s in selection.active), sorted([item_a, item_b])
        )
        self.assertEqual(len(selection.active), 2)
