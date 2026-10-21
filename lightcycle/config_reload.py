from dataclasses import dataclass
from typing import Optional

RESTART_REQUIRED_KEYS = ("poll-seconds", "pool-upgrade-check-seconds", "tick-failure-cap", "spin-cap")

RELOAD_UNCHANGED = "unchanged"
RELOAD_RELOADED = "reloaded"
RELOAD_REJECTED = "rejected"


@dataclass(frozen=True)
class ConfigReloadResult:
    outcome: str
    reason: Optional[str] = None
    mtime: Optional[int] = None
    restart_required: tuple = ()


def rejection_reason(bad):
    reason = bad[0].error
    if len(bad) > 1:
        reason = "%s (and %d more)" % (reason, len(bad) - 1)
    return reason


def restart_required(candidate, start_values, env_overridden):
    return tuple(
        k for k in RESTART_REQUIRED_KEYS
        if k in start_values
        and not env_overridden(k)
        and candidate.get(k) != start_values[k]
    )
