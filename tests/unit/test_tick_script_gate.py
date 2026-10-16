import contextlib
import io
import unittest

from lightcycle.application.pool.script_stages import ScriptStagesResponse
from lightcycle.application.pool.tick import TickInput
from lightcycle.config import RELOAD_RELOADED
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_pool import FakeSpawner, make_tick
from tests.unit.test_tick_lifecycle_gate import _Config, _Reload


class RecordingScriptGate:
    def __init__(self, fail=None):
        self.seen = []
        self.resets = 0
        self.fail = fail

    def execute(self, now):
        self.seen.append(now)
        if self.fail:
            raise self.fail
        return ScriptStagesResponse(started=["step:APP-1.1"])

    def reset(self):
        self.resets += 1


def _tick(gate, outcome="unchanged"):
    return make_tick(
        FakeStore(), FakeWorkers(), FakeSpawner(), _Config(),
        script_gate=gate, config_reload=_Reload(outcome))


class TestTickScriptGate(unittest.TestCase):
    def test_the_gate_runs_each_tick_and_its_result_is_surfaced(self):
        gate = RecordingScriptGate()

        response = _tick(gate).execute(TickInput(now=7.0))

        self.assertEqual(gate.seen, [7.0])
        self.assertEqual(response.scripts.started, ["step:APP-1.1"])

    def test_the_gate_still_runs_while_draining(self):
        gate = RecordingScriptGate()

        _tick(gate).execute(TickInput(now=7.0, drain=True))

        self.assertEqual(gate.seen, [7.0])

    def test_a_reloaded_config_resets_the_gate(self):
        gate = RecordingScriptGate()

        _tick(gate, RELOAD_RELOADED).execute(TickInput(now=1.0))

        self.assertEqual(gate.resets, 1)

    def test_a_failing_gate_warns_and_the_tick_continues(self):
        gate = RecordingScriptGate(fail=OSError("cannot create the data dir"))
        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            response = _tick(gate).execute(TickInput(now=1.0))

        self.assertIsNone(response.scripts)
        self.assertIn("warning: script stage check failed: cannot create the data dir", err.getvalue())
