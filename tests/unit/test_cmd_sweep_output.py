import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest import mock

from lightcycle.application.pool.reap_orphan_processes import OrphanProcess
from lightcycle.application.pool.sweep import SweepEnd, SweepResponse
from lightcycle.commands import pool as pool_commands


class TestCmdSweepOutput(unittest.TestCase):
    def _run(self, response):
        sweeper = SimpleNamespace(execute=lambda now, boot, stall, sleeps=(): response)
        config = SimpleNamespace(max_boot_seconds=lambda: 120, stall_seconds=lambda: 1800)
        observed = SimpleNamespace(execute=lambda wall, awake: ())
        fake = SimpleNamespace(observe_sleep=lambda: observed, sweep=lambda: sweeper, config=config)
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(pool_commands, "container", lambda: fake), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            pool_commands.cmd_sweep([])
        self.stderr = err.getvalue()
        return out.getvalue()

    def test_cmd_sweep_prints_the_reason(self):
        out = self._run(SweepResponse(
            swept=["x.1"], killed=[], pruned=0, ended={"x.1": SweepEnd("pool-stopped", 3)}))

        self.assertEqual(out.strip(), "swept x.1  (session 3 ended: pool-stopped)")

    def test_cmd_sweep_without_a_reason_prints_the_bare_line(self):
        out = self._run(SweepResponse(swept=["x.1"], killed=[], pruned=0))

        self.assertEqual(out.strip(), "swept x.1")

    def test_cmd_sweep_prints_ended_unended_and_left_orphan_processes(self):
        out = self._run(SweepResponse(
            swept=[], killed=[], pruned=0,
            orphans_ended=[OrphanProcess(11, "/w/a")],
            orphans_unended=[OrphanProcess(12, "/w/b")],
            orphans_left=[OrphanProcess(13, "/w/c")]))

        self.assertEqual(out.strip(), "ended orphan process 11 in /w/a")
        self.assertEqual(self.stderr.splitlines(), [
            "could not end orphan process 12 in /w/b",
            "left orphan process 13 in /w/c (worktree exists, no claimed step)",
        ])
