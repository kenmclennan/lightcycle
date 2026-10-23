import json
import unittest

from lightcycle.adapters.claude_stream import parse_usage_event
from lightcycle.domain.money import Cost
from lightcycle.domain.pool import AttributionEvent, ToolUsage
from lightcycle.domain.pool.usage import (
    ModelRates, UsageEvent, UsageResume, price_tokens, resolve_usage, sum_usage_events,
)


def _result_line(model_usage):
    return json.dumps({"type": "result", "modelUsage": model_usage})


_RATES = {
    "sonnet": ModelRates(input=2.0, output=10.0, cache_write=2.5, cache_read=0.2),
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
        self.assertEqual(event.cost_usd, Cost.from_usd(0.8933274))
        self.assertEqual(event.cost_basis, "list")
        self.assertEqual(event.thinking_tokens, 9899)

    def test_empty_model_usage_returns_zeroed_event_not_none(self):
        event = parse_usage_event([_result_line({})])
        self.assertEqual(event.input_tokens, 0)
        self.assertEqual(event.output_tokens, 0)
        self.assertEqual(event.cache_read_tokens, 0)
        self.assertEqual(event.cache_creation_tokens, 0)
        self.assertEqual(event.cost_usd, Cost())
        self.assertIsNone(event.cost_basis)
        self.assertIsNone(event.thinking_tokens)

    def test_no_result_line_returns_zeroed_event_not_none(self):
        event = parse_usage_event(['{"type":"assistant","message":"hi"}'])
        self.assertEqual(event.input_tokens, 0)
        self.assertEqual(event.cost_usd, Cost())
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
        self.assertEqual(event.cost_usd, Cost.from_usd(0.12))

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
        self.assertEqual(event.cost_usd, Cost.from_usd(1.01))


class TestPriceTokens(unittest.TestCase):
    def test_known_model_returns_computed_cost_and_derived_basis(self):
        cost, basis, rates_used = price_tokens(
            "sonnet", 1_000_000, 1_000_000, 1_000_000, 1_000_000, _RATES
        )
        self.assertEqual(cost, Cost.from_usd(2.0 + 10.0 + 0.2 + 2.5))
        self.assertEqual(basis, "derived")
        self.assertEqual(rates_used, _RATES["sonnet"])

    def test_unknown_model_returns_zero_cost_and_unpriced_basis(self):
        cost, basis, rates_used = price_tokens("haiku", 1_000_000, 0, 0, 0, _RATES)
        self.assertEqual(cost, Cost())
        self.assertEqual(basis, "unpriced")
        self.assertIsNone(rates_used)

    def test_only_cache_read_tokens_prices_at_just_the_cache_read_rate(self):
        cost, basis, rates_used = price_tokens("sonnet", 0, 0, 1_000_000, 0, _RATES)
        self.assertEqual(cost, Cost.from_usd(0.2))
        self.assertEqual(basis, "derived")
        self.assertEqual(rates_used, _RATES["sonnet"])


class TestSumUsageEventsRatesUsed(unittest.TestCase):
    def test_keeps_the_first_non_null_rates_used_across_events(self):
        events = [
            UsageEvent(cost_basis="unpriced", rates_used=None),
            UsageEvent(cost_basis="derived", rates_used=_RATES["sonnet"]),
            UsageEvent(cost_basis="derived", rates_used=ModelRates(1, 1, 1, 1)),
        ]
        summed = sum_usage_events(events)
        self.assertEqual(summed.rates_used, _RATES["sonnet"])


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
        self.assertEqual(result.cost_usd, Cost.from_usd(2.0 + 10.0 + 0.2 + 2.5))
        self.assertEqual(result.cost_basis, "derived")
        self.assertEqual(result.rates_used, _RATES["sonnet"])

    def test_no_result_line_with_recovered_tokens_and_an_unpriced_model_records_tokens_only(self):
        usage = UsageEvent()
        attribution = _attribution(recovered_input_tokens=1_000_000)
        result = resolve_usage(usage, attribution, "haiku", _RATES)
        self.assertEqual(result.input_tokens, 1_000_000)
        self.assertEqual(result.cost_usd, Cost())
        self.assertEqual(result.cost_basis, "unpriced")
        self.assertIsNone(result.rates_used)


class TestUsageResumeSubtractFrom(unittest.TestCase):
    def test_subtracts_posted_fields_from_usage(self):
        resume = UsageResume(
            posted_input_tokens=40, posted_output_tokens=20, posted_cache_read_tokens=4,
            posted_cache_creation_tokens=2, posted_cost=Cost.from_usd(0.4),
        )
        usage = UsageEvent(
            input_tokens=100, output_tokens=50, cache_read_tokens=10,
            cache_creation_tokens=5, cost_usd=Cost.from_usd(1.0), cost_basis="list",
            rates_used=_RATES["sonnet"], thinking_tokens=9, has_result_line=True,
        )
        result = resume.subtract_from(usage)
        self.assertEqual(result.input_tokens, 60)
        self.assertEqual(result.output_tokens, 30)
        self.assertEqual(result.cache_read_tokens, 6)
        self.assertEqual(result.cache_creation_tokens, 3)
        self.assertEqual(result.cost_usd, Cost.from_usd(0.6))
        self.assertEqual(result.cost_basis, "list")
        self.assertEqual(result.rates_used, _RATES["sonnet"])
        self.assertEqual(result.thinking_tokens, 9)
        self.assertTrue(result.has_result_line)


class TestUsageResumeSubtractAttributionFrom(unittest.TestCase):
    def test_subtracts_posted_turn_count_and_tool_usage(self):
        resume = UsageResume(
            posted_turn_count=1, posted_tool_usage={"Read": {"calls": 1, "bytes": 5}},
        )
        attribution = AttributionEvent(
            turn_count=2, tool_usage={"Read": ToolUsage(calls=2, bytes=15)},
            recovered_input_tokens=1, recovered_output_tokens=2,
            recovered_cache_read_tokens=3, recovered_cache_creation_tokens=4,
        )
        result = resume.subtract_attribution_from(attribution)
        self.assertEqual(result.turn_count, 1)
        self.assertEqual(result.tool_usage["Read"].calls, 1)
        self.assertEqual(result.tool_usage["Read"].bytes, 10)
        self.assertEqual(result.recovered_input_tokens, 1)
        self.assertEqual(result.recovered_output_tokens, 2)
        self.assertEqual(result.recovered_cache_read_tokens, 3)
        self.assertEqual(result.recovered_cache_creation_tokens, 4)


class TestAttributionEventIsImmutable(unittest.TestCase):
    def test_tool_usage_is_a_read_only_copy_of_the_given_mapping(self):
        given = {"Read": ToolUsage(calls=1, bytes=5)}
        event = AttributionEvent(tool_usage=given)
        given["Grep"] = ToolUsage(calls=1, bytes=1)
        self.assertEqual(list(event.tool_usage), ["Read"])
        with self.assertRaises(TypeError):
            event.tool_usage["Grep"] = ToolUsage()


class TestUsageResumePlus(unittest.TestCase):
    def test_an_all_zero_delta_leaves_posted_fields_unchanged(self):
        resume = UsageResume(
            posted_input_tokens=40, posted_output_tokens=20, posted_turn_count=1,
            posted_tool_usage={"Read": {"calls": 1, "bytes": 5}},
        )
        result = resume.plus(
            AttributionEvent(), Cost(), log_file="x", offset=0,
            message_ids=[], pending_tool_use={},
        )
        self.assertEqual(result.posted_input_tokens, 40)
        self.assertEqual(result.posted_output_tokens, 20)
        self.assertEqual(result.posted_turn_count, 1)
        self.assertEqual(result.posted_tool_usage, {"Read": {"calls": 1, "bytes": 5}})
        self.assertEqual(result.log_file, "x")
        self.assertEqual(result.offset, 0)

    def test_a_recovered_token_delta_advances_the_usage_fields_and_cost(self):
        resume = UsageResume(posted_input_tokens=40, posted_cost=Cost.from_usd(0.4))
        delta = AttributionEvent(
            recovered_input_tokens=10, recovered_output_tokens=5,
            recovered_cache_read_tokens=1, recovered_cache_creation_tokens=2,
        )
        result = resume.plus(
            delta, Cost.from_usd(0.1), log_file="x", offset=0,
            message_ids=[], pending_tool_use={},
        )
        self.assertEqual(result.posted_input_tokens, 50)
        self.assertEqual(result.posted_output_tokens, 5)
        self.assertEqual(result.posted_cache_read_tokens, 1)
        self.assertEqual(result.posted_cache_creation_tokens, 2)
        self.assertEqual(result.posted_cost, Cost.from_usd(0.5))
        self.assertEqual(result.posted_turn_count, 0)

    def test_subtracting_a_resume_that_equals_the_total_lands_on_zero(self):
        resume = UsageResume(posted_cost=Cost.from_usd(0.4))
        result = resume.subtract_from(UsageEvent(cost_usd=Cost.from_usd(0.4)))
        self.assertEqual(result.cost_usd, Cost())

    def test_a_turn_or_tool_usage_delta_advances_only_those_fields(self):
        resume = UsageResume(posted_turn_count=1, posted_tool_usage={"Read": {"calls": 1, "bytes": 5}})
        delta = AttributionEvent(turn_count=2, tool_usage={"Read": ToolUsage(calls=1, bytes=15)})
        result = resume.plus(
            delta, Cost(), log_file="x", offset=0, message_ids=[], pending_tool_use={},
        )
        self.assertEqual(result.posted_turn_count, 3)
        self.assertEqual(result.posted_tool_usage["Read"], {"calls": 2, "bytes": 20})
        self.assertEqual(result.posted_input_tokens, 0)


class TestUsageMutationGaps(unittest.TestCase):
    _RECOVERED = (
        "recovered_input_tokens", "recovered_output_tokens",
        "recovered_cache_read_tokens", "recovered_cache_creation_tokens")

    def test_cache_read_pricing_divides_by_exactly_one_million(self):
        cost, _, _ = price_tokens("sonnet", 0, 0, 1_000_000_000, 0, _RATES)
        self.assertEqual(cost, Cost.from_usd(200.0))

    def test_sum_adds_every_token_field_across_events(self):
        events = [
            UsageEvent(1, 10, 100, 1000),
            UsageEvent(2, 20, 200, 2000),
        ]
        summed = sum_usage_events(events)
        self.assertEqual(
            (summed.input_tokens, summed.output_tokens,
             summed.cache_read_tokens, summed.cache_creation_tokens),
            (3, 30, 300, 3000))

    def test_sum_keeps_the_first_non_null_cost_basis(self):
        events = [
            UsageEvent(cost_basis=None), UsageEvent(cost_basis="list"),
            UsageEvent(cost_basis="derived"),
        ]
        self.assertEqual(sum_usage_events(events).cost_basis, "list")

    def test_sum_adds_thinking_tokens_and_leaves_none_when_no_event_has_any(self):
        events = [UsageEvent(thinking_tokens=5), UsageEvent(), UsageEvent(thinking_tokens=7)]
        self.assertEqual(sum_usage_events(events).thinking_tokens, 12)
        self.assertIsNone(sum_usage_events([UsageEvent(), UsageEvent()]).thinking_tokens)

    def test_any_single_recovered_field_makes_resolve_usage_derive_from_attribution(self):
        usage = UsageEvent(input_tokens=99)
        for field_name in self._RECOVERED:
            with self.subTest(field_name):
                resolved = resolve_usage(
                    usage, AttributionEvent(**{field_name: 7}), "sonnet", _RATES)
                self.assertIsNot(resolved, usage)
                self.assertEqual(resolved.cost_basis, "derived")

    def test_a_derived_usage_event_has_no_thinking_tokens(self):
        resolved = resolve_usage(
            UsageEvent(thinking_tokens=4), AttributionEvent(recovered_input_tokens=1),
            "sonnet", _RATES)
        self.assertIsNone(resolved.thinking_tokens)

    def test_subtract_attribution_keeps_a_tool_the_resume_has_not_posted_whole(self):
        result = UsageResume().subtract_attribution_from(
            AttributionEvent(tool_usage={"Read": ToolUsage(calls=2, bytes=15)}))
        self.assertEqual(
            (result.tool_usage["Read"].calls, result.tool_usage["Read"].bytes), (2, 15))

    def test_subtract_attribution_treats_zero_or_missing_posted_counts_as_zero(self):
        attribution = AttributionEvent(tool_usage={"Read": ToolUsage(calls=2, bytes=15)})
        for posted in ({"calls": 0, "bytes": 0}, {}):
            with self.subTest(posted):
                result = UsageResume(posted_tool_usage={"Read": posted}).subtract_attribution_from(
                    attribution)
                self.assertEqual(
                    (result.tool_usage["Read"].calls, result.tool_usage["Read"].bytes), (2, 15))

    def test_plus_advances_on_any_single_recovered_field(self):
        for field_name in self._RECOVERED:
            with self.subTest(field_name):
                result = UsageResume().plus(
                    AttributionEvent(**{field_name: 3}), Cost(5), log_file="x", offset=0,
                    message_ids=[], pending_tool_use={})
                self.assertEqual(result.posted_cost, Cost(5))

    def test_plus_adds_each_recovered_field_onto_what_was_already_posted(self):
        resume = UsageResume(
            posted_input_tokens=10, posted_output_tokens=20, posted_cache_read_tokens=30,
            posted_cache_creation_tokens=40)
        result = resume.plus(
            AttributionEvent(
                recovered_input_tokens=1, recovered_output_tokens=2,
                recovered_cache_read_tokens=3, recovered_cache_creation_tokens=4),
            Cost(), log_file="x", offset=0, message_ids=[], pending_tool_use={})
        self.assertEqual(
            (result.posted_input_tokens, result.posted_output_tokens,
             result.posted_cache_read_tokens, result.posted_cache_creation_tokens),
            (11, 22, 33, 44))

    def test_plus_records_a_turn_count_alone_and_a_tool_usage_alone(self):
        turns = UsageResume(posted_turn_count=1).plus(
            AttributionEvent(turn_count=2), Cost(), log_file="x", offset=0,
            message_ids=[], pending_tool_use={})
        tools = UsageResume().plus(
            AttributionEvent(tool_usage={"Read": ToolUsage(calls=0, bytes=0)}), Cost(),
            log_file="x", offset=0, message_ids=[], pending_tool_use={})
        self.assertEqual(turns.posted_turn_count, 3)
        self.assertEqual(tools.posted_tool_usage, {"Read": {"calls": 0, "bytes": 0}})

    def test_plus_starts_a_new_tool_from_zero_and_accumulates_a_known_one(self):
        resume = UsageResume(posted_tool_usage={"Read": {"calls": 1, "bytes": 5}})
        result = resume.plus(
            AttributionEvent(tool_usage={
                "Read": ToolUsage(calls=2, bytes=7), "Grep": ToolUsage(calls=3, bytes=4)}),
            Cost(), log_file="x", offset=0, message_ids=[], pending_tool_use={})
        self.assertEqual(
            result.posted_tool_usage,
            {"Read": {"calls": 3, "bytes": 12}, "Grep": {"calls": 3, "bytes": 4}})

    def test_plus_carries_the_pending_tool_use_it_was_given(self):
        result = UsageResume().plus(
            AttributionEvent(), Cost(), log_file="x", offset=0, message_ids=["m"],
            pending_tool_use={"t1": "Read"})
        self.assertEqual((result.pending_tool_use, result.message_ids), ({"t1": "Read"}, ["m"]))


if __name__ == "__main__":
    unittest.main()
