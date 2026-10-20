import unittest

from lightcycle.adapters.tui.hub import COST_FIELD_LABELS, item_cost_fields, step_cost_fields
from lightcycle.domain.work.cost import item_cost, step_cost
from tests.unit.test_cost import _FakeStep


def _keys(fields):
    return [k for k, _v in fields]


class TestCostTabApiCalls(unittest.TestCase):
    def test_the_label_is_api_calls(self):
        self.assertEqual(COST_FIELD_LABELS["api_calls"], "API CALLS")

    def test_a_step_view_shows_the_count_right_after_turns(self):
        cost = step_cost(_FakeStep(role="agent", turn_count=3, usage_api_calls=12), {})

        fields = step_cost_fields(cost)

        keys = _keys(fields)
        self.assertEqual(keys[keys.index("turns") + 1], "api_calls")
        self.assertEqual(dict(fields)["api_calls"], "12")

    def test_a_step_view_omits_the_row_when_never_metered(self):
        cost = step_cost(_FakeStep(role="agent", turn_count=3), {})

        self.assertNotIn("api_calls", _keys(step_cost_fields(cost)))

    def test_an_item_view_shows_the_sum_over_agent_steps(self):
        cost = item_cost([
            _FakeStep(role="agent", turn_count=1, usage_api_calls=5),
            _FakeStep(role="agent", turn_count=1, usage_api_calls=9),
        ])

        fields = item_cost_fields(cost)

        keys = _keys(fields)
        self.assertEqual(keys[keys.index("turns") + 1], "api_calls")
        self.assertEqual(dict(fields)["api_calls"], "14")

    def test_an_item_view_omits_the_row_when_no_step_has_a_count(self):
        cost = item_cost([_FakeStep(role="agent", turn_count=1)])

        self.assertNotIn("api_calls", _keys(item_cost_fields(cost)))


if __name__ == "__main__":
    unittest.main()
