from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lightcycle.domain.money import Cost
from lightcycle.domain.pool.attribution import AttributionEvent, ToolUsage


@dataclass(frozen=True)
class ModelRates:
    input: float
    output: float
    cache_read: float
    cache_write: float


@dataclass(frozen=True)
class UsageEvent:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: Cost = field(default_factory=Cost)
    cost_basis: Optional[str] = None
    thinking_tokens: Optional[int] = None
    has_result_line: bool = False


@dataclass(frozen=True)
class UsageResume:
    log_file: Optional[str] = None
    offset: int = 0
    message_ids: List[str] = field(default_factory=list)
    pending_tool_use: Dict[str, str] = field(default_factory=dict)
    posted_turn_count: int = 0
    posted_tool_usage: Dict[str, dict] = field(default_factory=dict)
    posted_input_tokens: int = 0
    posted_output_tokens: int = 0
    posted_cache_read_tokens: int = 0
    posted_cache_creation_tokens: int = 0
    posted_cost_usd: float = 0.0

    def subtract_from(self, usage):
        return UsageEvent(
            input_tokens=usage.input_tokens - self.posted_input_tokens,
            output_tokens=usage.output_tokens - self.posted_output_tokens,
            cache_read_tokens=usage.cache_read_tokens - self.posted_cache_read_tokens,
            cache_creation_tokens=usage.cache_creation_tokens - self.posted_cache_creation_tokens,
            cost_usd=usage.cost_usd - Cost.from_usd(self.posted_cost_usd),
            cost_basis=usage.cost_basis,
            thinking_tokens=usage.thinking_tokens,
            has_result_line=usage.has_result_line,
        )

    def subtract_attribution_from(self, attribution):
        tool_usage = {}
        for tool, usage in attribution.tool_usage.items():
            posted = self.posted_tool_usage.get(tool) or {}
            tool_usage[tool] = ToolUsage(
                calls=usage.calls - (posted.get("calls", 0) or 0),
                bytes=usage.bytes - (posted.get("bytes", 0) or 0),
            )
        return AttributionEvent(
            turn_count=attribution.turn_count - self.posted_turn_count,
            tool_usage=tool_usage,
            recovered_input_tokens=attribution.recovered_input_tokens,
            recovered_output_tokens=attribution.recovered_output_tokens,
            recovered_cache_read_tokens=attribution.recovered_cache_read_tokens,
            recovered_cache_creation_tokens=attribution.recovered_cache_creation_tokens,
        )

    def plus(self, delta, recovered_cost, *, log_file, offset, message_ids, pending_tool_use):
        posted_input_tokens = self.posted_input_tokens
        posted_output_tokens = self.posted_output_tokens
        posted_cache_read_tokens = self.posted_cache_read_tokens
        posted_cache_creation_tokens = self.posted_cache_creation_tokens
        posted_cost = Cost.from_usd(self.posted_cost_usd)
        posted_turn_count = self.posted_turn_count
        posted_tool_usage = dict(self.posted_tool_usage)
        if (delta.recovered_input_tokens or delta.recovered_output_tokens
                or delta.recovered_cache_read_tokens or delta.recovered_cache_creation_tokens):
            posted_input_tokens += delta.recovered_input_tokens
            posted_output_tokens += delta.recovered_output_tokens
            posted_cache_read_tokens += delta.recovered_cache_read_tokens
            posted_cache_creation_tokens += delta.recovered_cache_creation_tokens
            posted_cost = posted_cost + recovered_cost
        if delta.turn_count or delta.tool_usage:
            posted_turn_count += delta.turn_count
            for tool, usage in delta.tool_usage.items():
                existing = posted_tool_usage.get(tool) or {"calls": 0, "bytes": 0}
                posted_tool_usage[tool] = {
                    "calls": existing["calls"] + usage.calls,
                    "bytes": existing["bytes"] + usage.bytes,
                }
        return UsageResume(
            log_file=log_file, offset=offset, message_ids=message_ids,
            pending_tool_use=pending_tool_use, posted_turn_count=posted_turn_count,
            posted_tool_usage=posted_tool_usage, posted_input_tokens=posted_input_tokens,
            posted_output_tokens=posted_output_tokens,
            posted_cache_read_tokens=posted_cache_read_tokens,
            posted_cache_creation_tokens=posted_cache_creation_tokens,
            posted_cost_usd=posted_cost.to_usd(),
        )


def price_tokens(model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, rates):
    model_rates = rates.get(model)
    if model_rates is None:
        return Cost(), None
    cost_dollars = (
        input_tokens / 1_000_000 * model_rates.input
        + output_tokens / 1_000_000 * model_rates.output
        + cache_read_tokens / 1_000_000 * model_rates.cache_read
        + cache_creation_tokens / 1_000_000 * model_rates.cache_write
    )
    return Cost.from_usd(cost_dollars), "derived"


def sum_usage_events(events) -> UsageEvent:
    input_tokens = output_tokens = cache_read_tokens = cache_creation_tokens = 0
    cost_usd = Cost()
    cost_basis = None
    thinking_tokens = None
    for event in events:
        input_tokens += event.input_tokens
        output_tokens += event.output_tokens
        cache_read_tokens += event.cache_read_tokens
        cache_creation_tokens += event.cache_creation_tokens
        cost_usd = cost_usd + event.cost_usd
        if cost_basis is None and event.cost_basis is not None:
            cost_basis = event.cost_basis
        if event.thinking_tokens is not None:
            thinking_tokens = (thinking_tokens or 0) + event.thinking_tokens
    return UsageEvent(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cost_usd=cost_usd,
        cost_basis=cost_basis,
        thinking_tokens=thinking_tokens,
    )


def resolve_usage(usage, attribution, model, rates) -> UsageEvent:
    if usage.has_result_line:
        return usage
    if not (attribution.recovered_input_tokens or attribution.recovered_output_tokens
            or attribution.recovered_cache_read_tokens or attribution.recovered_cache_creation_tokens):
        return usage
    cost_usd, cost_basis = price_tokens(
        model, attribution.recovered_input_tokens, attribution.recovered_output_tokens,
        attribution.recovered_cache_read_tokens, attribution.recovered_cache_creation_tokens, rates,
    )
    return UsageEvent(
        input_tokens=attribution.recovered_input_tokens,
        output_tokens=attribution.recovered_output_tokens,
        cache_read_tokens=attribution.recovered_cache_read_tokens,
        cache_creation_tokens=attribution.recovered_cache_creation_tokens,
        cost_usd=cost_usd, cost_basis=cost_basis, thinking_tokens=None,
    )
