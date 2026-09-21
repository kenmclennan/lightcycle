import shutil
import subprocess
import tempfile
import unittest

from lightcycle import cli
from tests.unit.test_workflow_check_dir import _Container, _bundle, _break, run_check


class TestWorkflowCheckDirDirtyTree(unittest.TestCase):
    def test_uncommitted_edit_is_seen(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cli.set_container(_Container())
        _bundle(tmp)
        git = ["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run([*git, "init", "-q"], check=True, timeout=30)
        subprocess.run([*git, "add", "."], check=True, timeout=30)
        subprocess.run([*git, "commit", "-qm", "init"], check=True, timeout=30)
        rc, _out, err = run_check("--dir", tmp, "spec-driven")
        self.assertEqual(rc, 0, err)
        _break(tmp)
        rc, _out, err = run_check("--dir", tmp, "spec-driven")
        self.assertEqual(rc, 1)
        self.assertIn("nonexistent-frag", err)


if __name__ == "__main__":
    unittest.main()
