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
        acquired, holder_pid = self._lock.acquire()
        return AcquireRunLockResponse(acquired=acquired, holder_pid=holder_pid)


class ReleaseRunLockUseCase:
    def __init__(self, lock):
        self._lock = lock

    def execute(self):
        self._lock.release()
