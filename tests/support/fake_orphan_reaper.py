from lightcycle.application.pool.reap_orphan_processes import OrphanReapResponse


class NoOpOrphanReaper:
    def execute(self):
        return OrphanReapResponse()


class RecordingOrphanReaper:
    def __init__(self, response=None, log=None):
        self.calls = 0
        self._response = response if response is not None else OrphanReapResponse()
        self._log = log

    def execute(self):
        self.calls += 1
        if self._log is not None:
            self._log.append("reap")
        return self._response
