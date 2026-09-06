from dataclasses import dataclass

from lightcycle.domain.pool import extract_claimed_step, parse_attribution_event, parse_usage_event


@dataclass(frozen=True)
class BackfillUsageResponse:
    total: int
    matched: int
    unmatched: int
    skipped_pending: int
    orphaned: int
    stored: int


class BackfillUsageUseCase:
    def __init__(self, store, fs, workers, config):
        self._store = store
        self._fs = fs
        self._workers = workers
        self._config = config

    def execute(self) -> BackfillUsageResponse:
        root = self._config.data_root()
        files = self._fs.list_worker_log_files(root)
        already_ingested = self._store.usage_backfilled_logs()
        pending_logs = {
            w.get("log") for w in self._workers.workers_state() if not w.get("checked")
        }

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
            was_stored = self._store.record_backfilled_usage(log_file, step_id, usage, attribution)
            if step_id is not None:
                if was_stored:
                    stored += 1
                else:
                    orphaned += 1

        return BackfillUsageResponse(
            total=total, matched=matched, unmatched=unmatched, skipped_pending=skipped_pending,
            orphaned=orphaned, stored=stored,
        )
