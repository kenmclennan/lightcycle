import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LC = str(ROOT / "bin" / "lc")


def run_worker(*args):
    env = {"PATH": "/usr/bin:/bin", "LC_HOME": tempfile.mkdtemp(), "LC_WORKER": "1"}
    return subprocess.run(
        [sys.executable, LC, *args], capture_output=True, text=True, env=env
    )


class TestWorkerModeGuard(unittest.TestCase):
    def test_worker_cannot_rm(self):
        r = run_worker("rm", "X")
        self.assertEqual(r.returncode, 1)
        self.assertIn("workers may not run 'rm'", r.stderr)

    def test_worker_cannot_init(self):
        r = run_worker("init")
        self.assertEqual(r.returncode, 1)
        self.assertIn("workers may not run 'init'", r.stderr)

    def test_worker_cannot_set_parent(self):
        r = run_worker("set", "X", "--parent", "Y")
        self.assertEqual(r.returncode, 1)
        self.assertIn("workers may not run 'set'", r.stderr)

    def test_worker_cannot_upgrade(self):
        r = run_worker("upgrade", "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("workers may not run 'upgrade'", r.stderr)

    def test_worker_show_is_not_guard_refused(self):
        r = run_worker("show", "X")
        self.assertNotIn("workers may not run", r.stderr)


if __name__ == "__main__":
    unittest.main()
