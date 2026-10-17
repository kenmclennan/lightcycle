from dataclasses import dataclass
from typing import Optional

from lightcycle.application.pool.resolve_log import ResolveLogInput, ResolveLogUseCase
from lightcycle.domain.work import State, latest_log_path


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
    def __init__(self, store, workers, fs, probe, config):
        self._store = store
        self._resolve = ResolveLogUseCase(store, workers, probe, config)
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
            if w.step == target or w.role == target:
                return self._workers.pid_alive(w.pid, w.pid_started)
        return self._run_log_live(target)

    def _run_log_live(self, target):
        try:
            node = self._store.get_node(target)
        except KeyError:
            return False
        return (
            node.type == "step" and latest_log_path(self._store.item_artifacts(node.id)) is not None
            and node.state == State.QUEUED)
