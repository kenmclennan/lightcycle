"""End-to-end smoke test: one tg + bd subprocess path against a real bd store.

SmokeTest is the only test class in this suite that spawns tg as a subprocess
against a live bd store. All other integration tests use FakeStore in-process.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TG = str(ROOT / "bin" / "tg")

_CODER_STEP = """\
---
model: sonnet
step: build
routes:
  done: review
---
# coder
stub
"""

_REVIEWER_STEP = """\
---
model: opus
step: review
---
# reviewer
stub
"""


def _tg(*args, root):
    env = dict(os.environ)
    env["GRID_ROOT_OVERRIDE"] = root
    env["GRID_CONFIG"] = os.path.join(root, "grid.config")
    return subprocess.run([sys.executable, TG, *args], capture_output=True, text=True, env=env)


def _bd_init():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(
        ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
        cwd=d, check=True,
    )
    return d


class SmokeTest(unittest.TestCase):
    """End-to-end: create -> claim -> done -> advance -> show via tg subprocess + real bd store."""

    def setUp(self):
        self.root = _bd_init()
        steps = Path(self.root) / "steps"
        steps.mkdir()
        (steps / "coder.md").write_text(_CODER_STEP)
        (steps / "reviewer.md").write_text(_REVIEWER_STEP)
        ws = tempfile.mkdtemp()
        Path(self.root, "grid.config").write_text("projects: %s\nspecs: %s\n" % (ws, ws))

    def test_create_claim_done_advance_show(self):
        r = _tg("file", "specs/smoke.md", "--step", "build", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)

        r = _tg("claim", "coder", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        task = json.loads(r.stdout)
        self.assertEqual(task["status"], "in-progress")
        build_id = task["id"]

        r = _tg("done", build_id, "done", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        review_id = r.stdout.strip()
        self.assertTrue(review_id, "tg done should print the next task id")

        r = _tg("show", review_id, root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        shown = json.loads(r.stdout)
        self.assertEqual(shown["role"], "reviewer")
        self.assertEqual(shown["step"], "review")
        self.assertEqual(shown["status"], "ready")


if __name__ == "__main__":
    unittest.main()
