import tempfile
import unittest
from pathlib import Path

from lightcycle.adapters import workers as wk
from lightcycle.domain.pool import Worker, WorkerPool


class TestStepFor(unittest.TestCase):
    def _root(self):
        root = tempfile.mkdtemp()
        (Path(root) / "logs").mkdir()
        return root

    def test_returns_the_assigned_step(self):
        root = self._root()
        wk.register_worker(root, {"spawnid": "sp1", "step": None})
        wk.set_step(root, "sp1", "b-1")
        self.assertEqual(wk.step_for(root, "sp1"), "b-1")

    def test_none_when_unassigned(self):
        root = self._root()
        wk.register_worker(root, {"spawnid": "sp1", "step": None})
        self.assertIsNone(wk.step_for(root, "sp1"))

    def test_none_for_unknown_spawnid(self):
        self.assertIsNone(wk.step_for(self._root(), "nope"))


def probe(alive_pids):
    return lambda pid, started=None: pid in alive_pids


class TestWorker(unittest.TestCase):
    def test_from_state_reads_the_registry_dict(self):
        w = Worker.from_state(
            {"spawnid": "sp-1", "pid": 42, "role": "coder", "step": "b-1", "started": 100}
        )
        self.assertEqual(
            (w.spawnid, w.pid, w.role, w.step, w.started), ("sp-1", 42, "coder", "b-1", 100)
        )

    def test_from_state_reads_log_and_checked(self):
        w = Worker.from_state({"spawnid": "sp-1", "log": "/l/1.log", "checked": True})
        self.assertEqual(w.log, "/l/1.log")
        self.assertTrue(w.checked)

    def test_checked_defaults_to_false(self):
        self.assertFalse(Worker.from_state({"spawnid": "sp-1"}).checked)

    def test_is_alive_delegates_to_probe(self):
        w = Worker(pid=42)
        self.assertTrue(w.is_alive(probe({42})))
        self.assertFalse(w.is_alive(probe(set())))

    def test_is_booting_when_unclaimed_within_window(self):
        self.assertTrue(Worker(step=None, started=100).is_booting(now=150, max_boot=120))

    def test_not_booting_once_claimed(self):
        self.assertFalse(Worker(step="b-1", started=100).is_booting(now=150, max_boot=120))

    def test_not_booting_past_the_window(self):
        self.assertFalse(Worker(step=None, started=100).is_booting(now=300, max_boot=120))


class TestWorkerPool(unittest.TestCase):
    def _pool(self):
        return WorkerPool.from_state(
            [
                {"spawnid": "live", "pid": 1, "role": "coder", "step": None, "started": 100},
                {"spawnid": "dead", "pid": 2, "role": "coder", "step": None, "started": 100},
                {"spawnid": "busy", "pid": 3, "role": "reviewer", "step": "b-9", "started": 100},
            ]
        )

    def test_live_spawnids_only_counts_alive(self):
        self.assertEqual(self._pool().live_spawnids(probe({1, 3})), {"live", "busy"})

    def test_free_slots_subtracts_alive(self):
        self.assertEqual(self._pool().free_slots(4, probe({1, 3})), 2)

    def test_inflight_counts_alive_booting_by_role(self):
        self.assertEqual(self._pool().inflight(probe({1, 3}), now=150, max_boot=120), {"coder": 1})

    def test_dead_unchecked_only_includes_dead_unchecked_workers(self):
        pool = WorkerPool.from_state(
            [
                {"spawnid": "dead", "pid": 1, "checked": False},
                {"spawnid": "live", "pid": 2, "checked": False},
                {"spawnid": "dead-checked", "pid": 3, "checked": True},
            ]
        )
        self.assertEqual(
            [w.spawnid for w in pool.dead_unchecked(probe({2}))], ["dead"]
        )


if __name__ == "__main__":
    unittest.main()
