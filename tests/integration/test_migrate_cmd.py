import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TG = str(ROOT / "bin" / "lc")


def _run_migrate(new, legacy, xdg):
    env = dict(os.environ, LC_HOME=new, LC_LEGACY_HOME=legacy, XDG_CONFIG_HOME=xdg)
    env.pop("LC_CONFIG", None)
    env.pop("LC_ROOT_OVERRIDE", None)
    return subprocess.run([sys.executable, TG, "migrate"], capture_output=True, text=True, env=env)


class TestMigrateCommand(unittest.TestCase):
    def test_moves_a_legacy_store_into_lightcycle_home(self):
        new, legacy, xdg = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        Path(legacy, ".grid.db").write_text("live-backlog")
        r = _run_migrate(new, legacy, xdg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("migrated", r.stdout)
        self.assertEqual(Path(new, "store.db").read_text(), "live-backlog")
        self.assertFalse(Path(legacy, ".grid.db").exists())

    def test_runs_before_the_store_is_created(self):
        new, legacy, xdg = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        Path(legacy, ".grid.db").write_text("live")
        _run_migrate(new, legacy, xdg)
        self.assertEqual(Path(new, "store.db").read_text(), "live")

    def test_is_idempotent_when_already_on_the_new_layout(self):
        new, legacy, xdg = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        Path(new, "store.db").write_text("already")
        Path(legacy, ".grid.db").write_text("live")
        r = _run_migrate(new, legacy, xdg)
        self.assertIn("nothing to migrate", r.stdout)
        self.assertTrue(Path(legacy, ".grid.db").exists())


if __name__ == "__main__":
    unittest.main()
