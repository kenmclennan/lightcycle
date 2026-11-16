import unittest
from types import SimpleNamespace
from unittest import mock

from lightcycle import cli as cli_mod
from lightcycle.commands import pool as pool_commands
from lightcycle.application.pool.breaker_gate import BreakerGateResponse
from lightcycle.application.pool.callout_dispatch import CalloutDispatchResponse
from lightcycle.application.pool.monitor_prs import MonitorPrsResponse
from lightcycle.application.pool.script_stages import ScriptStagesResponse
from lightcycle.application.pool.sweep import SweepResponse
from lightcycle.application.pool.tick import TickInput
from lightcycle.domain.pool import Breaker
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_pool import FakeSpawner, make_tick
from tests.unit.test_tick_lifecycle_gate import _Config, _Reload

FIRST = ((10.0, 20.0),)
SECOND = ((10.0, 20.0), (30.0, 40.0))


class Events:
    def __init__(self):
        self.log = []
        self.received = {}

    def record(self, name, sleeps):
        self.log.append(name)
        self.received[name] = sleeps


class RecordingMonitor:
    def __init__(self, events):
        self._events = events

    def execute(self, sleeps=()):
        self._events.record("monitor", sleeps)
        return MonitorPrsResponse(merged=[])

    def reset(self):
        return None


class RecordingScriptGate:
    def __init__(self, events):
        self._events = events

    def execute(self, now, sleeps=()):
        self._events.record("scripts", sleeps)
        return ScriptStagesResponse()

    def reset(self):
        return None


class RecordingCalloutGate:
    def __init__(self, events):
        self._events = events

    def execute(self, now, sleeps=()):
        self._events.record("callouts", sleeps)
        return CalloutDispatchResponse()


class RecordingBreakerGate:
    def __init__(self, events):
        self._events = events

    def execute(self, now, sleeps=()):
        self._events.record("breaker", sleeps)
        return BreakerGateResponse(breaker=Breaker())


class RecordingSweep:
    def __init__(self, events):
        self._events = events

    def execute(self, now, max_boot, stall_seconds, sleeps=()):
        self._events.record("sweep", sleeps)
        return SweepResponse(swept=[], killed=[], pruned=0)


class TestTickSleeps(unittest.TestCase):
    def test_the_tick_observes_twice_and_feeds_every_gate(self):
        events = Events()
        answers = iter([FIRST, SECOND])

        def sleeps():
            events.log.append("observe")
            return next(answers)

        tick = make_tick(
            FakeStore(), FakeWorkers(), FakeSpawner(), _Config(),
            monitor=RecordingMonitor(events), script_gate=RecordingScriptGate(events),
            callout_gate=RecordingCalloutGate(events), breaker_gate=RecordingBreakerGate(events),
            sweep=RecordingSweep(events), config_reload=_Reload("unchanged"), sleeps=sleeps)

        tick.execute(TickInput(now=7.0))

        self.assertEqual(events.log.count("observe"), 2)
        self.assertLess(events.log.index("observe"), events.log.index("monitor"))
        self.assertEqual(events.log[events.log.index("sweep") - 1], "observe")
        for gate in ("monitor", "scripts", "callouts", "breaker"):
            self.assertEqual(events.received[gate], FIRST, gate)
        self.assertEqual(events.received["sweep"], SECOND)

    def test_lc_sweep_and_stop_observe_first(self):
        order = []
        observed = SimpleNamespace(
            execute=lambda wall, awake: order.append("observe") or FIRST)
        sweeper = SimpleNamespace(
            execute=lambda now, boot, stall, sleeps=(): order.append(("sweep", sleeps)) or
            SweepResponse(swept=[], killed=[], pruned=0))
        config = SimpleNamespace(
            max_boot_seconds=lambda: 120, stall_seconds=lambda: 1800,
            shutdown_grace_seconds=lambda: 0)
        fake = SimpleNamespace(
            observe_sleep=lambda: observed, sweep=lambda: sweeper, config=config)

        with mock.patch.object(pool_commands, "container", lambda: fake):
            pool_commands.cmd_sweep([])

        self.assertEqual(order, ["observe", ("sweep", FIRST)])

        stopped = []
        stop_use_case = SimpleNamespace(
            execute=lambda now, boot, stall, shutdown_grace_seconds=0, sleeps=():
            stopped.append(("stop", sleeps)) or SimpleNamespace(
                stopped=[], survivors=[], reclaimed=[], preserved=[], capture_failed=[],
                scripts_terminated=[], scripts_killed=[]))
        fake_stop = SimpleNamespace(
            observe_sleep=lambda: observed, stop_pool=lambda flow=None: stop_use_case,
            config=config)
        order.clear()

        with mock.patch.object(cli_mod, "_container", fake_stop), \
                mock.patch.object(cli_mod, "_flow", lambda: None):
            cli_mod._stop_pool()

        self.assertEqual(order, ["observe"])
        self.assertEqual(stopped, [("stop", FIRST)])


if __name__ == "__main__":
    unittest.main()
