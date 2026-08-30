from dataclasses import dataclass
from typing import Optional

from lightcycle.application.pool.resolve_log import ResolveLogInput, ResolveLogUseCase


@dataclass(frozen=True)
class TailLogInput:
    target: str
    offset: int = 0
    max_bytes: Optional[int] = None


@dataclass(frozen=True)
class TailLogResult:
    path: Optional[str]
    data: bytes
    offset: int
    live: bool


class TailLogUseCase:
    def __init__(self, store, workers, fs, config):
        self._resolve = ResolveLogUseCase(store, workers, config)
        self._workers = workers
        self._fs = fs

    def execute(self, input: TailLogInput) -> TailLogResult:
        path = self._resolve.execute(ResolveLogInput(target=input.target)).path
        if path is None:
            return TailLogResult(path=None, data=b"", offset=input.offset, live=False)
        if input.max_bytes is not None:
            data, offset = self._fs.read_tail(path, input.max_bytes)
        else:
            data, offset = self._fs.read_from(path, input.offset)
        return TailLogResult(path=path, data=data, offset=offset, live=self._worker_alive(input.target))

    def _worker_alive(self, target):
        for w in reversed(self._workers.workers_state()):
            if w.get("step") == target or w.get("role") == target:
                return self._workers.pid_alive(w.get("pid"), w.get("pid_started"))
        return False
