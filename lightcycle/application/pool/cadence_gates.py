import sys
from dataclasses import dataclass
from typing import Optional

from lightcycle.application.pool.lifecycle_cadence import LifecycleCadenceResponse
from lightcycle.application.pool.schedule_cadence import ScheduleCadenceResponse
from lightcycle.application.pool.script_stages import ScriptStagesResponse
from lightcycle.config import ConfigError
from lightcycle.ports.git import GitReadError


@dataclass(frozen=True)
class CadenceGatesResponse:
    schedules: Optional[ScheduleCadenceResponse] = None
    lifecycle: Optional[LifecycleCadenceResponse] = None
    scripts: Optional[ScriptStagesResponse] = None


class CadenceGatesUseCase:
    def __init__(self, schedule_gate, lifecycle_gate, script_gate):
        self._schedule_gate = schedule_gate
        self._lifecycle_gate = lifecycle_gate
        self._script_gate = script_gate

    def _schedules(self, now):
        try:
            return self._schedule_gate.execute(now)
        except (OSError, GitReadError, ValueError) as e:
            sys.stderr.write("warning: schedule check failed: %s\n" % e)
            return None

    def _lifecycle(self, now):
        try:
            return self._lifecycle_gate.execute(now)
        except (OSError, GitReadError, ValueError, ConfigError) as e:
            sys.stderr.write("warning: lifecycle check failed: %s\n" % e)
            return None

    def _scripts(self, now):
        try:
            return self._script_gate.execute(now)
        except (OSError, GitReadError, ValueError, ConfigError) as e:
            sys.stderr.write("warning: script stage check failed: %s\n" % e)
            return None

    def execute(self, now) -> CadenceGatesResponse:
        return CadenceGatesResponse(
            schedules=self._schedules(now),
            lifecycle=self._lifecycle(now),
            scripts=self._scripts(now),
        )

    def reset(self):
        self._schedule_gate.reset()
        self._lifecycle_gate.reset()
        self._script_gate.reset()
