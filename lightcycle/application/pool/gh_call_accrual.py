import os

from lightcycle.domain.work.worker_log import gh_calls_filename
from lightcycle.ports.workers import RegistryUnreadable


class GhCallAccrualUseCase:
    def __init__(self, store, worker_log, workers, config):
        self._store = store
        self._worker_log = worker_log
        self._workers = workers
        self._config = config
        self._offsets = {}
        self._counts = {}

    def execute(self):
        try:
            workers = self._workers.workers_state()
        except RegistryUnreadable:
            return
        logs = os.path.join(self._config.data_root(), "logs")
        for w in workers:
            if not w.spawnid or not w.step:
                continue
            self._accrue(w, os.path.join(logs, gh_calls_filename(w.spawnid)))

    def _accrue(self, w, path):
        offset = self._offsets.get(w.spawnid, 0)
        data, _ = self._worker_log.read_from(path, offset)
        last_newline = data.rfind(b"\n")
        if last_newline == -1:
            return
        added = data[: last_newline + 1].count(b"\n")
        self._offsets[w.spawnid] = offset + last_newline + 1
        total = self._counts.get(w.spawnid, 0) + added
        self._counts[w.spawnid] = total
        self._store.record_gh_calls(w.spawnid, w.step, total)
