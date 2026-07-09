import unittest

from lightcycle.application.pool.breaker_gate import BreakerGateUseCase
from tests.support.fake_fs import FakeFs

_REJECTED = (
    '{"type":"rate_limit_event","rate_limit_info":'
    '{"status":"rejected","resetsAt":%d}}'
)


class FakeWorkers:
    def __init__(self, workers=None, alive_pids=()):
        self._workers = workers or []
        self._alive = set(alive_pids)
        self.killed = []
        self.checked = []

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid, started=None):
        return pid in self._alive

    def reap(self):
        pass

    def kill(self, pid):
        self.killed.append(pid)

    def mark_checked(self, spawnid):
        self.checked.append(spawnid)
        for w in self._workers:
            if w.get("spawnid") == spawnid:
                w["checked"] = True


class FakeBreakerPort:
    def __init__(self, state=None):
        self._state = state or {}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class TestBreakerGateUseCase(unittest.TestCase):
    def test_no_signal_stays_closed(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "log": "/l/1.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/1.log": b'{"type":"result"}'})
        breaker_port = FakeBreakerPort()
        result = BreakerGateUseCase(workers, fs, breaker_port).execute(now=100)
        self.assertFalse(result.breaker.is_open)
        self.assertFalse(result.opened)
        self.assertEqual(workers.killed, [])
        self.assertEqual(workers.checked, ["sp-1"])

    def test_rejected_signal_opens_the_breaker_and_kills_live_workers(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "dead-sp", "pid": 1, "log": "/l/dead.log", "started": 0},
                {"spawnid": "live-sp", "pid": 2, "log": "/l/live.log", "started": 0},
            ],
            alive_pids={2},
        )
        fs = FakeFs(files={"/l/dead.log": (_REJECTED % 500).encode()})
        breaker_port = FakeBreakerPort()
        result = BreakerGateUseCase(workers, fs, breaker_port).execute(now=100)
        self.assertTrue(result.opened)
        self.assertTrue(result.breaker.is_open)
        self.assertEqual(result.breaker.reset_at, 500)
        self.assertEqual(workers.killed, [2])
        self.assertEqual(breaker_port.load(), {"open": True, "reset_at": 500})

    def test_probe_success_closes_the_breaker(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "probe-sp", "pid": 3, "log": "/l/probe.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/probe.log": b'{"type":"result","subtype":"success"}'})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(workers, fs, breaker_port).execute(now=500)
        self.assertTrue(result.closed)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(breaker_port.load(), {"open": False, "reset_at": None})

    def test_probe_failure_reopens_with_new_reset_at(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "probe-sp", "pid": 3, "log": "/l/probe.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/probe.log": (_REJECTED % 900).encode()})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(workers, fs, breaker_port).execute(now=500)
        self.assertTrue(result.opened)
        self.assertTrue(result.breaker.is_open)
        self.assertEqual(result.breaker.reset_at, 900)

    def test_already_checked_workers_are_not_rescanned(self):
        workers = FakeWorkers(
            workers=[
                {
                    "spawnid": "old-sp",
                    "pid": 9,
                    "log": "/l/old.log",
                    "started": 0,
                    "checked": True,
                }
            ]
        )
        fs = FakeFs(files={"/l/old.log": (_REJECTED % 500).encode()})
        breaker_port = FakeBreakerPort()
        result = BreakerGateUseCase(workers, fs, breaker_port).execute(now=100)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(workers.checked, [])

    def test_missing_log_is_not_a_signal(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "log": "/l/missing.log", "started": 0}]
        )
        fs = FakeFs(files={})
        breaker_port = FakeBreakerPort()
        result = BreakerGateUseCase(workers, fs, breaker_port).execute(now=100)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(workers.checked, ["sp-1"])


if __name__ == "__main__":
    unittest.main()
