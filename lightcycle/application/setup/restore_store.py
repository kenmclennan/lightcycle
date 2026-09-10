from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.pool import AcquireRunLockUseCase, ReleaseRunLockUseCase


@dataclass(frozen=True)
class RestoreInput:
    snapshot: Optional[str]
    force: bool


@dataclass(frozen=True)
class RestoreResponse:
    snapshot: str
    taken_at: float


class RestoreStoreUseCase:
    def __init__(self, lock, store, backup, config):
        self._lock = lock
        self._store = store
        self._backup = backup
        self._config = config

    def execute(self, input: RestoreInput) -> RestoreResponse:
        snapshots = self._backup.list_snapshots()
        if not snapshots:
            raise UseCaseError("lc restore: no snapshots in %s" % self._config.backups_dir())
        if input.snapshot is None:
            target, target_mtime = snapshots[0].name, snapshots[0].taken_at
        else:
            match = next((s for s in snapshots if s.name == input.snapshot), None)
            if match is None:
                raise UseCaseError("lc restore: no such snapshot %s" % input.snapshot)
            target, target_mtime = match.name, match.taken_at
        if not input.force:
            raise UseCaseError(
                "lc restore: this would overwrite the live store from %s; re-run with --force"
                % target
            )
        lock_result = AcquireRunLockUseCase(self._lock).execute()
        if not lock_result.acquired:
            raise UseCaseError(
                "lc restore: lc start is running (pid %d); stop it first" % lock_result.holder_pid
            )
        try:
            self._store.release()
            self._backup.restore(target)
        finally:
            ReleaseRunLockUseCase(self._lock).execute()
        return RestoreResponse(snapshot=target, taken_at=target_mtime)
