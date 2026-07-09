import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TG = str(ROOT / "bin" / "lc")


def _run(args):
    new, legacy, xdg = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
    env = dict(os.environ, LC_HOME=new, LC_LEGACY_HOME=legacy, XDG_CONFIG_HOME=xdg)
    env.pop("LC_CONFIG", None)
    env.pop("LC_ROOT_OVERRIDE", None)
    return subprocess.run([sys.executable, TG] + args, capture_output=True, text=True, env=env)


class TestUpgradeCommand(unittest.TestCase):
    def test_check_runs_with_no_store_and_exits_zero(self):
        r = _run(["upgrade", "--check"])
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
