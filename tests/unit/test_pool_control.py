import unittest

from lightcycle.application.pool import (
    LiveWorkerCountUseCase,
    StartPoolUseCase,
    StopPoolSignalUseCase,
)
from lightcycle.domain.pool.worker import Worker


class FakeLock:
    def __init__(self, pid=None):
        self.pid = pid

    def holder_pid(self):
        return self.pid


class FakeSpawner:
    def __init__(self, pid=777):
        self._pid = pid
        self.calls = 0

    def spawn_pool(self):
        self.calls += 1
        return self._pid


class FakeWorkers:
    def __init__(self, workers=()):
        self._workers = list(workers)
        self.killed = []

    def workers_state(self):
        return [Worker.from_state(d) for d in self._workers]

    def pid_alive(self, pid, started=None):
        return pid > 0

    def kill(self, pid):
        self.killed.append(pid)


class TestStartPoolUseCase(unittest.TestCase):
    def test_spawns_when_no_lock_is_held(self):
        spawner = FakeSpawner(pid=777)
        resp = StartPoolUseCase(FakeLock(pid=None), spawner).execute()
        self.assertTrue(resp.started)
        self.assertEqual(resp.pid, 777)
        self.assertEqual(spawner.calls, 1)

    def test_refuses_and_names_the_holder_when_already_running(self):
        spawner = FakeSpawner()
        resp = StartPoolUseCase(FakeLock(pid=42), spawner).execute()
        self.assertFalse(resp.started)
        self.assertEqual(resp.pid, 42)
        self.assertEqual(spawner.calls, 0)


class TestStopPoolSignalUseCase(unittest.TestCase):
    def test_signals_the_lock_holder(self):
        workers = FakeWorkers()
        resp = StopPoolSignalUseCase(FakeLock(pid=42), workers).execute()
        self.assertTrue(resp.signalled)
        self.assertEqual(resp.pid, 42)
        self.assertEqual(workers.killed, [42])

    def test_signals_nothing_when_no_pool_is_running(self):
        workers = FakeWorkers()
        resp = StopPoolSignalUseCase(FakeLock(pid=None), workers).execute()
        self.assertFalse(resp.signalled)
        self.assertIsNone(resp.pid)
        self.assertEqual(workers.killed, [])


class TestLiveWorkerCountUseCase(unittest.TestCase):
    def test_counts_only_workers_whose_pid_is_alive(self):
        workers = FakeWorkers(workers=[
            {"spawnid": "a", "pid": 1, "started": 0},
            {"spawnid": "b", "pid": -1, "started": 0},
            {"spawnid": "c", "pid": 2, "started": 0},
        ])
        self.assertEqual(LiveWorkerCountUseCase(workers).execute(), 2)

    def test_is_zero_with_no_workers(self):
        self.assertEqual(LiveWorkerCountUseCase(FakeWorkers()).execute(), 0)


if __name__ == "__main__":
    unittest.main()
