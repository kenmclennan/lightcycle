import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.setup.upgrade import scan_venv_holders

ROOT = Path(__file__).resolve().parents[2]
LC = str(ROOT / "bin" / "lc")


def _run(args):
    home, xdg = tempfile.mkdtemp(), tempfile.mkdtemp()
    env = dict(os.environ, LC_HOME=home, XDG_CONFIG_HOME=xdg)
    env.pop("LC_CONFIG", None)
    result = subprocess.run([sys.executable, LC] + args, capture_output=True, text=True, env=env)
    return result, home


class TestUpgradeCommand(unittest.TestCase):
    def test_check_is_store_less_and_exits_cleanly(self):
        result, home = _run(["upgrade", "--check"])
        self.assertFalse(
            os.path.exists(os.path.join(home, "store.db")),
            "upgrade --check must run before the store is built",
        )
        self.assertIn(
            result.returncode,
            (0, 1),
            "expected a clean exit (0 checked, 1 network error), got:\n%s" % result.stderr,
        )


class TestScanVenvHolders(unittest.TestCase):
    def test_finds_the_current_process_when_not_excluded(self):
        holders = scan_venv_holders(exclude_pid=1)
        self.assertIn(os.getpid(), [pid for pid, _ in holders])

    def test_excludes_the_given_pid(self):
        holders = scan_venv_holders(exclude_pid=os.getpid())
        self.assertNotIn(os.getpid(), [pid for pid, _ in holders])


if __name__ == "__main__":
    unittest.main()
