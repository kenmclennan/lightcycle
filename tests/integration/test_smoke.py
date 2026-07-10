import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TG = str(ROOT / "bin" / "lc")

_CODER_STEP = """\
---
model: sonnet
step: write-code
routes:
  done: review-code
---
# write-code
stub
"""

_REVIEWER_STEP = """\
---
model: opus
step: review-code
---
# review-code
stub
"""


def _tg(*args, root):
    env = dict(os.environ)
    env["LC_ROOT_OVERRIDE"] = root
    env["LC_CONFIG"] = os.path.join(root, "grid.config")
    return subprocess.run([sys.executable, TG, *args], capture_output=True, text=True, env=env)


def _engine_root():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    return d


class SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _engine_root()
        steps = Path(cls.root) / "steps"
        steps.mkdir()
        (steps / "write-code.md").write_text(_CODER_STEP)
        (steps / "review-code.md").write_text(_REVIEWER_STEP)
        workflows = Path(cls.root) / "workflows"
        workflows.mkdir()
        (workflows / "standard.md").write_text(
            "entry: write-code\n\nedges:\n  write-code  done  review-code\n"
        )
        ws = tempfile.mkdtemp()
        Path(cls.root, "grid.config").write_text(
            "projects: %s\nspecs: %s\nshortcode: tg\n"
            "branch-prefix: feat\ndefault-workflow: standard\nmax-agents: 5\nworktree-retries: 6\n"
            "worktree-retry-sleep: 0.25\nmax-boot-seconds: 120\npoll-seconds: 5\n"
            "worker-history: 20\neditor: vi\n" % (ws, ws)
        )

    def test_add_with_description_and_edit(self):
        r = _tg("new", "item", "my step", "--description", "detail here", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        tid = r.stdout.strip()

        r = _tg("show", tid, root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        shown = json.loads(r.stdout)
        self.assertEqual(shown["description"], "detail here")

        r = _tg(
            "set", tid, "--title", "updated title", "--description", "updated desc", root=self.root
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        r = _tg("show", tid, root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        shown = json.loads(r.stdout)
        self.assertEqual(shown["title"], "updated title")
        self.assertEqual(shown["description"], "updated desc")

    def test_create_claim_done_advance_show(self):
        r = _tg("new", "theme", "smoke objective", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        epic_id = r.stdout.strip()

        r = _tg("new", "item", "smoke", "--parent", epic_id, root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        item_id = r.stdout.strip()
        r = _tg("attach", item_id, "spec", "specs/smoke.md", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = _tg("set", item_id, "--state", "active", "--step", "write-code", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)

        r = _tg("claim", "write-code", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        step = json.loads(r.stdout)
        self.assertEqual(step["state"], "in_progress")
        build_id = step["id"]

        r = _tg("done", build_id, "done", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        review_id = r.stdout.strip()
        self.assertTrue(review_id, "tg done should print the next step id")

        r = _tg("show", review_id, root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        shown = json.loads(r.stdout)
        self.assertEqual(shown["role"], "review-code")
        self.assertEqual(shown["step"], "review-code")
        self.assertEqual(shown["state"], "ready")


if __name__ == "__main__":
    unittest.main()
