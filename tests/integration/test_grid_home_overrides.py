import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TG = str(ROOT / "bin" / "lc")


def _env(home, xdg):
    env = dict(os.environ, LC_HOME=home, XDG_CONFIG_HOME=xdg)
    env.pop("LC_CONFIG", None)
    env.pop("LC_ROOT_OVERRIDE", None)
    return env


def _run(args, home, xdg):
    return subprocess.run([sys.executable, TG, *args], capture_output=True, text=True,
                          env=_env(home, xdg))


class TestGridHomeOverrides(unittest.TestCase):
    def test_init_scaffolds_the_override_dirs(self):
        home, xdg = tempfile.mkdtemp(), tempfile.mkdtemp()
        r = _run(["init"], home, xdg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(Path(home, "steps").is_dir())
        self.assertTrue(Path(home, "workflows").is_dir())

    def test_a_grid_home_workflow_shadows_the_packaged_default(self):
        home, xdg = tempfile.mkdtemp(), tempfile.mkdtemp()
        _run(["init"], home, xdg)
        self.assertIn("open-pr", _run(["flow"], home, xdg).stdout)
        Path(home, "workflows", "standard.md").write_text(
            "entry: build\n\nnodes:\n  build  coder\n"
        )
        out = _run(["flow"], home, xdg).stdout
        self.assertIn("build", out)
        self.assertNotIn("open-pr", out)


if __name__ == "__main__":
    unittest.main()
