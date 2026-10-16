import contextlib
import io
import unittest

from lightcycle.application.pool.lifecycle_cadence import LifecycleCadenceResponse
from lightcycle.application.pool.tick import TickInput
from lightcycle.config import RELOAD_RELOADED
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_pool import FakeSpawner, make_tick


class RecordingLifecycleGate:
    def __init__(self, fail=None):
        self.seen = []
        self.resets = 0
        self.fail = fail

    def execute(self, now):
        self.seen.append(now)
        if self.fail:
            raise self.fail
        return LifecycleCadenceResponse(started=["acme/build"])

    def reset(self):
        self.resets += 1

    def in_flight(self):
        return []


class _Reload:
    def __init__(self, outcome):
        self._outcome = outcome

    def execute(self):
        return type("R", (), {"outcome": self._outcome, "reason": None})()


class _Config:
    def max_agents(self):
        return 1

    def max_boot_seconds(self):
        return 1

    def stall_seconds(self):
        return 1

    def poll_seconds(self):
        return 1

    def spin_cap(self):
        return 3


def _tick(gate, outcome="unchanged"):
    return make_tick(
        FakeStore(), FakeWorkers(), FakeSpawner(), _Config(),
        lifecycle_gate=gate, config_reload=_Reload(outcome))


class TestTickLifecycleGate(unittest.TestCase):
    def test_the_gate_runs_each_tick_and_its_result_is_surfaced(self):
        gate = RecordingLifecycleGate()
        response = _tick(gate).execute(TickInput(now=7.0))
        self.assertEqual(gate.seen, [7.0])
        self.assertEqual(response.lifecycle.started, ["acme/build"])

    def test_a_reloaded_config_resets_the_gate(self):
        gate = RecordingLifecycleGate()
        _tick(gate, RELOAD_RELOADED).execute(TickInput(now=1.0))
        self.assertEqual(gate.resets, 1)

    def test_a_failing_gate_warns_and_the_tick_continues(self):
        gate = RecordingLifecycleGate(fail=OSError("state file unreadable"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            response = _tick(gate).execute(TickInput(now=1.0))
        self.assertIsNone(response.lifecycle)
        self.assertIn("warning: lifecycle check failed: state file unreadable", err.getvalue())
        self.assertEqual(response.spawned, [])
