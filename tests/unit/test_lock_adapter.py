import os
import tempfile
import unittest

from the_grid.adapters.lock import RunLockAdapter


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def grid_root(self):
        return self._root

    def data_root(self):
        return self._root

    def library_root(self):
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
        with open(os.path.join(self.root, ".tg-run.pid"), "w") as f:
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
        with open(os.path.join(self.root, ".tg-run.pid"), "w") as f:
            f.write(str(os.getpid() + 1))
        self.lock.release()
        self.assertTrue(os.path.exists(os.path.join(self.root, ".tg-run.pid")))


if __name__ == "__main__":
    unittest.main()
