import copy
import json
import unittest

from lightcycle.application.pool.breaker_gate import BreakerGateUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

_REJECTED = (
    '{"type":"rate_limit_event","rate_limit_info":'
    '{"status":"rejected","resetsAt":%d}}'
)
_NO_WORK_LOG = (
    b"session started\n"
    b"Failed to authenticate: OAuth session expired and could not be refreshed\n"
    b"error: api_error"
)


class RecordingFakeFs(FakeFs):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.iter_lines_calls = []

    def iter_lines(self, path):
        self.iter_lines_calls.append(path)
        return super().iter_lines(path)


class FakeWorkers:
    def __init__(self, workers=None, alive_pids=(), log_mtimes=None):
        self._workers = workers or []
        self._alive = set(alive_pids)
        self._log_mtimes = log_mtimes or {}
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

    def log_mtime(self, path):
        return self._log_mtimes.get(path)


class FakeBreakerPort:
    def __init__(self, state=None):
        self._state = state or {}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class FakeConfig:
    def __init__(
        self, max_boot_seconds=120, stall_seconds=1800, probe_cooldown_seconds=1800, spin_cap=2
    ):
        self._max_boot_seconds = max_boot_seconds
        self._stall_seconds = stall_seconds
        self._probe_cooldown_seconds = probe_cooldown_seconds
        self._spin_cap = spin_cap

    def max_boot_seconds(self):
        return self._max_boot_seconds

    def stall_seconds(self):
        return self._stall_seconds

    def probe_cooldown_seconds(self):
        return self._probe_cooldown_seconds

    def spin_cap(self):
        return self._spin_cap


class FakeSpinPort:
    def __init__(self, state=None):
        self._state = state or {}

    def load(self):
        return copy.deepcopy(self._state)

    def save(self, state):
        self._state = copy.deepcopy(state)


