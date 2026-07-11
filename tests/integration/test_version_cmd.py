import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lightcycle import __version__

ROOT = Path(__file__).resolve().parents[2]
TG = str(ROOT / "bin" / "lc")


def _run(args):
    new, xdg = tempfile.mkdtemp(), tempfile.mkdtemp()
    env = dict(os.environ, LC_HOME=new, XDG_CONFIG_HOME=xdg)
    env.pop("LC_CONFIG", None)
    return subprocess.run([sys.executable, TG] + args, capture_output=True, text=True, env=env)


class TestVersionCommand(unittest.TestCase):
    def test_version_subcommand_prints_version_with_no_store(self):
        r = _run(["version"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "lightcycle %s" % __version__)

    def test_version_flag_prints_version_with_no_store(self):
        r = _run(["--version"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "lightcycle %s" % __version__)


if __name__ == "__main__":
    unittest.main()
