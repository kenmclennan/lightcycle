from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AcquireRunLockResponse:
    acquired: bool
    holder_pid: Optional[int]


class AcquireRunLockUseCase:
    def __init__(self, lock):
        self._lock = lock

    def execute(self) -> AcquireRunLockResponse:
        result = self._lock.acquire()
        return AcquireRunLockResponse(acquired=result.acquired, holder_pid=result.holder_pid)


class ReleaseRunLockUseCase:
    def __init__(self, lock):
        self._lock = lock

    def execute(self):
        self._lock.release()


@dataclass(frozen=True)
class PoolRunningResponse:
    running: bool
    holder_pid: Optional[int] = None


class PoolRunningUseCase:
    def __init__(self, lock):
        self._lock = lock

    def execute(self) -> PoolRunningResponse:
        pid = self._lock.holder_pid()
        return PoolRunningResponse(running=pid is not None, holder_pid=pid)
