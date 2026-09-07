import json
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UsageEvent:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    cost_basis: Optional[str] = None
    thinking_tokens: Optional[int] = None
    has_result_line: bool = False


def parse_usage_event(lines) -> UsageEvent:
    found = UsageEvent()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("type") != "result":
            continue
        found = _from_model_usage(data.get("modelUsage") or {})
    return found


def _from_model_usage(model_usage) -> UsageEvent:
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0
    cost_usd = 0.0
    cost_basis = None
    thinking_tokens = None
    for entry in model_usage.values():
        input_tokens += entry.get("inputTokens") or 0
        output_tokens += entry.get("outputTokens") or 0
        cache_read_tokens += entry.get("cacheReadInputTokens") or 0
        cache_creation_tokens += entry.get("cacheCreationInputTokens") or 0
        cost_usd += entry.get("costUSD") or 0.0
        if cost_basis is None and "costBasis" in entry:
            cost_basis = entry["costBasis"]
        if "thinkingTokens" in entry:
            thinking_tokens = (thinking_tokens or 0) + entry["thinkingTokens"]
    return UsageEvent(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cost_usd=cost_usd,
        cost_basis=cost_basis,
        thinking_tokens=thinking_tokens,
        has_result_line=True,
    )


def price_tokens(model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, rates):
    model_rates = rates.get(model)
    if model_rates is None:
        return 0.0, None
    cost = (
        input_tokens / 1_000_000 * model_rates["input"]
        + output_tokens / 1_000_000 * model_rates["output"]
        + cache_read_tokens / 1_000_000 * model_rates["cache_read"]
        + cache_creation_tokens / 1_000_000 * model_rates["cache_write"]
    )
    return cost, "derived"


def sum_usage_events(events) -> UsageEvent:
    input_tokens = output_tokens = cache_read_tokens = cache_creation_tokens = 0
    cost_usd = 0.0
    cost_basis = None
    thinking_tokens = None
    for event in events:
        input_tokens += event.input_tokens
        output_tokens += event.output_tokens
        cache_read_tokens += event.cache_read_tokens
        cache_creation_tokens += event.cache_creation_tokens
        cost_usd += event.cost_usd
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
