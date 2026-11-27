import signal
from dataclasses import dataclass, field
from typing import List

from lightcycle.domain.pool import WorkerPool
from lightcycle.ports.workers import RegistryUnreadable

SIGTERM = int(signal.SIGTERM)
SIGKILL = int(signal.SIGKILL)
SIGCONT = int(signal.SIGCONT)
POLL_SECONDS = 0.05


@dataclass(frozen=True)
class OrphanProcess:
    pid: int
    worktree: str


@dataclass(frozen=True)
class OrphanReapResponse:
    ended: List[OrphanProcess] = field(default_factory=list)
    unended: List[OrphanProcess] = field(default_factory=list)
    left: List[OrphanProcess] = field(default_factory=list)


class ReapOrphanProcessesUseCase:
    def __init__(self, orphans, workers, machine, config, sleep, clock):
        self._orphans = orphans
        self._workers = workers
        self._machine = machine
        self._config = config
        self._sleep = sleep
        self._clock = clock

    def execute(self):
        entries = self._orphans.scan()
        if not entries:
            return OrphanReapResponse()
        try:
            live = {
                int(w.pid) for w in WorkerPool(self._workers.workers_state()).alive(
                    self._workers.pid_alive)
                if w.pid is not None
            }
        except RegistryUnreadable:
            return OrphanReapResponse()
        left = []
        candidates = []
        for entry in entries:
            for pid in entry.pids:
                if pid in live:
                    continue
                target = left if entry.exists else candidates
                target.append(OrphanProcess(pid, entry.path))
        signalled = [
            c for c in candidates if self._signal(c.pid, SIGCONT) | self._signal(c.pid, SIGTERM)
        ]
        grace = self._config.shutdown_grace_seconds()
        deadline = self._clock() + grace
        survivors = self._alive(signalled)
        while survivors and grace > 0 and self._clock() < deadline:
            self._sleep(POLL_SECONDS)
            survivors = self._alive(survivors)
        killed = []
        for c in survivors:
            if c.pid in self._orphans.pids_still_under(c.worktree):
                self._signal(c.pid, SIGCONT)
                self._signal(c.pid, SIGKILL)
                killed.append(c)
        if killed:
            self._sleep(POLL_SECONDS)
        unended = [c for c in killed if self._machine.signal_pid(c.pid, 0)]
        unended_pids = {c.pid for c in unended}
        ended = [
            c for c in signalled
            if c.pid not in unended_pids and not self._machine.signal_pid(c.pid, 0)
        ]
        return OrphanReapResponse(ended=ended, unended=unended, left=left)

    def _alive(self, candidates):
        return [c for c in candidates if self._machine.signal_pid(c.pid, 0)]

    def _signal(self, pid, sig):
        return bool(self._machine.signal_pid(pid, sig))
