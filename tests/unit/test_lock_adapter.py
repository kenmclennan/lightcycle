import os
import tempfile
import unittest

from lightcycle.adapters.lock import RunLockAdapter
from lightcycle.application.pool import AcquireRunLockUseCase


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def engine_root(self):
        return self._root

    def data_root(self):
        return self._root

    def prompts_root(self):
        return self._root


class TestRunLockAdapter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.lock = RunLockAdapter(FakeConfig(self.root))

    def test_acquire_succeeds_when_no_lock_file(self):
        acquired, holder_pid = self.lock.acquire()
        self.assertTrue(acquired)
        self.assertEqual(holder_pid, os.getpid())

    def test_second_acquire_refused_while_first_alive(self):
        self.lock.acquire()
        acquired, holder_pid = RunLockAdapter(FakeConfig(self.root)).acquire()
        self.assertFalse(acquired)
        self.assertEqual(holder_pid, os.getpid())

    def test_stale_lock_reclaimed(self):
        dead_pid = 999999
        with open(os.path.join(self.root, ".lc-run.pid"), "w") as f:
            f.write(str(dead_pid))
        acquired, holder_pid = self.lock.acquire()
        self.assertTrue(acquired)
        self.assertEqual(holder_pid, os.getpid())

    def test_release_removes_lock_file(self):
        self.lock.acquire()
        self.lock.release()
        acquired, _ = RunLockAdapter(FakeConfig(self.root)).acquire()
        self.assertTrue(acquired)

    def test_release_without_ownership_leaves_other_holder_lock(self):
        with open(os.path.join(self.root, ".lc-run.pid"), "w") as f:
            f.write(str(os.getpid() + 1))
        self.lock.release()
        self.assertTrue(os.path.exists(os.path.join(self.root, ".lc-run.pid")))

    def test_is_running_false_when_no_lock_file(self):
        self.assertFalse(self.lock.is_running())
        self.assertFalse(os.path.exists(os.path.join(self.root, ".lc-run.pid")))

    def test_is_running_true_when_pid_alive(self):
        path = os.path.join(self.root, ".lc-run.pid")
        with open(path, "w") as f:
            f.write(str(os.getpid()))
        self.assertTrue(self.lock.is_running())
        with open(path) as f:
            self.assertEqual(f.read().strip(), str(os.getpid()))

    def test_is_running_false_when_pid_dead(self):
        dead_pid = 999999
        path = os.path.join(self.root, ".lc-run.pid")
        with open(path, "w") as f:
            f.write(str(dead_pid))
        self.assertFalse(self.lock.is_running())
        with open(path) as f:
            self.assertEqual(f.read().strip(), str(dead_pid))

    def test_repeated_is_running_never_blocks_a_later_real_acquire(self):
        for _ in range(3):
            self.lock.is_running()
        resp = AcquireRunLockUseCase(RunLockAdapter(FakeConfig(self.root))).execute()
        self.assertTrue(resp.acquired)
        self.assertEqual(resp.holder_pid, os.getpid())


if __name__ == "__main__":
    unittest.main()
