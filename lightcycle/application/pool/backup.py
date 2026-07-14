from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class BackupResponse:
    created: Optional[str] = None
    pruned: List[str] = field(default_factory=list)


class BackupUseCase:
    def __init__(self, backup_port, config):
        self._backup_port = backup_port
        self._config = config

    def execute(self, now) -> BackupResponse:
        snapshots = self._backup_port.list_snapshots()
        interval_seconds = self._config.backup_interval_minutes() * 60
        if snapshots and (now - snapshots[0][1]) < interval_seconds:
            return BackupResponse()
        created = self._backup_port.create_snapshot(now)
        pruned = self._backup_port.prune(self._config.backup_retention())
        return BackupResponse(created=created, pruned=pruned)
