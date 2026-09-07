from dataclasses import dataclass

from lightcycle.domain.pool import (
    extract_claimed_step, parse_attribution_event, parse_usage_event, resolve_usage,
    sum_attribution_events, sum_usage_events,
)
from lightcycle.ports.store import NodeNotFoundError


@dataclass(frozen=True)
class BackfillUsageResponse:
    total: int
    matched: int
    unmatched: int
    skipped_pending: int
    orphaned: int
    stored: int
    reclassified: int
    recovered: int
    repair_examined: int = 0
    repair_corrected: int = 0
    repair_missing_logs: int = 0


class BackfillUsageUseCase:
    def __init__(self, store, fs, workers, config):
        self._store = store
        self._fs = fs
        self._workers = workers
        self._config = config

    def _model_for(self, step_id):
        try:
            return self._store.get_node(step_id).model
        except NodeNotFoundError:
            return None

    def _repair(self, rates):
        examined = corrected = missing_logs = 0
        for step in self._store.all_steps_including_done():
            log_files = self._store.logs_for_step(step.id)
            if not log_files:
                continue
            examined += 1
            usage_events = []
            attribution_events = []
            for log_file in log_files:
                if not self._fs.exists(log_file):
                    missing_logs += 1
                    continue
                usage = parse_usage_event(self._fs.iter_lines(log_file))
                attribution = parse_attribution_event(self._fs.iter_lines(log_file))
                if not usage.has_result_line:
                    usage = resolve_usage(usage, attribution, step.model, rates)
                usage_events.append(usage)
                attribution_events.append(attribution)
            usage_totals = sum_usage_events(usage_events)
            turn_count, tool_usage_totals = sum_attribution_events(attribution_events)
            current_tool_usage = self._store.tool_usage_for(step.id)
            if (
                usage_totals.input_tokens != step.usage_input_tokens
                or usage_totals.output_tokens != step.usage_output_tokens
                or usage_totals.cache_read_tokens != step.usage_cache_read_tokens
                or usage_totals.cache_creation_tokens != step.usage_cache_creation_tokens
                or usage_totals.cost_usd != step.usage_cost_usd
                or usage_totals.cost_basis != step.usage_cost_basis
                or usage_totals.thinking_tokens != step.usage_thinking_tokens
                or turn_count != step.turn_count
                or tool_usage_totals != current_tool_usage
            ):
                self._store.overwrite_usage_and_attribution(
                    step.id, usage_totals, turn_count, tool_usage_totals
                )
                corrected += 1
        return examined, corrected, missing_logs

    def execute(self, repair=False) -> BackfillUsageResponse:
        root = self._config.data_root()
        files = self._fs.list_worker_log_files(root)
        already_ingested = self._store.usage_backfilled_logs()
        pending_logs = {
            w.get("log") for w in self._workers.workers_state() if not w.get("checked")
        }
        rates = self._config.usage_pricing()

        reclassified = recovered = 0
        for log_file, step_id in self._store.unclassified_backfill_logs():
            reclassified += 1
            usage = parse_usage_event(self._fs.iter_lines(log_file))
            attribution = parse_attribution_event(self._fs.iter_lines(log_file))
            if step_id is not None and not usage.has_result_line:
                model = self._model_for(step_id)
                usage = resolve_usage(usage, attribution, model, rates)
            if self._store.reclassify_backfilled_log(log_file, step_id, usage, attribution):
                recovered += 1

        total = matched = unmatched = skipped_pending = orphaned = stored = 0
        for log_file in files:
            if log_file in already_ingested:
                continue
            total += 1
            if log_file in pending_logs:
                skipped_pending += 1
                continue
            step_id = extract_claimed_step(self._fs.iter_lines(log_file))
            if step_id is not None:
                matched += 1
            else:
                unmatched += 1
            usage = parse_usage_event(self._fs.iter_lines(log_file))
            attribution = parse_attribution_event(self._fs.iter_lines(log_file))
            if step_id is not None and not usage.has_result_line:
                model = self._model_for(step_id)
                usage = resolve_usage(usage, attribution, model, rates)
            was_stored = self._store.record_backfilled_usage(log_file, step_id, usage, attribution)
            if step_id is not None:
                if was_stored:
                    stored += 1
                else:
                    orphaned += 1

        repair_examined = repair_corrected = repair_missing_logs = 0
        if repair:
            repair_examined, repair_corrected, repair_missing_logs = self._repair(rates)

        return BackfillUsageResponse(
            total=total, matched=matched, unmatched=unmatched, skipped_pending=skipped_pending,
            orphaned=orphaned, stored=stored, reclassified=reclassified, recovered=recovered,
            repair_examined=repair_examined, repair_corrected=repair_corrected,
            repair_missing_logs=repair_missing_logs,
        )
