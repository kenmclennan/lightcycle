import json
import unittest

from lightcycle.domain.pool import AttributionEvent, parse_usage_event
from lightcycle.domain.pool.usage import UsageEvent, price_tokens, resolve_usage


def _result_line(model_usage):
    return json.dumps({"type": "result", "modelUsage": model_usage})


_RATES = {
    "sonnet": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.2},
}


class TestParseUsageEvent(unittest.TestCase):
    def test_populated_model_usage_returns_summed_fields(self):
        line = _result_line({
            "claude-sonnet-5": {
                "inputTokens": 68, "outputTokens": 16478,
                "cacheReadInputTokens": 2190437, "cacheCreationInputTokens": 72581,
                "thinkingTokens": 9899, "costUSD": 0.8933274, "costBasis": "list",
            }
        })
        event = parse_usage_event([line])
        self.assertEqual(event.input_tokens, 68)
        self.assertEqual(event.output_tokens, 16478)
        self.assertEqual(event.cache_read_tokens, 2190437)
        self.assertEqual(event.cache_creation_tokens, 72581)
        self.assertEqual(event.cost_usd, 0.8933274)
        self.assertEqual(event.cost_basis, "list")
        self.assertEqual(event.thinking_tokens, 9899)

    def test_empty_model_usage_returns_zeroed_event_not_none(self):
        event = parse_usage_event([_result_line({})])
        self.assertEqual(event.input_tokens, 0)
        self.assertEqual(event.output_tokens, 0)
        self.assertEqual(event.cache_read_tokens, 0)
        self.assertEqual(event.cache_creation_tokens, 0)
        self.assertEqual(event.cost_usd, 0.0)
        self.assertIsNone(event.cost_basis)
        self.assertIsNone(event.thinking_tokens)

    def test_no_result_line_returns_zeroed_event_not_none(self):
        event = parse_usage_event(['{"type":"assistant","message":"hi"}'])
        self.assertEqual(event.input_tokens, 0)
        self.assertEqual(event.cost_usd, 0.0)
        self.assertIsNone(event.cost_basis)
        self.assertIsNone(event.thinking_tokens)

    def test_a_result_line_sets_has_result_line_even_when_model_usage_is_empty(self):
        event = parse_usage_event([_result_line({})])
        self.assertTrue(event.has_result_line)

    def test_no_result_line_leaves_has_result_line_false(self):
        event = parse_usage_event(['{"type":"assistant","message":"hi"}'])
        self.assertFalse(event.has_result_line)

    def test_sums_numeric_fields_across_multiple_model_keys(self):
        line = _result_line({
            "claude-sonnet-5": {"inputTokens": 10, "outputTokens": 20, "costUSD": 0.1},
            "claude-haiku-4-5": {"inputTokens": 5, "outputTokens": 3, "costUSD": 0.02},
        })
        event = parse_usage_event([line])
        self.assertEqual(event.input_tokens, 15)
        self.assertEqual(event.output_tokens, 23)
        self.assertAlmostEqual(event.cost_usd, 0.12)

    def test_missing_cost_basis_and_thinking_tokens_keys_are_none(self):
        line = _result_line({
            "claude-sonnet-5": {"inputTokens": 68, "outputTokens": 16478, "costUSD": 0.89}
        })
        event = parse_usage_event([line])
        self.assertIsNone(event.cost_basis)
        self.assertIsNone(event.thinking_tokens)
        self.assertEqual(event.input_tokens, 68)

    def test_last_of_several_result_lines_wins_not_the_sum(self):
        lines = [
            _result_line({"claude-sonnet-5": {"inputTokens": 10, "costUSD": 0.59}}),
            _result_line({"claude-sonnet-5": {"inputTokens": 40, "costUSD": 0.88}}),
            _result_line({"claude-sonnet-5": {"inputTokens": 68, "costUSD": 1.01}}),
        ]
        event = parse_usage_event(lines)
        self.assertEqual(event.input_tokens, 68)
        self.assertAlmostEqual(event.cost_usd, 1.01)


class TestPriceTokens(unittest.TestCase):
    def test_known_model_returns_computed_cost_and_derived_basis(self):
        cost, basis = price_tokens(
            "sonnet", 1_000_000, 1_000_000, 1_000_000, 1_000_000, _RATES
        )
        self.assertAlmostEqual(cost, 2.0 + 10.0 + 0.2 + 2.5)
        self.assertEqual(basis, "derived")

    def test_unknown_model_returns_zero_cost_and_no_basis(self):
        cost, basis = price_tokens("haiku", 1_000_000, 0, 0, 0, _RATES)
        self.assertEqual(cost, 0.0)
        self.assertIsNone(basis)

    def test_only_cache_read_tokens_prices_at_just_the_cache_read_rate(self):
        cost, basis = price_tokens("sonnet", 0, 0, 1_000_000, 0, _RATES)
        self.assertAlmostEqual(cost, 0.2)
        self.assertEqual(basis, "derived")


def _attribution(**recovered):
    return AttributionEvent(**recovered)


class TestResolveUsage(unittest.TestCase):
    def test_a_result_line_event_is_returned_unchanged_regardless_of_attribution(self):
        usage = UsageEvent(input_tokens=5, has_result_line=True)
        attribution = _attribution(recovered_input_tokens=999)
        result = resolve_usage(usage, attribution, "sonnet", _RATES)
        self.assertIs(result, usage)

    def test_no_result_line_and_nothing_recovered_is_returned_unchanged(self):
        usage = UsageEvent()
        attribution = _attribution()
        result = resolve_usage(usage, attribution, "sonnet", _RATES)
        self.assertIs(result, usage)
        self.assertFalse(result.has_result_line)

    def test_no_result_line_with_recovered_tokens_and_a_priced_model_derives_cost(self):
        usage = UsageEvent()
        attribution = _attribution(
            recovered_input_tokens=1_000_000, recovered_output_tokens=1_000_000,
            recovered_cache_read_tokens=1_000_000, recovered_cache_creation_tokens=1_000_000,
        )
        result = resolve_usage(usage, attribution, "sonnet", _RATES)
        self.assertEqual(result.input_tokens, 1_000_000)
        self.assertEqual(result.output_tokens, 1_000_000)
        self.assertEqual(result.cache_read_tokens, 1_000_000)
        self.assertEqual(result.cache_creation_tokens, 1_000_000)
        self.assertAlmostEqual(result.cost_usd, 2.0 + 10.0 + 0.2 + 2.5)
        self.assertEqual(result.cost_basis, "derived")

    def test_no_result_line_with_recovered_tokens_and_an_unpriced_model_records_tokens_only(self):
        usage = UsageEvent()
        attribution = _attribution(recovered_input_tokens=1_000_000)
        result = resolve_usage(usage, attribution, "haiku", _RATES)
        self.assertEqual(result.input_tokens, 1_000_000)
        self.assertEqual(result.cost_usd, 0.0)
        self.assertIsNone(result.cost_basis)


if __name__ == "__main__":
    unittest.main()