class TestBreakerGateUseCase(unittest.TestCase):
    def test_no_signal_stays_closed(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "log": "/l/1.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/1.log": b'{"type":"result"}'})
        breaker_port = FakeBreakerPort()
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig()).execute(now=100)
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
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig()).execute(now=100)
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
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig()).execute(now=500)
        self.assertTrue(result.closed)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(breaker_port.load(), {"open": False, "reset_at": None})

    def test_probe_failure_reopens_with_new_reset_at(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "probe-sp", "pid": 3, "log": "/l/probe.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/probe.log": (_REJECTED % 900).encode()})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig()).execute(now=500)
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
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig()).execute(now=100)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(workers.checked, [])

    def test_missing_log_is_not_a_signal(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "log": "/l/missing.log", "started": 0}]
        )
        fs = FakeFs(files={})
        breaker_port = FakeBreakerPort()
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig()).execute(now=100)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(workers.checked, ["sp-1"])

    def test_a_stalled_probe_rearms_the_reset_time_by_the_probe_cooldown(self):
        workers = FakeWorkers(
            workers=[
                {
                    "spawnid": "probe-sp",
                    "pid": 3,
                    "step": "probe",
                    "log": "/l/probe.log",
                    "started": 0,
                }
            ],
            alive_pids={3},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        fs = FakeFs(files={})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig()
        ).execute(now=1000)
        self.assertTrue(result.rearmed)
        self.assertFalse(result.closed)
        self.assertFalse(result.opened)
        self.assertTrue(result.breaker.is_open)
        self.assertEqual(result.breaker.reset_at, 1000 + 1800)
        self.assertEqual(workers.killed, [])
        self.assertEqual(workers.checked, [])

    def test_a_probe_log_within_the_stall_threshold_is_left_alone(self):
        workers = FakeWorkers(
            workers=[
                {
                    "spawnid": "probe-sp",
                    "pid": 3,
                    "step": "probe",
                    "log": "/l/probe.log",
                    "started": 0,
                }
            ],
            alive_pids={3},
            log_mtimes={"/l/probe.log": 1000 - 1800 + 1},
        )
        fs = FakeFs(files={})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig()
        ).execute(now=1000)
        self.assertFalse(result.rearmed)
        self.assertEqual(result.breaker.reset_at, 500)

    def test_a_stalled_worker_with_a_terminal_marker_is_not_treated_as_a_stalled_probe(self):
        workers = FakeWorkers(
            workers=[
                {
                    "spawnid": "probe-sp",
                    "pid": 3,
                    "step": "probe",
                    "log": "/l/probe.log",
                    "started": 0,
                }
            ],
            alive_pids={3},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        log_line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "input": {"command": "lc done t done"}}]
                },
            }
        )
        fs = FakeFs(files={"/l/probe.log": log_line.encode()})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig()
        ).execute(now=1000)
        self.assertFalse(result.rearmed)

    def test_rearming_only_happens_while_actually_probing(self):
        workers = FakeWorkers(
            workers=[
                {
                    "spawnid": "probe-sp",
                    "pid": 3,
                    "step": "probe",
                    "log": "/l/probe.log",
                    "started": 0,
                }
            ],
            alive_pids={3},
            log_mtimes={"/l/probe.log": 0},
        )
        fs = FakeFs(files={})
        for state in ({"open": False, "reset_at": None}, {"open": True, "reset_at": 2000}):
            breaker_port = FakeBreakerPort(state)
            result = BreakerGateUseCase(
                workers, fs, breaker_port, FakeConfig()
            ).execute(now=1000)
            self.assertFalse(result.rearmed)

    def test_a_concurrent_rejection_takes_precedence_over_a_stalled_probe(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "dead-sp", "pid": 1, "log": "/l/dead.log", "started": 0},
                {
                    "spawnid": "probe-sp",
                    "pid": 3,
                    "step": "probe",
                    "log": "/l/probe.log",
                    "started": 0,
                },
            ],
            alive_pids={3},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        fs = FakeFs(files={"/l/dead.log": (_REJECTED % 5000).encode()})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig()
        ).execute(now=1000)
        self.assertTrue(result.opened)
        self.assertEqual(result.breaker.reset_at, 5000)
        self.assertFalse(result.rearmed)

    def test_when_not_probing_the_stalled_workers_log_is_never_read(self):
        workers = FakeWorkers(
            workers=[
                {
                    "spawnid": "probe-sp",
                    "pid": 3,
                    "step": "probe",
                    "log": "/l/probe.log",
                    "started": 0,
                }
            ],
            alive_pids={3},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        fs = RecordingFakeFs(files={})
        breaker_port = FakeBreakerPort({"open": False, "reset_at": None})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig()
        ).execute(now=1000)
        self.assertFalse(result.rearmed)
        self.assertNotIn("/l/probe.log", fs.iter_lines_calls)

    def test_a_concurrent_rejection_skips_reading_the_stalled_probe_log(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "dead-sp", "pid": 1, "log": "/l/dead.log", "started": 0},
                {
                    "spawnid": "probe-sp",
                    "pid": 3,
                    "step": "probe",
                    "log": "/l/probe.log",
                    "started": 0,
                },
            ],
            alive_pids={3},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        fs = RecordingFakeFs(files={"/l/dead.log": (_REJECTED % 5000).encode()})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig()
        ).execute(now=1000)
        self.assertTrue(result.opened)
        self.assertFalse(result.rearmed)
        self.assertIn("/l/dead.log", fs.iter_lines_calls)
        self.assertNotIn("/l/probe.log", fs.iter_lines_calls)

    def test_a_successful_probe_skips_reading_a_different_stalled_workers_log(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "probe-sp", "pid": 3, "log": "/l/probe.log", "started": 0},
                {
                    "spawnid": "other-sp",
                    "pid": 4,
                    "step": "probe",
                    "log": "/l/other.log",
                    "started": 0,
                },
            ],
            alive_pids={4},
            log_mtimes={"/l/other.log": 500 - 1800 - 1},
        )
        fs = RecordingFakeFs(files={"/l/probe.log": b'{"type":"result","subtype":"success"}'})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig()
        ).execute(now=500)
        self.assertTrue(result.closed)
        self.assertFalse(result.breaker.is_open)
        self.assertIn("/l/probe.log", fs.iter_lines_calls)
        self.assertNotIn("/l/other.log", fs.iter_lines_calls)

    def test_a_dead_worker_with_no_rejection_and_no_session_activity_does_not_close_a_probe(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "probe-sp", "pid": 3, "log": "/l/probe.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/probe.log": _NO_WORK_LOG})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig()).execute(now=500)
        self.assertFalse(result.closed)
        self.assertTrue(result.breaker.is_open)


