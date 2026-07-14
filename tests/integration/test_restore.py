import io
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import lightcycle.cli as cli
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.config import Config
from lightcycle.container import Container


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def _config(home, backups_dir):
    cfg_path = os.path.join(tempfile.mkdtemp(), "config")
    Path(cfg_path).write_text(
        "shortcode: xy\n"
        "backups-dir: %s\n"
        "backup-interval-minutes: 15\n"
        "backup-retention: 96\n" % backups_dir
    )
    return Config(environ={"LC_HOME": home, "LC_CONFIG": cfg_path})


class TestRestoreCommand(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.backups_dir = tempfile.mkdtemp()
        self.config = _config(self.home, self.backups_dir)
        self.container = Container(config=self.config)
        self._orig = cli._container
        cli.set_container(self.container)
        self.addCleanup(lambda: cli.set_container(self._orig))

    def _store_bytes(self):
        return Path(self.home, "store.db").read_bytes()

    def test_list_prints_snapshots_and_writes_nothing(self):
        self.container.backup.create_snapshot(time.time())
        before = self._store_bytes()
        rc, out, err = call(cli.cmd_restore, "--list")
        self.assertEqual(rc, 0, err)
        self.assertIn("store-", out)
        self.assertEqual(self._store_bytes(), before)

    def test_missing_force_refuses_and_writes_nothing(self):
        self.container.backup.create_snapshot(time.time())
        before = self._store_bytes()
        rc, out, err = call(cli.cmd_restore)
        self.assertNotEqual(rc, 0)
        self.assertIn("--force", err)
        self.assertEqual(self._store_bytes(), before)

    def test_force_refused_while_run_lock_held_by_a_live_pid(self):
        self.container.backup.create_snapshot(time.time())
        Path(self.home, ".lc-run.pid").write_text(str(os.getpid()))
        before = self._store_bytes()
        rc, out, err = call(cli.cmd_restore, "--force")
        self.assertNotEqual(rc, 0)
        self.assertIn("lc start is running", err)
        self.assertEqual(self._store_bytes(), before)

    def test_force_with_lock_free_restores_snapshot_contents(self):
        tid = self.container.store.create_step("t", role="coder")
        self.container.backup.create_snapshot(time.time())
        later_tid = self.container.store.create_step("added-after-snapshot", role="coder")
        rc, out, err = call(cli.cmd_restore, "--force")
        self.assertEqual(rc, 0, err)
        self.assertFalse(Path(self.home, ".lc-run.pid").exists())
        reopened = SqliteStore(self.config)
        self.assertEqual(reopened.get_node(tid).id, tid)
        with self.assertRaises(KeyError):
            reopened.get_node(later_tid)


if __name__ == "__main__":
    unittest.main()
