import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest import mock

from lightcycle.application.pool.sweep import SweepEnd, SweepResponse
from lightcycle.commands import pool as pool_commands


class TestCmdSweepOutput(unittest.TestCase):
    def _run(self, response):
        sweeper = SimpleNamespace(execute=lambda now, boot, stall, sleeps=(): response)
        config = SimpleNamespace(max_boot_seconds=lambda: 120, stall_seconds=lambda: 1800)
        observed = SimpleNamespace(execute=lambda wall, awake: ())
        fake = SimpleNamespace(observe_sleep=lambda: observed, sweep=lambda: sweeper, config=config)
        out = io.StringIO()
        with mock.patch.object(pool_commands, "container", lambda: fake), contextlib.redirect_stdout(out):
            pool_commands.cmd_sweep([])
        return out.getvalue()

    def test_cmd_sweep_prints_the_reason(self):
        out = self._run(SweepResponse(
            swept=["x.1"], killed=[], pruned=0, ended={"x.1": SweepEnd("pool-stopped", 3)}))

        self.assertEqual(out.strip(), "swept x.1  (session 3 ended: pool-stopped)")

    def test_cmd_sweep_without_a_reason_prints_the_bare_line(self):
        out = self._run(SweepResponse(swept=["x.1"], killed=[], pruned=0))

        self.assertEqual(out.strip(), "swept x.1")
