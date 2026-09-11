import unittest

from lightcycle.domain.money import Cost
from lightcycle.domain.pool import ToolUsage
from lightcycle.domain.work.cost import (
    ToolUsageRow,
    cache_hit_rate,
    item_cost,
    step_cost,
)


class _FakeStep:
    def __init__(self, stage="write-code", role="agent", turn_count=0, usage_cost_usd=Cost(),
                 usage_input_tokens=0, usage_output_tokens=0, usage_cache_read_tokens=0,
                 usage_cache_creation_tokens=0, usage_thinking_tokens=None, usage_cost_basis=None):
        self.stage = stage
        self.role = role
        self.turn_count = turn_count
        self.usage_cost_usd = usage_cost_usd
        self.usage_input_tokens = usage_input_tokens
        self.usage_output_tokens = usage_output_tokens
        self.usage_cache_read_tokens = usage_cache_read_tokens
        self.usage_cache_creation_tokens = usage_cache_creation_tokens
        self.usage_thinking_tokens = usage_thinking_tokens
        self.usage_cost_basis = usage_cost_basis


class TestCacheHitRate(unittest.TestCase):
    def test_none_when_denominator_is_zero(self):
        self.assertIsNone(cache_hit_rate(0, 0, 0))

    def test_reference_case_from_lc_468_4(self):
        rate = cache_hit_rate(cache_read_tokens=21_685_338, cache_creation_tokens=204_321, input_tokens=555)
        self.assertAlmostEqual(rate, 21_685_338 / 21_890_214, places=6)


class TestStepCost(unittest.TestCase):
    def test_human_role_short_circuits_regardless_of_turn_or_cost_data(self):
        step = _FakeStep(role="human", turn_count=5, usage_cost_usd=Cost.from_usd(5.0), usage_cost_basis="list")
        cost = step_cost(step, {})
        self.assertFalse(cost.applicable)
        self.assertFalse(cost.has_run)
        self.assertFalse(cost.recorded)
        self.assertEqual(cost.turn_count, 0)

    def test_role_none_is_treated_as_human_not_as_agent_not_yet_run(self):
        step = _FakeStep(role=None, turn_count=0)
        cost = step_cost(step, {})
        self.assertFalse(cost.applicable)

    def test_agent_not_yet_run_has_no_figures(self):
        step = _FakeStep(role="agent", turn_count=0)
        cost = step_cost(step, {})
        self.assertTrue(cost.applicable)
        self.assertFalse(cost.has_run)
        self.assertFalse(cost.recorded)

    def test_agent_ran_not_recorded_has_tokens_and_cache_hit_rate_but_no_cost_per_turn(self):
        step = _FakeStep(
            role="agent", turn_count=246, usage_input_tokens=100, usage_cache_read_tokens=50,
            usage_cost_basis=None,
        )
        cost = step_cost(step, {})
        self.assertTrue(cost.has_run)
        self.assertFalse(cost.recorded)
        self.assertEqual(cost.input_tokens, 100)
        self.assertIsNotNone(cost.cache_hit_rate)
        self.assertIsNone(cost.cost_per_turn)

    def test_agent_ran_recorded_has_every_figure(self):
        step = _FakeStep(role="agent", turn_count=10, usage_cost_usd=Cost.from_usd(1.5), usage_cost_basis="list")
        cost = step_cost(step, {})
        self.assertTrue(cost.has_run)
        self.assertTrue(cost.recorded)
        self.assertEqual(cost.cost_per_turn, Cost.from_usd(0.15))

    def test_tools_ordered_by_calls_descending_tool_name_ascending_on_tie(self):
        step = _FakeStep(role="agent", turn_count=10, usage_cost_usd=Cost.from_usd(1.0), usage_cost_basis="list")
        tool_usage = {
            "Bash": ToolUsage(calls=5, bytes=100),
            "Read": ToolUsage(calls=5, bytes=200),
            "Write": ToolUsage(calls=9, bytes=50),
        }
        cost = step_cost(step, tool_usage)
        self.assertEqual(
            cost.tools,
            (
                ToolUsageRow("Write", 9, 50),
                ToolUsageRow("Bash", 5, 100),
                ToolUsageRow("Read", 5, 200),
            ),
        )


