from lightcycle.domain.pool import WorkerPool, price_tokens
from lightcycle.ports.store import NodeNotFoundError
from lightcycle.ports.workers import RegistryUnreadable

MAX_ACCRUAL_READ_BYTES = 5_000_000


class LiveUsageAccrualUseCase:
    def __init__(self, store, fs, workers, config, stream):
        self._store = store
        self._fs = fs
        self._workers = workers
        self._config = config
        self._stream = stream

    def execute(self, now):
        rates = self._config.usage_pricing()
        try:
            pool = WorkerPool(self._workers.workers_state())
        except RegistryUnreadable:
            return
        for w in pool.alive(self._workers.pid_alive):
            if not w.step or not w.spawnid:
                continue
            self._accrue(w, rates)

    def _accrue(self, w, rates):
        resume = self._store.usage_accrual_state(w.spawnid) or {}
        offset = resume.get("offset", 0)
        data, _ = self._fs.read_from_bounded(w.log, offset, MAX_ACCRUAL_READ_BYTES)
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
        delta, message_ids, pending_tool_use = self._stream.parse_attribution_chunk(
            lines, seen_message_ids, pending_tool_use
        )

        posted_input = resume.get("posted_input_tokens", 0)
        posted_output = resume.get("posted_output_tokens", 0)
        posted_cache_read = resume.get("posted_cache_read_tokens", 0)
        posted_cache_creation = resume.get("posted_cache_creation_tokens", 0)
        posted_cost = resume.get("posted_cost_usd", 0.0)
        posted_turn_count = resume.get("posted_turn_count", 0)
        posted_tool_usage = dict(resume.get("posted_tool_usage") or {})

        cost_usd = 0.0
        cost_basis = None
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
            posted_input += delta.recovered_input_tokens
            posted_output += delta.recovered_output_tokens
            posted_cache_read += delta.recovered_cache_read_tokens
            posted_cache_creation += delta.recovered_cache_creation_tokens
            posted_cost += cost_usd

        if delta.turn_count or delta.tool_usage:
            posted_turn_count += delta.turn_count
            for tool, usage in delta.tool_usage.items():
                existing = posted_tool_usage.get(tool) or {"calls": 0, "bytes": 0}
                posted_tool_usage[tool] = {
                    "calls": existing["calls"] + usage.calls,
                    "bytes": existing["bytes"] + usage.bytes,
                }

        self._store.record_live_usage(
            spawnid=w.spawnid,
            log_file=w.log,
            offset=new_offset,
            message_ids=sorted(message_ids),
            pending_tool_use=pending_tool_use,
            posted_turn_count=posted_turn_count,
            posted_tool_usage=posted_tool_usage,
            posted_input_tokens=posted_input,
            posted_output_tokens=posted_output,
            posted_cache_read_tokens=posted_cache_read,
            posted_cache_creation_tokens=posted_cache_creation,
            posted_cost_usd=posted_cost,
            tid=w.step,
            input_tokens=delta.recovered_input_tokens,
            output_tokens=delta.recovered_output_tokens,
            cache_read_tokens=delta.recovered_cache_read_tokens,
            cache_creation_tokens=delta.recovered_cache_creation_tokens,
            cost_usd=cost_usd,
            cost_basis=cost_basis,
            thinking_tokens=None,
            turn_count=delta.turn_count,
            tool_usage=delta.tool_usage,
        )
