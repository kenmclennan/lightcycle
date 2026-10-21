from lightcycle.application.pool.pr_poll import PrPoll
import time

from lightcycle.domain.pool import GithubBudget
from lightcycle.ports.github import RateLimit
from lightcycle.ports.store import StoreError

PR_FEEDBACK_RETENTION_DAYS = 30


class GithubPollUseCase:
    def __init__(self, snapshot, github, runner, config, writes, github_budget_status, clock,
                 worker_log, store):
        self._store = store
        self._writes = writes
        self._worker_log = worker_log
        self._seeded = set()
        self._pruned = False
        self._snapshot = snapshot
        self._github = github
        self._runner = runner
        self._config = config
        self._poll = PrPoll(github, snapshot, writes, worker_log)
        self._github_budget_status = github_budget_status
        self._clock = clock
        self._last_started = None
        self._last_was_budget_only = False
        config.github_poll_seconds()
        config.github_view_refresh_polls()

    def settle(self):
        self._runner.join()
        self._flush()

    def _log_store_failure(self, action, error):
        self._worker_log.append_run_log("%s  %-7s  %s failed: %s\n" % (
            time.strftime("%H:%M:%S"), "github", action, error))

    def _flush(self):
        updates = self._writes.take_unsaved_updates()
        changes = self._snapshot.take_cutoff_changes()
        if not updates and not changes:
            return
        try:
            with self._store.transaction():
                for pr, head in updates:
                    self._store.record_pool_update(pr, head)
                for pr, (cutoff, head) in changes.items():
                    self._store.save_feedback_cutoff(pr, cutoff, head)
        except StoreError as error:
            self._writes.requeue_unsaved_updates(updates)
            self._snapshot.requeue_cutoff_changes(changes)
            self._log_store_failure("persisting the feedback cutoff", error)

    def _seed(self, prs):
        self._seeded &= set(prs)
        for pr in prs:
            if pr in self._seeded:
                continue
            try:
                stored = self._store.feedback_cutoff(pr)
                heads = self._store.pool_updated_heads(pr)
            except StoreError as error:
                self._log_store_failure("seeding the feedback cutoff", error)
                continue
            if stored is not None:
                self._snapshot.seed_cutoff(pr, stored[0], stored[1])
            self._writes.seed_updated_from(pr, heads)
            self._seeded.add(pr)

    def _prune(self):
        if self._pruned:
            return
        self._pruned = True
        try:
            self._store.prune_pr_feedback_state(PR_FEEDBACK_RETENTION_DAYS)
        except StoreError as error:
            self._log_store_failure("pruning the feedback cutoff", error)

    def _publish_budget(self):
        reading = self._github.rate_limit()
        if not isinstance(reading, RateLimit):
            return
        self._github_budget_status.save(GithubBudget(
            limit=reading.limit, remaining=reading.remaining,
            reset=reading.reset, read_at=self._clock(),
        ))

    def execute(self, now):
        interval = self._config.github_poll_seconds()
        self._flush()
        if self._runner.running():
            return False
        due = self._last_started is None or now - self._last_started >= interval
        if not due and not self._last_was_budget_only:
            return False
        refresh_polls = self._config.github_view_refresh_polls()
        wanted = self._snapshot.take_wanted()
        if not due and not wanted.prs:
            return False

        self._prune()
        self._seed(wanted.prs)

        def cycle():
            self._publish_budget()
            if wanted.prs:
                self._poll.run(wanted, now, refresh_polls)

        if not self._runner.start(cycle):
            return False
        self._last_started = now
        self._last_was_budget_only = not wanted.prs
        return True
