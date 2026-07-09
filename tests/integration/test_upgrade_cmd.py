import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TG = str(ROOT / "bin" / "lc")


def _run(args):
    home, legacy, xdg = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
    env = dict(os.environ, LC_HOME=home, LC_LEGACY_HOME=legacy, XDG_CONFIG_HOME=xdg)
    env.pop("LC_CONFIG", None)
    env.pop("LC_ROOT_OVERRIDE", None)
    result = subprocess.run([sys.executable, TG] + args, capture_output=True, text=True, env=env)
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


if __name__ == "__main__":
    unittest.main()
