import unittest

from lightcycle.application.pool.tick_timing import RecordTickTimingUseCase, TickHealthUseCase
from lightcycle.config import ConfigError
from lightcycle.domain.pool import TickTiming
from tests.support.fake_tick_timing_status import FakeTickTimingStatus


class _Config:
    def __init__(self, broken=None):
        self._broken = broken

    def _get(self, name, value):
        if self._broken == name:
            raise ConfigError(name)
        return value

    def poll_seconds(self):
        return self._get("poll_seconds", 5)

    def tick_lag_window_seconds(self):
        return self._get("tick_lag_window_seconds", 300)

    def tick_lag_share(self):
        return self._get("tick_lag_share", 50)

    def tick_stall_seconds(self):
        return self._get("tick_stall_seconds", 120)


class TestRecordTickTiming(unittest.TestCase):
    def test_started_saves_an_empty_timing_for_the_pid(self):
        status = FakeTickTimingStatus()
        RecordTickTimingUseCase(status, _Config()).started(7, 100.0)
        self.assertEqual(status.saves, [TickTiming(7, 100.0, ())])

    def test_finished_accumulates_and_prunes_by_the_configured_window(self):
        status = FakeTickTimingStatus()
        record = RecordTickTimingUseCase(status, _Config())
        record.started(7, 0.0)
        record.finished(7, 10.0, 1.0)
        record.finished(7, 400.0, 2.0)
        self.assertEqual(status.load().ticks, ((400.0, 2.0),))
        self.assertEqual(status.load().finished_at, 400.0)


class TestTickHealthReading(unittest.TestCase):
    def _reading(self, status, running=True, pid=7, now=100.0, config=None):
        return TickHealthUseCase(status, config or _Config()).reading(running, pid, now)

    def test_none_when_the_pool_is_not_running(self):
        status = FakeTickTimingStatus(TickTiming(7, 0.0, ()))
        self.assertIsNone(self._reading(status, running=False, pid=None, now=1000.0))

    def test_none_when_nothing_is_saved(self):
        self.assertIsNone(self._reading(FakeTickTimingStatus()))

    def test_none_on_a_pid_mismatch(self):
        status = FakeTickTimingStatus(TickTiming(6, 0.0, ()))
        self.assertIsNone(self._reading(status, now=1000.0))

    def test_none_when_a_getter_raises_config_error(self):
        status = FakeTickTimingStatus(TickTiming(7, 99.0, ()))
        for name in ("poll_seconds", "tick_lag_window_seconds", "tick_lag_share", "tick_stall_seconds"):
            self.assertIsNone(self._reading(status, config=_Config(broken=name)), name)

    def test_restart_old_pid_reads_none_then_new_pid_is_healthy_then_stalled(self):
        status = FakeTickTimingStatus(TickTiming(6, 0.0, ()))
        record = RecordTickTimingUseCase(status, _Config())
        self.assertIsNone(self._reading(status, pid=7, now=5000.0))
        record.started(7, 5000.0)
        self.assertEqual(self._reading(status, pid=7, now=5120.0).level, "healthy")
        self.assertEqual(self._reading(status, pid=7, now=5121.0).level, "stalled")
