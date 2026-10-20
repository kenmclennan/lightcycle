from lightcycle.application.pool.pr_poll import PrPoll
from lightcycle.ports.github import RateLimit


class GithubPollUseCase:
    def __init__(self, snapshot, github, runner, config, writes, github_budget_status, clock):
        self._snapshot = snapshot
        self._github = github
        self._runner = runner
        self._config = config
        self._poll = PrPoll(github, snapshot, writes)
        self._github_budget_status = github_budget_status
        self._clock = clock
        self._last_started = None
        self._last_was_budget_only = False
        config.github_poll_seconds()

    def settle(self):
        self._runner.join()

    def _publish_budget(self):
        reading = self._github.rate_limit()
        if not isinstance(reading, RateLimit):
            return
        self._github_budget_status.save({
            "limit": reading.limit, "remaining": reading.remaining,
            "reset": reading.reset, "read_at": self._clock(),
        })

    def execute(self, now):
        interval = self._config.github_poll_seconds()
        if self._runner.running():
            return False
        due = self._last_started is None or now - self._last_started >= interval
        if not due and not self._last_was_budget_only:
            return False
        wanted = self._snapshot.take_wanted()
        if not due and not wanted.prs:
            return False

        def cycle():
            self._publish_budget()
            if wanted.prs:
                self._poll.run(wanted)

        if not self._runner.start(cycle):
            return False
        self._last_started = now
        self._last_was_budget_only = not wanted.prs
        return True
