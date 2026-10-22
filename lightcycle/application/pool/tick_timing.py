from lightcycle.config import ConfigError
from lightcycle.domain.pool import tick_health, tick_timing_recorded, tick_timing_started


class RecordTickTimingUseCase:
    def __init__(self, tick_timing_status, config):
        self._status = tick_timing_status
        self._config = config

    def started(self, pid, now):
        self._status.save(tick_timing_started(pid, now))

    def finished(self, pid, finished_at, duration):
        self._status.save(tick_timing_recorded(
            self._status.load(), pid, finished_at, duration,
            self._config.tick_lag_window_seconds()))


class TickHealthUseCase:
    def __init__(self, tick_timing_status, config):
        self._status = tick_timing_status
        self._config = config

    def reading(self, running, holder_pid, now):
        if not running:
            return None
        timing = self._status.load()
        if timing is None or timing.pid != holder_pid:
            return None
        try:
            return tick_health(
                timing, now, self._config.poll_seconds(),
                self._config.tick_lag_window_seconds(), self._config.tick_lag_share(),
                self._config.tick_stall_seconds())
        except ConfigError:
            return None
