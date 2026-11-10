from tests.support.store_seed import seed_attribution, seed_usage
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
        step = store.create_step(stage="write-code", role="agent", item=item)
        seed_usage(store, step, 100, 50, 10, 5, 1.5, "list", None)
        seed_attribution(store, step, 4, {"Read": ToolUsage(calls=2, bytes=40)})

        cost = CostUseCase(store).execute(CostInput(node=step))

        self.assertTrue(cost.applicable)
        self.assertEqual(cost.turn_count, 4)
        self.assertEqual(cost.cost_usd, Cost.from_usd(1.5))
        self.assertEqual(cost.tools, (ToolUsageRow("Read", 2, 40),))

    def test_item_node_rolls_up_every_step_across_passes(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        step_a = store.create_step(stage="write-code", role="agent", item=item)
        step_b = store.create_step(stage="write-code", role="agent", item=item)
        seed_usage(store, step_a, 100, 50, 0, 0, 1.0, "list", None)
        seed_attribution(store, step_a, 5, {})
        seed_usage(store, step_b, 100, 50, 0, 0, 2.0, "list", None)
        seed_attribution(store, step_b, 3, {})

        cost = CostUseCase(store).execute(CostInput(node=item))

        self.assertEqual(cost.turn_count, 8)
        self.assertEqual(cost.cost_usd, Cost.from_usd(3.0))

    def test_item_node_excludes_human_steps_from_the_rollup(self):
        store = FakeStore()
        item = store.create_item("item", "a description")
        store.create_step(stage="await-merge", role="human", item=item)

        cost = CostUseCase(store).execute(CostInput(node=item))

        self.assertEqual(cost.turn_count, 0)
        self.assertEqual(cost.stages, ())

    def test_item_node_carries_prs_for_a_merged_three_layer_stack_without_changing_cost(self):
        import json

        store = FakeStore()
        item = store.create_item("item", "a description")
        step = store.create_step(stage="write-code", role="agent", item=item)
        seed_usage(store, step, 100, 50, 0, 0, 2.0, "list", None)
        seed_attribution(store, step, 5, {})
        pid = store.open_pass(item)
        rid = store.open_run(item, pid, "code")
        store.set_pr(rid, "https://github.com/a/b/pull/3")
        store.set_stack_seen(rid, json.dumps([
            {"number": n, "state": "merged", "head_ref": "l%d" % n, "base": None}
            for n in (1, 2, 3)
        ]))
        store.close_run(rid, "merged")

        cost = CostUseCase(store).execute(CostInput(node=item))

        self.assertEqual((cost.prs, cost.prs_merged), (3, 3))
        self.assertEqual(cost.cost_usd, Cost.from_usd(2.0))


if __name__ == "__main__":
    unittest.main()
