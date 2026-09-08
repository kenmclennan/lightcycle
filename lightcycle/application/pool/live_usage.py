from lightcycle.domain.pool import WorkerPool, parse_attribution_chunk, price_tokens
from lightcycle.ports.store import NodeNotFoundError


class LiveUsageAccrualUseCase:
    def __init__(self, store, fs, workers, config):
        self._store = store
        self._fs = fs
        self._workers = workers
        self._config = config

    def execute(self, now):
        rates = self._config.usage_pricing()
        pool = WorkerPool.from_state(self._workers.workers_state())
        for w in pool.alive(self._workers.pid_alive):
            if not w.step or not w.spawnid:
                continue
            self._accrue(w, rates)

    def _accrue(self, w, rates):
        resume = self._workers.usage_resume(w.spawnid) or {}
        offset = resume.get("offset", 0)
        data, _ = self._fs.read_from(w.log, offset)
        if not data:
            return
        last_newline = data.rfind(b"\n")
        if last_newline == -1:
            return
        complete = data[: last_newline + 1]
        new_offset = offset + len(complete)
        lines = complete.decode("utf-8", errors="replace").splitlines(keepends=True)
        seen_message_ids = set(resume.get("message_ids") or [])
        pending_tool_use = dict(resume.get("pending_tool_use") or {})
        delta, message_ids, pending_tool_use = parse_attribution_chunk(
            lines, seen_message_ids, pending_tool_use
        )

        posted_input = resume.get("posted_input_tokens", 0)
        posted_output = resume.get("posted_output_tokens", 0)
        posted_cache_read = resume.get("posted_cache_read_tokens", 0)
        posted_cache_creation = resume.get("posted_cache_creation_tokens", 0)
        posted_cost = resume.get("posted_cost_usd", 0.0)
        posted_turn_count = resume.get("posted_turn_count", 0)
        posted_tool_usage = dict(resume.get("posted_tool_usage") or {})

        if (
            delta.recovered_input_tokens or delta.recovered_output_tokens
            or delta.recovered_cache_read_tokens or delta.recovered_cache_creation_tokens
        ):
            try:
                model = self._store.get_node(w.step).model
            except NodeNotFoundError:
                model = None
            cost_usd, cost_basis = price_tokens(
                model, delta.recovered_input_tokens, delta.recovered_output_tokens,
                delta.recovered_cache_read_tokens, delta.recovered_cache_creation_tokens, rates,
            )
            self._store.record_usage(
                w.step, delta.recovered_input_tokens, delta.recovered_output_tokens,
                delta.recovered_cache_read_tokens, delta.recovered_cache_creation_tokens,
                cost_usd, cost_basis, None,
            )
            posted_input += delta.recovered_input_tokens
            posted_output += delta.recovered_output_tokens
            posted_cache_read += delta.recovered_cache_read_tokens
            posted_cache_creation += delta.recovered_cache_creation_tokens
            posted_cost += cost_usd

        if delta.turn_count or delta.tool_usage:
            self._store.record_attribution(w.step, delta.turn_count, delta.tool_usage)
            posted_turn_count += delta.turn_count
            for tool, usage in delta.tool_usage.items():
                existing = posted_tool_usage.get(tool) or {"calls": 0, "bytes": 0}
                posted_tool_usage[tool] = {
                    "calls": existing["calls"] + usage.calls,
                    "bytes": existing["bytes"] + usage.bytes,
                }

        self._workers.set_usage_resume(w.spawnid, {
            "offset": new_offset,
            "message_ids": sorted(message_ids),
            "pending_tool_use": pending_tool_use,
            "posted_turn_count": posted_turn_count,
            "posted_tool_usage": posted_tool_usage,
            "posted_input_tokens": posted_input,
            "posted_output_tokens": posted_output,
            "posted_cache_read_tokens": posted_cache_read,
            "posted_cache_creation_tokens": posted_cache_creation,
            "posted_cost_usd": posted_cost,
            "posted_thinking_tokens": None,
        })