class TestItemCost(unittest.TestCase):
    def test_human_step_contributes_nothing(self):
        steps = [_FakeStep(role="human", turn_count=1, usage_cost_usd=Cost.from_usd(5.0), usage_cost_basis="list")]
        result = item_cost(steps)
        self.assertEqual(result.turn_count, 0)
        self.assertEqual(result.stages, ())

    def test_basis_counts_distinguish_list_derived_and_not_recorded(self):
        steps = [
            _FakeStep(role="agent", turn_count=1, usage_cost_usd=Cost.from_usd(1.0), usage_cost_basis="list"),
            _FakeStep(role="agent", turn_count=2, usage_cost_usd=Cost.from_usd(2.0), usage_cost_basis="derived"),
            _FakeStep(role="agent", turn_count=3, usage_cost_usd=Cost.from_usd(0.0), usage_cost_basis=None),
        ]
        result = item_cost(steps)
        self.assertEqual(result.list_count, 1)
        self.assertEqual(result.derived_count, 1)
        self.assertEqual(result.not_recorded_count, 1)

    def test_cost_per_turn_divides_by_recorded_turn_count_not_full_total(self):
        steps = [
            _FakeStep(role="human", turn_count=100, usage_cost_usd=Cost.from_usd(0.0)),
            _FakeStep(role="agent", turn_count=10, usage_cost_usd=Cost.from_usd(3.0), usage_cost_basis="list"),
            _FakeStep(role="agent", turn_count=246, usage_cost_usd=Cost.from_usd(0.0), usage_cost_basis=None),
        ]
        result = item_cost(steps)
        self.assertEqual(result.recorded_turn_count, 10)
        self.assertEqual(result.cost_per_turn, Cost.from_usd(0.3))

    def test_per_stage_subtotal_ordered_by_spend_descending(self):
        steps = [
            _FakeStep(stage="cleanup", role="agent", turn_count=2, usage_cost_usd=Cost.from_usd(0.17), usage_cost_basis="list"),
            _FakeStep(
                stage="spec-writer", role="agent", turn_count=10, usage_cost_usd=Cost.from_usd(2.91), usage_cost_basis="list",
            ),
        ]
        result = item_cost(steps)
        self.assertEqual([st.stage for st in result.stages], ["spec-writer", "cleanup"])

    def test_stage_tie_on_spend_breaks_by_stage_name_ascending(self):
        steps = [
            _FakeStep(stage="write-code", role="agent", turn_count=1, usage_cost_usd=Cost.from_usd(1.0), usage_cost_basis="list"),
            _FakeStep(stage="cleanup", role="agent", turn_count=1, usage_cost_usd=Cost.from_usd(1.0), usage_cost_basis="list"),
        ]
        result = item_cost(steps)
        self.assertEqual([st.stage for st in result.stages], ["cleanup", "write-code"])

    def test_stage_whose_steps_have_not_run_yet_still_appears(self):
        steps = [_FakeStep(stage="build", role="agent", turn_count=0, usage_cost_usd=Cost.from_usd(0.0))]
        result = item_cost(steps)
        self.assertEqual(len(result.stages), 1)
        self.assertEqual(result.stages[0].step_count, 1)
        self.assertEqual(result.stages[0].turn_count, 0)
        self.assertEqual(result.stages[0].cost_usd, Cost())

    def test_stage_not_recorded_count_only_counts_steps_that_have_run(self):
        steps = [
            _FakeStep(stage="review-code", role="agent", turn_count=0, usage_cost_usd=Cost.from_usd(0.0)),
            _FakeStep(stage="review-code", role="agent", turn_count=60, usage_cost_usd=Cost.from_usd(0.0), usage_cost_basis=None),
        ]
        result = item_cost(steps)
        self.assertEqual(result.stages[0].not_recorded_count, 1)


if __name__ == "__main__":
    unittest.main()
