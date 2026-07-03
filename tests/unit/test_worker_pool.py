import unittest

from the_grid.domain.pool import Worker, WorkerPool


def probe(alive_pids):
    return lambda pid: pid in alive_pids


class TestWorker(unittest.TestCase):
    def test_from_state_reads_the_registry_dict(self):
        w = Worker.from_state(
            {"spawnid": "sp-1", "pid": 42, "role": "coder", "task": "b-1", "started": 100}
        )
        self.assertEqual(
            (w.spawnid, w.pid, w.role, w.task, w.started), ("sp-1", 42, "coder", "b-1", 100)
        )

    def test_is_alive_delegates_to_probe(self):
        w = Worker(pid=42)
        self.assertTrue(w.is_alive(probe({42})))
        self.assertFalse(w.is_alive(probe(set())))

    def test_is_booting_when_unclaimed_within_window(self):
        self.assertTrue(Worker(task=None, started=100).is_booting(now=150, max_boot=120))

    def test_not_booting_once_claimed(self):
        self.assertFalse(Worker(task="b-1", started=100).is_booting(now=150, max_boot=120))

    def test_not_booting_past_the_window(self):
        self.assertFalse(Worker(task=None, started=100).is_booting(now=300, max_boot=120))


class TestWorkerPool(unittest.TestCase):
    def _pool(self):
        return WorkerPool.from_state(
            [
                {"spawnid": "live", "pid": 1, "role": "coder", "task": None, "started": 100},
                {"spawnid": "dead", "pid": 2, "role": "coder", "task": None, "started": 100},
                {"spawnid": "busy", "pid": 3, "role": "reviewer", "task": "b-9", "started": 100},
            ]
        )

    def test_live_spawnids_only_counts_alive(self):
        self.assertEqual(self._pool().live_spawnids(probe({1, 3})), {"live", "busy"})

    def test_free_slots_subtracts_alive(self):
        self.assertEqual(self._pool().free_slots(4, probe({1, 3})), 2)

    def test_inflight_counts_alive_booting_by_role(self):
        self.assertEqual(self._pool().inflight(probe({1, 3}), now=150, max_boot=120), {"coder": 1})


if __name__ == "__main__":
    unittest.main()
