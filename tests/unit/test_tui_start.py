import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import lightcycle.cli as cli_mod
from tests.support.tui_harness import FakeLock


class _Fs:
    def __init__(self, ready):
        self._ready = ready

    def store_ready(self):
        return self._ready


class _Spawner:
    def __init__(self):
        self.pools = 0

    def spawn_pool(self):
        self.pools += 1
        return 4242


class _Container:
    def __init__(self, lock, ready=True):
        self.lock = lock
        self.fs = _Fs(ready)
        self.spawner = _Spawner()


class TestTuiStart(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, container, *argv):
        cli_mod.set_container(container)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("lightcycle.adapters.tui.app.run") as run:
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli_mod.cmd_tui(list(argv))
        return rc, out.getvalue(), err.getvalue(), run

    def test_start_with_no_pool_spawns_one_detached_and_opens_the_tui(self):
        c = _Container(FakeLock(running=False))
        rc, out, _, run = self._run(c, "--start")
        self.assertEqual(rc, 0)
        self.assertEqual(c.spawner.pools, 1)
        self.assertIn("4242", out)
        run.assert_called_once_with(c)

    def test_start_with_a_running_pool_notes_it_and_opens_the_tui(self):
        c = _Container(FakeLock(running=True, pid=42))
        rc, out, _, run = self._run(c, "--start")
        self.assertEqual((rc, out.strip()), (0, "pool already running, pid 42"))
        self.assertEqual(c.spawner.pools, 0)
        run.assert_called_once_with(c)

    def test_start_without_a_store_exits_non_zero_and_skips_the_tui(self):
        c = _Container(FakeLock(running=False), ready=False)
        rc, out, err, run = self._run(c, "--start")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("lc init", err)
        self.assertEqual(c.spawner.pools, 0)
        run.assert_not_called()

    def test_plain_tui_never_touches_the_pool(self):
        c = _Container(FakeLock(running=False))
        rc, out, _, run = self._run(c)
        self.assertEqual((rc, out), (0, ""))
        self.assertEqual(c.spawner.pools, 0)
        run.assert_called_once_with(c)

    def test_tui_help_lists_start(self):
        with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            cli_mod.cmd_tui(["--help"])
        self.assertIn("--start", out.getvalue())
