import os
import signal
import threading
import time

from lightcycle.ports.run_groups import RunGroupsPort, StoppedRuns


def _signal_group(pid, signum):
    try:
        os.killpg(pid, signum)
    except (ProcessLookupError, PermissionError):
        return


class RunGroupsAdapter(RunGroupsPort):
    def __init__(self, sleep=time.sleep, clock=time.monotonic):
        self._runs = {}
        self._lock = threading.Lock()
        self._sleep = sleep
        self._clock = clock

    def register(self, label, proc):
        with self._lock:
            self._runs[proc.pid] = (label, proc)

    def release(self, proc):
        with self._lock:
            self._runs.pop(proc.pid, None)

    def stop(self, grace_seconds):
        with self._lock:
            runs = dict(self._runs)
        for pid in runs:
            _signal_group(pid, signal.SIGTERM)
        deadline = self._clock() + grace_seconds
        pending = dict(runs)
        while pending:
            pending = {k: v for k, v in pending.items() if v[1].poll() is None}
            if not pending or self._clock() >= deadline:
                break
            self._sleep(0.05)
        for pid in runs:
            _signal_group(pid, signal.SIGKILL)
        return StoppedRuns(
            terminated=sorted(label for label, _ in runs.values()),
            killed=sorted(label for label, _ in pending.values()))
