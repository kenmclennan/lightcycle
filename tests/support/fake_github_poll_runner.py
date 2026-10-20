from lightcycle.ports.github_poll_runner import GithubPollRunnerPort


class InlineGithubPollRunner(GithubPollRunnerPort):
    def __init__(self):
        self.starts = 0

    def start(self, fn):
        self.starts += 1
        fn()
        return True

    def join(self):
        pass

    def running(self):
        return False


class BlockingGithubPollRunner(GithubPollRunnerPort):
    def __init__(self):
        self.starts = 0
        self.pending = []

    def start(self, fn):
        if self.pending:
            return False
        self.starts += 1
        self.pending.append(fn)
        return True

    def join(self):
        pass

    def running(self):
        return bool(self.pending)
