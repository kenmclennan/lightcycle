from dataclasses import dataclass

from lightcycle.domain.pool import (
    extract_claimed_step, parse_attribution_event, parse_usage_event, resolve_usage,
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

    def execute(self) -> BackfillUsageResponse:
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

        return BackfillUsageResponse(
            total=total, matched=matched, unmatched=unmatched, skipped_pending=skipped_pending,
            orphaned=orphaned, stored=stored, reclassified=reclassified, recovered=recovered,
        )
