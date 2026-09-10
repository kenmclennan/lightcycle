from dataclasses import dataclass, field
from typing import Optional, Tuple


def _is_human(step) -> bool:
    return step.role is None or step.role == "human"


def cache_hit_rate(cache_read_tokens, cache_creation_tokens, input_tokens) -> Optional[float]:
    denominator = cache_read_tokens + cache_creation_tokens + input_tokens
    return cache_read_tokens / denominator if denominator > 0 else None


@dataclass(frozen=True)
class ToolUsageRow:
    tool: str
    calls: int
    bytes: int


@dataclass(frozen=True)
class StepCost:
    applicable: bool
    has_run: bool
    recorded: bool
    turn_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    thinking_tokens: Optional[int]
    cache_hit_rate: Optional[float]
    cost_usd: float
    cost_basis: Optional[str]
    cost_per_turn: Optional[float]
    tools: Tuple[ToolUsageRow, ...] = ()


def step_cost(step, tool_usage) -> StepCost:
    if _is_human(step):
        return StepCost(
            applicable=False, has_run=False, recorded=False, turn_count=0,
            input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_creation_tokens=0,
            thinking_tokens=None, cache_hit_rate=None, cost_usd=0.0, cost_basis=None,
            cost_per_turn=None, tools=(),
        )
    has_run = step.turn_count > 0
    recorded = step.usage_cost_basis is not None
    cost_per_turn_value = step.usage_cost_usd / step.turn_count if recorded and has_run else None
    tools = tuple(sorted(
        (ToolUsageRow(tool, usage.calls, usage.bytes) for tool, usage in tool_usage.items()),
        key=lambda row: (-row.calls, row.tool),
    ))
    return StepCost(
        applicable=True, has_run=has_run, recorded=recorded, turn_count=step.turn_count,
        input_tokens=step.usage_input_tokens, output_tokens=step.usage_output_tokens,
        cache_read_tokens=step.usage_cache_read_tokens,
        cache_creation_tokens=step.usage_cache_creation_tokens,
        thinking_tokens=step.usage_thinking_tokens,
        cache_hit_rate=cache_hit_rate(
            step.usage_cache_read_tokens, step.usage_cache_creation_tokens, step.usage_input_tokens,
        ),
        cost_usd=step.usage_cost_usd, cost_basis=step.usage_cost_basis, cost_per_turn=cost_per_turn_value,
        tools=tools,
    )


@dataclass(frozen=True)
class StageSubtotal:
    stage: str
    step_count: int
    turn_count: int
    cost_usd: float
    not_recorded_count: int


@dataclass(frozen=True)
class ItemCost:
    turn_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    thinking_tokens: Optional[int]
    cache_hit_rate: Optional[float]
    cost_usd: float
    cost_per_turn: Optional[float]
    recorded_turn_count: int
    list_count: int
    derived_count: int
    not_recorded_count: int
    stages: Tuple[StageSubtotal, ...] = field(default_factory=tuple)


def item_cost(steps) -> ItemCost:
    agent_steps = [s for s in steps if not _is_human(s)]
    turn_count = sum(s.turn_count for s in agent_steps)
    input_tokens = sum(s.usage_input_tokens for s in agent_steps)
    output_tokens = sum(s.usage_output_tokens for s in agent_steps)
    cache_read_tokens = sum(s.usage_cache_read_tokens for s in agent_steps)
    cache_creation_tokens = sum(s.usage_cache_creation_tokens for s in agent_steps)
    thinking_values = [
        s.usage_thinking_tokens for s in agent_steps if s.usage_thinking_tokens is not None
    ]
    cost_usd = sum(s.usage_cost_usd for s in agent_steps)
    recorded_steps = [s for s in agent_steps if s.usage_cost_basis is not None]
    recorded_turn_count = sum(s.turn_count for s in recorded_steps)
    return ItemCost(
        turn_count=turn_count, input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens, cache_creation_tokens=cache_creation_tokens,
        thinking_tokens=sum(thinking_values) if thinking_values else None,
        cache_hit_rate=cache_hit_rate(cache_read_tokens, cache_creation_tokens, input_tokens),
        cost_usd=cost_usd,
        cost_per_turn=cost_usd / recorded_turn_count if recorded_turn_count > 0 else None,
        recorded_turn_count=recorded_turn_count,
        list_count=sum(1 for s in agent_steps if s.usage_cost_basis == "list"),
        derived_count=sum(1 for s in agent_steps if s.usage_cost_basis == "derived"),
        not_recorded_count=sum(1 for s in agent_steps if s.turn_count > 0 and s.usage_cost_basis is None),
        stages=_stage_subtotals(agent_steps),
    )


def _stage_subtotals(agent_steps):
    buckets = {}
    for s in agent_steps:
        bucket = buckets.setdefault(s.stage, {"steps": 0, "turns": 0, "cost": 0.0, "not_recorded": 0})
        bucket["steps"] += 1
        bucket["turns"] += s.turn_count
        bucket["cost"] += s.usage_cost_usd
        if s.turn_count > 0 and s.usage_cost_basis is None:
            bucket["not_recorded"] += 1
    rows = [
        StageSubtotal(
            stage=stage, step_count=bucket["steps"], turn_count=bucket["turns"], cost_usd=bucket["cost"],
            not_recorded_count=bucket["not_recorded"],
        )
        for stage, bucket in buckets.items()
    ]
    return tuple(sorted(rows, key=lambda r: (-r.cost_usd, r.stage)))
