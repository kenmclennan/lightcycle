import json
import unittest

from lightcycle.domain.pool import parse_usage_event


def _result_line(model_usage):
    return json.dumps({"type": "result", "modelUsage": model_usage})


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


if __name__ == "__main__":
    unittest.main()
