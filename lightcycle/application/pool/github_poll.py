from lightcycle.application.pool.pr_poll import PrPoll


class GithubPollUseCase:
    def __init__(self, snapshot, github, runner, config, writes):
        self._snapshot = snapshot
        self._runner = runner
        self._config = config
        self._poll = PrPoll(github, snapshot, writes)
        self._last_started = None
        config.github_poll_seconds()

    def settle(self):
        self._runner.join()

    def execute(self, now):
        interval = self._config.github_poll_seconds()
        if self._runner.running():
            return False
        if self._last_started is not None and now - self._last_started < interval:
            return False
        wanted = self._snapshot.take_wanted()
        if not wanted.prs:
            return False
        if not self._runner.start(lambda: self._poll.run(wanted)):
            return False
        self._last_started = now
        return True
