import unittest

from lightcycle.application.work import CostInput, CostUseCase
from lightcycle.domain.money import Cost
from lightcycle.domain.pool import ToolUsage
from lightcycle.domain.work.cost import ToolUsageRow
from tests.support.fake_store import FakeStore


class TestCostUseCase(unittest.TestCase):
    def test_step_node_returns_its_own_usage_and_tool_table(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        step = store.create_step("s", step="write-code", role="agent", parent=item)
        store.record_usage(step, 100, 50, 10, 5, 1.5, "list", None)
        store.record_attribution(step, 4, {"Read": ToolUsage(calls=2, bytes=40)})

        cost = CostUseCase(store).execute(CostInput(node=step))

        self.assertTrue(cost.applicable)
        self.assertEqual(cost.turn_count, 4)
        self.assertEqual(cost.cost_usd, Cost.from_usd(1.5))
        self.assertEqual(cost.tools, (ToolUsageRow("Read", 2, 40),))

    def test_item_node_rolls_up_every_step_across_passes(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        step_a = store.create_step("a", step="write-code", role="agent", parent=item)
        step_b = store.create_step("b", step="write-code", role="agent", parent=item)
        store.record_usage(step_a, 100, 50, 0, 0, 1.0, "list", None)
        store.record_attribution(step_a, 5, {})
        store.record_usage(step_b, 100, 50, 0, 0, 2.0, "list", None)
        store.record_attribution(step_b, 3, {})

        cost = CostUseCase(store).execute(CostInput(node=item))

        self.assertEqual(cost.turn_count, 8)
        self.assertEqual(cost.cost_usd, Cost.from_usd(3.0))

    def test_item_node_excludes_human_steps_from_the_rollup(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        store.create_step("gate", step="await-merge", role="human", parent=item)

        cost = CostUseCase(store).execute(CostInput(node=item))

        self.assertEqual(cost.turn_count, 0)
        self.assertEqual(cost.stages, ())


if __name__ == "__main__":
    unittest.main()
