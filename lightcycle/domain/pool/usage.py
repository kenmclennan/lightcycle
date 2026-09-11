from dataclasses import dataclass, field
from typing import Optional

from lightcycle.domain.money import Cost


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
