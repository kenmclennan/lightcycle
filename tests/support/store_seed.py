import json

from lightcycle.domain.feedback import HeldComment
from lightcycle.domain.money import Cost
from lightcycle.domain.pool import ModelRates, ToolUsage, UsageEvent


def seed_usage(store, tid, input_tokens, output_tokens, cache_read_tokens,
               cache_creation_tokens, cost_usd, cost_basis, thinking_tokens,
               rates_used=None):
    step = store.get_node(tid)
    prior_rates = (
        ModelRates(**json.loads(step.usage_rates_used))
        if step.usage_rates_used is not None else None
    )
    if thinking_tokens is None:
        thinking = step.usage_thinking_tokens
    else:
        thinking = (step.usage_thinking_tokens or 0) + thinking_tokens
    totals = UsageEvent(
        input_tokens=step.usage_input_tokens + input_tokens,
        output_tokens=step.usage_output_tokens + output_tokens,
        cache_read_tokens=step.usage_cache_read_tokens + cache_read_tokens,
        cache_creation_tokens=step.usage_cache_creation_tokens + cache_creation_tokens,
        cost_usd=Cost.from_usd(step.usage_cost_usd.to_usd() + cost_usd),
        cost_basis=cost_basis if cost_basis is not None else step.usage_cost_basis,
        rates_used=rates_used if rates_used is not None else prior_rates,
        thinking_tokens=thinking,
    )
    store.overwrite_usage_and_attribution(
        tid, totals, step.turn_count, store.tool_usage_for(tid)
    )


def seed_attribution(store, tid, turn_count, tool_usage):
    step = store.get_node(tid)
    totals = store.tool_usage_for(tid)
    for tool, usage in tool_usage.items():
        existing = totals.get(tool, ToolUsage())
        totals[tool] = ToolUsage(
            calls=existing.calls + usage.calls, bytes=existing.bytes + usage.bytes
        )
    prior = UsageEvent(
        input_tokens=step.usage_input_tokens,
        output_tokens=step.usage_output_tokens,
        cache_read_tokens=step.usage_cache_read_tokens,
        cache_creation_tokens=step.usage_cache_creation_tokens,
        cost_usd=step.usage_cost_usd,
        cost_basis=step.usage_cost_basis,
        rates_used=(
            ModelRates(**json.loads(step.usage_rates_used))
            if step.usage_rates_used is not None else None
        ),
        thinking_tokens=step.usage_thinking_tokens,
    )
    store.overwrite_usage_and_attribution(tid, prior, step.turn_count + turn_count, totals)


def _is_sqlite(store):
    return hasattr(store, "_conn")


def held_comment(store, run_id, key):
    if not _is_sqlite(store):
        return store._holds.get((run_id, key))
    row = store._conn.execute(
        "SELECT %s FROM held_comments WHERE run_id = ? AND key = ?" % store._HOLD_COLUMNS,
        (run_id, key),
    ).fetchone()
    return HeldComment(*row) if row else None


def held_comment_for_step(store, step_id):
    if not _is_sqlite(store):
        return next((h for h in store._holds.values() if h.step_id == step_id), None)
    row = store._conn.execute(
        "SELECT %s FROM held_comments WHERE step_id = ?" % store._HOLD_COLUMNS, (step_id,)
    ).fetchone()
    return HeldComment(*row) if row else None


def seed_day_summary_claim(store, day, step_id, spawn_count):
    if not _is_sqlite(store):
        bucket = store._daily_summaries[day]
        bucket["step_id"] = step_id
        bucket["spawn_count"] = spawn_count
        return
    store._conn.execute(
        "UPDATE daily_summaries SET step_id = ?, spawn_count = ? WHERE day = ?",
        (step_id, spawn_count, day.isoformat()),
    )
    store._conn.commit()
