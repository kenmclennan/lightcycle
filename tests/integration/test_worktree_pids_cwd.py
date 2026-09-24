import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from lightcycle.adapters.machine import MachineAdapter


def _spawn(cwd, stdin=None, new_session=False):
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=cwd,
        stdin=stdin,
        start_new_session=new_session,
    )


@unittest.skipUnless(shutil.which("lsof"), "lsof not installed")
class TestWorktreePidsAgainstRealProcesses(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.worktree = os.path.join(self.root, "wt")
        os.makedirs(os.path.join(self.worktree, "sub"))
        self.held = os.path.join(self.worktree, "held.txt")
        open(self.held, "w").close()
        self.children = []

    def tearDown(self):
        for child in self.children:
            child.kill()
            child.wait()
        shutil.rmtree(self.root, ignore_errors=True)

    def _child(self, **kwargs):
        child = _spawn(**kwargs)
        self.children.append(child)
        return child

    def _pids(self, expected):
        deadline = time.time() + 5
        while True:
            pids = MachineAdapter().worktree_pids(self.worktree)
            if all(p in pids for p in expected) or time.time() > deadline:
                return pids
            time.sleep(0.1)

    def test_process_in_its_own_group_with_cwd_under_the_worktree_is_returned(self):
        child = self._child(cwd=os.path.join(self.worktree, "sub"), new_session=True)
        self.assertIn(child.pid, self._pids([child.pid]))

    def test_process_holding_a_file_under_the_worktree_from_elsewhere_is_not_returned(self):
        with open(self.held) as handle:
            vm = self._child(cwd=self.root, stdin=handle)
        cwd_child = self._child(cwd=self.worktree)
        pids = self._pids([cwd_child.pid])
        self.assertIn(cwd_child.pid, pids)
        self.assertNotIn(vm.pid, pids)