class TestBreakerGatePoolWideSpin(unittest.TestCase):
    def _dead_worker(self, spawnid, pid, step, no_work=True):
        return {"spawnid": spawnid, "pid": pid, "step": step, "log": "/l/%s.log" % spawnid, "started": 0}

    def _no_work_fs(self, files):
        return FakeFs(files=files)

    def test_two_no_work_deaths_with_steps_trips_the_pool_wide_guard_and_parks_a_step(self):
        s = FakeStore()
        step1 = s.create_step("build: a", step="build", role="agent")
        step2 = s.create_step("build: b", step="build", role="agent")
        workers = FakeWorkers(
            workers=[
                self._dead_worker("w1", 1, step1),
                self._dead_worker("w2", 2, step2),
            ]
        )
        fs = FakeFs(files={"/l/w1.log": _NO_WORK_LOG, "/l/w2.log": _NO_WORK_LOG})
        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=1),
            spin_port=FakeSpinPort(), store=s,
        ).execute(now=100)
        self.assertTrue(result.spin_open)
        self.assertTrue(result.spin_opened)
        parked = [n for n in (step1, step2) if s.get_node(n).role == "human"]
        self.assertEqual(len(parked), 1)

    def test_a_single_dead_worker_with_no_work_does_not_trip_the_guard(self):
        s = FakeStore()
        step1 = s.create_step("build: a", step="build", role="agent")
        workers = FakeWorkers(workers=[self._dead_worker("w1", 1, step1)])
        fs = FakeFs(files={"/l/w1.log": _NO_WORK_LOG})
        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=2),
            spin_port=FakeSpinPort(), store=s,
        ).execute(now=100)
        self.assertFalse(result.spin_open)
        self.assertFalse(result.spin_opened)

    def test_a_rejection_takes_precedence_over_the_pool_wide_no_work_tally(self):
        s = FakeStore()
        step1 = s.create_step("build: a", step="build", role="agent")
        step2 = s.create_step("build: b", step="build", role="agent")
        workers = FakeWorkers(
            workers=[
                self._dead_worker("w1", 1, step1),
                self._dead_worker("w2", 2, step2),
            ]
        )
        fs = FakeFs(
            files={"/l/w1.log": _NO_WORK_LOG, "/l/w2.log": (_REJECTED % 5000).encode()}
        )
        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=2),
            spin_port=FakeSpinPort(), store=s,
        ).execute(now=100)
        self.assertFalse(result.spin_open)

    def test_a_dead_worker_with_no_assigned_step_never_counts(self):
        s = FakeStore()
        workers = FakeWorkers(workers=[self._dead_worker("w1", 1, None)])
        fs = FakeFs(files={"/l/w1.log": _NO_WORK_LOG})
        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=1),
            spin_port=FakeSpinPort(), store=s,
        ).execute(now=100)
        self.assertFalse(result.spin_open)

    def test_real_activity_resets_an_advancing_streak(self):
        s = FakeStore()
        step1 = s.create_step("build: a", step="build", role="agent")
        step2 = s.create_step("build: b", step="build", role="agent")
        workers = FakeWorkers(
            workers=[
                self._dead_worker("w1", 1, step1),
                self._dead_worker("w2", 2, step2),
            ]
        )
        fs = FakeFs(
            files={
                "/l/w1.log": _NO_WORK_LOG,
                "/l/w2.log": b'{"type":"result","subtype":"success"}',
            }
        )
        spin_port = FakeSpinPort({"pool": {"streak": 1, "tripped": False}})
        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=3),
            spin_port=spin_port, store=s,
        ).execute(now=100)
        self.assertFalse(result.spin_open)
        self.assertEqual(spin_port.load()["pool"]["streak"], 0)

    def test_streak_accumulates_one_check_at_a_time_until_the_cap(self):
        s = FakeStore()
        spin_port = FakeSpinPort()
        config = FakeConfig(spin_cap=3)
        for i in range(3):
            step1 = s.create_step("build: a%d" % i, step="build", role="agent")
            step2 = s.create_step("build: b%d" % i, step="build", role="agent")
            workers = FakeWorkers(
                workers=[
                    self._dead_worker("w1-%d" % i, 100 + i * 2, step1),
                    self._dead_worker("w2-%d" % i, 101 + i * 2, step2),
                ]
            )
            fs = FakeFs(
                files={
                    "/l/w1-%d.log" % i: _NO_WORK_LOG,
                    "/l/w2-%d.log" % i: _NO_WORK_LOG,
                }
            )
            result = BreakerGateUseCase(
                workers, fs, FakeBreakerPort(), config, spin_port=spin_port, store=s,
            ).execute(now=100 + i)
            if i < 2:
                self.assertFalse(result.spin_open, "tripped too early on check %d" % i)
            else:
                self.assertTrue(result.spin_open)


if __name__ == "__main__":
    unittest.main()
