from dataclasses import dataclass
from typing import Optional

from lightcycle.config import RELOAD_RELOADED, RELOAD_UNCHANGED, RESTART_REQUIRED_KEYS


@dataclass(frozen=True)
class ReloadConfigResponse:
    outcome: str
    reason: Optional[str] = None
    mtime: Optional[int] = None
    restart_required: tuple = ()


class ReloadConfigUseCase:
    def __init__(self, config, status, pid):
        self._config = config
        self._status = status
        self._pid = pid
        self._start_values = config.raw_values(RESTART_REQUIRED_KEYS)
        self._announced = False
        self._restart_required = ()
        self._rejected_mtime = None

    def _save(self, outcome, reason=None):
        self._status.save({
            "pid": self._pid,
            "outcome": outcome,
            "reason": reason,
            "rejected_mtime": self._rejected_mtime,
            "restart_required": list(self._restart_required),
        })

    def execute(self) -> ReloadConfigResponse:
        if not self._announced:
            self._announced = True
            self._save(RELOAD_UNCHANGED)
        result = self._config.try_reload(self._start_values)
        if result.outcome == RELOAD_UNCHANGED:
            return ReloadConfigResponse(RELOAD_UNCHANGED, mtime=result.mtime)
        if result.outcome == RELOAD_RELOADED:
            self._restart_required = result.restart_required
            self._rejected_mtime = None
        else:
            self._rejected_mtime = result.mtime
        self._save(result.outcome, result.reason)
        return ReloadConfigResponse(
            result.outcome, result.reason, result.mtime, self._restart_required)
