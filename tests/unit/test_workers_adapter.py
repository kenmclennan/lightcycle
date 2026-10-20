import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr

from lightcycle.adapters.workers import (
    mark_checked, prune_pool_gh_call_logs, prune_workers, register_worker, set_pid_started, set_step,
    workers_path, workers_state,
)
from lightcycle.ports.workers import RegistryUnreadable


def _write_corrupt(root):
    path = workers_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{not valid json")
    return path


class TestWorkersState(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_returns_empty_list_with_no_warning_when_file_absent(self):
        err = io.StringIO()
        with redirect_stderr(err):
            state = workers_state(self.root)
        self.assertEqual(state, [])
        self.assertEqual(err.getvalue(), "")

    def test_returns_parsed_list_on_valid_file(self):
        path = workers_path(self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write('[{"spawnid": "a"}]')
        self.assertEqual(workers_state(self.root), [{"spawnid": "a"}])

    def test_raises_and_warns_on_corrupt_file(self):
        path = _write_corrupt(self.root)
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(RegistryUnreadable):
                workers_state(self.root)
        self.assertIn(path, err.getvalue())
        self.assertIn("warning", err.getvalue())


class TestMutatorsFailClosed(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = _write_corrupt(self.root)
        with open(self.path, "rb") as f:
            self.before = f.read()

    def _assert_unchanged(self):
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), self.before)

    def test_register_worker_raises_and_leaves_file_unchanged(self):
        with self.assertRaises(RegistryUnreadable):
            register_worker(self.root, {"spawnid": "x"})
        self._assert_unchanged()

    def test_prune_workers_raises_and_leaves_file_unchanged(self):
        with self.assertRaises(RegistryUnreadable):
            prune_workers(self.root, 0)
        self._assert_unchanged()

    def test_set_step_raises_and_leaves_file_unchanged(self):
        with self.assertRaises(RegistryUnreadable):
            set_step(self.root, "x", "t1")
        self._assert_unchanged()

    def test_mark_checked_raises_and_leaves_file_unchanged(self):
        with self.assertRaises(RegistryUnreadable):
            mark_checked(self.root, "x")
        self._assert_unchanged()

    def test_set_pid_started_raises_and_leaves_file_unchanged(self):
        with self.assertRaises(RegistryUnreadable):
            set_pid_started(self.root, "x", 12345)
        self._assert_unchanged()

if __name__ == "__main__":
    unittest.main()


class TestGhCallLogPruning(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.logs = os.path.join(self.root, "logs")
        os.makedirs(self.logs)

    def _touch(self, name):
        path = os.path.join(self.logs, name)
        with open(path, "w") as f:
            f.write("x\n")
        return path

    def test_a_pruned_dead_workers_call_log_goes_and_a_live_workers_stays(self):
        dead_pid = os.getpid() + 10 ** 7
        register_worker(self.root, {"spawnid": "dead", "pid": dead_pid, "step": None})
        register_worker(self.root, {"spawnid": "live", "pid": os.getpid(), "step": None})
        dead_log = self._touch("gh-calls-dead.log")
        live_log = self._touch("gh-calls-live.log")
        self.assertEqual(prune_workers(self.root, 0), 1)
        self.assertFalse(os.path.exists(dead_log))
        self.assertTrue(os.path.exists(live_log))

    def test_a_dead_worker_kept_by_history_keeps_its_call_log(self):
        register_worker(self.root, {"spawnid": "dead", "pid": os.getpid() + 10 ** 7, "step": None})
        dead_log = self._touch("gh-calls-dead.log")
        prune_workers(self.root, 1)
        self.assertTrue(os.path.exists(dead_log))

    def test_pool_call_logs_keep_only_the_newest_files(self):
        for day in ("20260101", "20260102", "20260103"):
            self._touch("gh-calls-pool-%s.log" % day)
        other = self._touch("gh-calls-abc.log")
        prune_pool_gh_call_logs(self.root, 2)
        self.assertEqual(
            sorted(os.listdir(self.logs)),
            ["gh-calls-abc.log", "gh-calls-pool-20260102.log", "gh-calls-pool-20260103.log"],
        )
        self.assertTrue(os.path.exists(other))
