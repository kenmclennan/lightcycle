import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from lightcycle.adapters.machine import MachineAdapter
from lightcycle.application.pool.reap_orphan_processes import (
    OrphanProcess, ReapOrphanProcessesUseCase,
)
from lightcycle.application.services.orphaned_worktrees import OrphanedWorktrees
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers


class _Config:
    def shutdown_grace_seconds(self):
        return 0


class _Worktrees:
    def worktree_path(self, node):
        raise KeyError(node)


def _spawn(cwd):
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=cwd, start_new_session=True,
    )


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@unittest.skipUnless(shutil.which("lsof"), "lsof not installed")
class TestOrphanProcessReapAgainstRealProcesses(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.children = []

    def tearDown(self):
        for child in self.children:
            child.kill()
            child.wait()
        shutil.rmtree(self.root, ignore_errors=True)

    def _child(self, cwd):
        child = _spawn(cwd)
        self.children.append(child)
        return child

    def test_real_process_in_deleted_worktree_is_ended_and_others_are_not(self):
        wt = os.path.join(self.root, ".worktrees")
        gone = os.path.join(wt, "gone")
        idle = os.path.join(wt, "idle")
        elsewhere = os.path.join(self.root, "elsewhere")
        for d in (gone, idle, elsewhere):
            os.makedirs(d)
        in_gone = self._child(gone)
        in_idle = self._child(idle)
        in_elsewhere = self._child(elsewhere)
        machine = MachineAdapter()
        deadline = time.time() + 5
        while time.time() < deadline:
            seen = machine.cwd_pids_under(wt)
            if in_gone.pid in seen.get(gone, []) and in_idle.pid in seen.get(idle, []):
                break
            time.sleep(0.1)
        for child in self.children:
            self.assertTrue(_alive(child.pid))
        shutil.rmtree(gone)
        if gone not in machine.cwd_pids_under(wt):
            self.skipTest("a removed cwd is not visible to the scan on this platform")
        store = FakeStore()
        store.add_project("acme", local_path=self.root)
        orphans = OrphanedWorktrees(store, _RealFs(), machine, _Worktrees(), lambda s: None)
        use_case = ReapOrphanProcessesUseCase(
            orphans, FakeWorkers(), machine, _Config(), time.sleep, time.monotonic)

        result = use_case.execute()

        in_gone.wait(timeout=5)
        self.assertFalse(_alive(in_gone.pid) and in_gone.poll() is None)
        self.assertIsNone(in_idle.poll())
        self.assertIsNone(in_elsewhere.poll())
        self.assertEqual(result.ended, [OrphanProcess(in_gone.pid, gone)])
        self.assertEqual(result.left, [OrphanProcess(in_idle.pid, idle)])


class _RealFs(FakeFs):
    def worktrees_dir(self, root):
        return os.path.join(root, ".worktrees")

    def exists(self, path):
        return os.path.exists(path)

    def list_dir(self, path):
        return sorted(os.listdir(path)) if os.path.isdir(path) else []
