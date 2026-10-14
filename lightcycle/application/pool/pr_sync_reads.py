class PrSyncReads:
    def __init__(self, github):
        self._github = github
        self._reads = {}

    def read(self, pr):
        if pr not in self._reads:
            self._reads[pr] = self._github.pr_sync_state(pr)
        return self._reads[pr]
