import json
import unittest

from lightcycle.adapters.claude_stream import ClaudeStreamAdapter
from lightcycle.application.pool.breaker_gate import BreakerGateUseCase
from lightcycle.domain.pool import ModelRates, UsageResume
from lightcycle.domain.pool.worker import Worker
from lightcycle.ports.breaker import BreakerPort
from lightcycle.ports.workers import RegistryUnreadable
from tests.support.fake_fs import FakeFs
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step

_REJECTED = (
    '{"type":"rate_limit_event","rate_limit_info":'
    '{"status":"rejected","resetsAt":%d}}'
)
_NO_WORK_LOG = (
    b"session started\n"
    b"Failed to authenticate: OAuth session expired and could not be refreshed\n"
    b"error: api_error"
)


class RecordingFakeStore(FakeStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.record_usage_calls = []
        self.record_attribution_calls = []
        self.get_node_calls = []

    def record_usage(self, tid, input_tokens, output_tokens, cache_read_tokens,
                      cache_creation_tokens, cost_usd, cost_basis, thinking_tokens):
        self.record_usage_calls.append(
            (tid, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
             cost_usd, cost_basis, thinking_tokens)
        )

    def record_attribution(self, tid, turn_count, tool_usage):
        self.record_attribution_calls.append((tid, turn_count, tool_usage))

    def get_node(self, tid):
        self.get_node_calls.append(tid)
        return super().get_node(tid)


class RecordingFakeFs(FakeFs):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.iter_lines_calls = []

    def iter_lines(self, path):
        self.iter_lines_calls.append(path)
        return super().iter_lines(path)


class FakeWorkers:
    def __init__(self, workers=None, alive_pids=(), raise_workers_state=False):
        self._workers = workers or []
        self._alive = set(alive_pids)
        self.killed = []
        self.checked = []
        self._raise_workers_state = raise_workers_state

    def workers_state(self):
        if self._raise_workers_state:
            raise RegistryUnreadable("boom")
        return [Worker.from_state(d) for d in self._workers]

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


class FakeBreakerPort(BreakerPort):
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

    def usage_pricing(self):
        return {"sonnet": ModelRates(input=2.0, output=10.0, cache_write=2.5, cache_read=0.2)}


class TestBreakerGateUseCase(unittest.TestCase):
    def test_no_signal_stays_closed(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "log": "/l/1.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/1.log": b'{"type":"result"}'})
        breaker_port = FakeBreakerPort()
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertFalse(result.breaker.is_open)
        self.assertFalse(result.opened)
        self.assertEqual(workers.killed, [])
        self.assertEqual(workers.checked, ["sp-1"])

    def test_registry_unreadable_no_ops_without_raising(self):
        workers = FakeWorkers(raise_workers_state=True)
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(workers, FakeFs(files={}), breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(
            now=100
        )
        self.assertEqual(result.breaker.reset_at, 500)
        self.assertFalse(result.opened)
        self.assertFalse(result.closed)
        self.assertFalse(result.rearmed)
        self.assertEqual(result.killed, [])
        self.assertEqual(workers.killed, [])
        self.assertEqual(workers.checked, [])
        self.assertEqual(breaker_port.load(), {"open": True, "reset_at": 500})

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
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertTrue(result.opened)
        self.assertTrue(result.breaker.is_open)
        self.assertEqual(result.breaker.reset_at, 500)
        self.assertEqual(workers.killed, [2])
        self.assertEqual(breaker_port.load(), {"open": True, "reset_at": 500, "trips": 1})

    def test_probe_success_closes_the_breaker(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "probe-sp", "pid": 3, "log": "/l/probe.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/probe.log": b'{"type":"result","subtype":"success"}'})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=500)
        self.assertTrue(result.closed)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(breaker_port.load(), {"open": False, "reset_at": None, "trips": 0})

    def test_probe_failure_reopens_with_new_reset_at(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "probe-sp", "pid": 3, "log": "/l/probe.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/probe.log": (_REJECTED % 900).encode()})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=500)
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
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(workers.checked, [])

    def test_missing_log_is_not_a_signal(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "log": "/l/missing.log", "started": 0}]
        )
        fs = FakeFs(files={})
        breaker_port = FakeBreakerPort()
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=100)
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
        )
        fs = FakeFs(files={}, log_mtimes={"/l/probe.log": 1000 - 1800 - 1})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=1000)
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
        )
        fs = FakeFs(files={}, log_mtimes={"/l/probe.log": 1000 - 1800 + 1})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=1000)
        self.assertFalse(result.rearmed)
        self.assertEqual(result.breaker.reset_at, 500)

    def test_a_probes_terminal_command_is_itself_activity_that_closes_the_breaker(self):
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
        )
        log_line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "input": {"command": "lc done t done"}}]
                },
            }
        )
        fs = FakeFs(
            files={"/l/probe.log": log_line.encode()},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=1000)
        self.assertTrue(result.closed)
        self.assertFalse(result.rearmed)

    def test_a_live_probes_session_activity_closes_the_breaker(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "probe-sp", "pid": 3, "log": "/l/probe.log", "started": 0}],
            alive_pids={3},
        )
        fs = FakeFs(files={"/l/probe.log": b'{"type":"result","subtype":"success"}'})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=500)
        self.assertTrue(result.closed)
        self.assertFalse(result.breaker.is_open)
        self.assertEqual(workers.killed, [])
        self.assertEqual(workers.checked, [])

    def test_a_live_probes_pending_rejection_does_not_close_or_rearm(self):
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
        )
        log = "\n".join([_REJECTED % 900, '{"type":"result","subtype":"error"}'])
        fs = FakeFs(files={"/l/probe.log": log.encode()})
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=500)
        self.assertFalse(result.closed)
        self.assertFalse(result.opened)
        self.assertFalse(result.rearmed)
        self.assertEqual(result.breaker.reset_at, 500)

    def test_success_wins_over_a_stale_mtime_when_a_probe_both_worked_and_later_stalled(self):
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
        )
        fs = FakeFs(
            files={"/l/probe.log": b'{"type":"result","subtype":"success"}'},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=1000)
        self.assertTrue(result.closed)
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
        )
        fs = FakeFs(files={}, log_mtimes={"/l/probe.log": 0})
        for state in ({"open": False, "reset_at": None}, {"open": True, "reset_at": 2000}):
            breaker_port = FakeBreakerPort(state)
            result = BreakerGateUseCase(
                workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=1000)
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
        )
        fs = FakeFs(
            files={"/l/dead.log": (_REJECTED % 5000).encode()},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=1000)
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
        )
        fs = RecordingFakeFs(files={}, log_mtimes={"/l/probe.log": 1000 - 1800 - 1})
        breaker_port = FakeBreakerPort({"open": False, "reset_at": None})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=1000)
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
        )
        fs = RecordingFakeFs(
            files={"/l/dead.log": (_REJECTED % 5000).encode()},
            log_mtimes={"/l/probe.log": 1000 - 1800 - 1},
        )
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=1000)
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
        )
        fs = RecordingFakeFs(
            files={"/l/probe.log": b'{"type":"result","subtype":"success"}'},
            log_mtimes={"/l/other.log": 500 - 1800 - 1},
        )
        breaker_port = FakeBreakerPort({"open": True, "reset_at": 500})
        result = BreakerGateUseCase(
            workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=500)
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
        result = BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=500)
        self.assertFalse(result.closed)
        self.assertTrue(result.breaker.is_open)

    def test_a_dead_worker_with_a_step_and_usage_records_it_on_the_store(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        line = json.dumps({
            "type": "result",
            "modelUsage": {
                "claude-sonnet-5": {
                    "inputTokens": 68, "outputTokens": 16478,
                    "cacheReadInputTokens": 2190437, "cacheCreationInputTokens": 72581,
                    "thinkingTokens": 9899, "costUSD": 0.8933274, "costBasis": "list",
                }
            },
        })
        fs = FakeFs(files={"/l/1.log": line.encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(
            store.record_usage_calls,
            [(tid, 68, 16478, 2190437, 72581, 0.893327, "list", 9899)],
        )

    def test_a_dead_worker_with_no_step_causes_no_record_usage_call(self):
        store = RecordingFakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "log": "/l/1.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/1.log": b'{"type":"result","modelUsage":{}}'})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(store.record_usage_calls, [])

    def test_a_dead_worker_with_a_step_and_a_log_causes_attribution_to_be_recorded(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {"id": "msg-1", "content": [
                    {"type": "tool_use", "id": "tu-1", "name": "Read"},
                ]},
            }),
            json.dumps({
                "type": "user",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tu-1", "content": "hello"},
                ]},
            }),
        ]
        fs = FakeFs(files={"/l/1.log": "\n".join(lines).encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(len(store.record_attribution_calls), 1)
        recorded_tid, turn_count, tool_usage = store.record_attribution_calls[0]
        self.assertEqual(recorded_tid, tid)
        self.assertEqual(turn_count, 1)
        self.assertEqual(tool_usage["Read"].calls, 1)
        self.assertEqual(tool_usage["Read"].bytes, len(b"hello"))

    def test_a_dead_worker_with_no_step_causes_no_record_attribution_call(self):
        store = RecordingFakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "log": "/l/1.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/1.log": b'{"type":"result","modelUsage":{}}'})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(store.record_attribution_calls, [])

    def test_a_result_line_log_skips_the_model_lookup_entirely(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        line = json.dumps({
            "type": "result",
            "modelUsage": {"claude-sonnet-5": {"inputTokens": 68, "costUSD": 0.5, "costBasis": "list"}},
        })
        fs = FakeFs(files={"/l/1.log": line.encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(store.get_node_calls, [])
        self.assertEqual(len(store.record_usage_calls), 1)

    def test_no_result_line_with_recoverable_usage_looks_up_the_model_and_derives_cost(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        store.set_model(tid, "sonnet")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        line = json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-1", "content": [],
                "usage": {
                    "input_tokens": 1_000_000, "output_tokens": 0,
                    "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                },
            },
        })
        fs = FakeFs(files={"/l/1.log": line.encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(store.get_node_calls, [tid])
        self.assertEqual(len(store.record_usage_calls), 1)
        recorded = store.record_usage_calls[0]
        self.assertEqual(recorded[0], tid)
        self.assertEqual(recorded[1], 1_000_000)
        self.assertAlmostEqual(recorded[5], 2.0)
        self.assertEqual(recorded[6], "derived")

    def test_a_vanished_step_looks_up_the_model_but_records_no_usage_or_attribution(self):
        store = RecordingFakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": "gone", "log": "/l/1.log", "started": 0}]
        )
        line = json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-1", "content": [],
                "usage": {"input_tokens": 5, "output_tokens": 0,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            },
        })
        fs = FakeFs(files={"/l/1.log": line.encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(store.get_node_calls, ["gone"])
        self.assertEqual(store.record_usage_calls, [])
        self.assertEqual(store.record_attribution_calls, [])

    def test_a_vanished_step_creates_no_orphan_step_tool_usage_row(self):
        store = FakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": "gone", "log": "/l/1.log", "started": 0}]
        )
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {"id": "msg-1", "content": [
                    {"type": "tool_use", "id": "tu-1", "name": "Read"},
                ]},
            }),
            json.dumps({
                "type": "user",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tu-1", "content": "hello"},
                ]},
            }),
        ]
        fs = FakeFs(files={"/l/1.log": "\n".join(lines).encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(store.tool_usage_for("gone"), {})

    def test_a_dead_worker_with_a_step_and_usage_results_in_one_ledger_entry(self):
        store = FakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        line = json.dumps({
            "type": "result",
            "modelUsage": {"claude-sonnet-5": {"inputTokens": 68, "costUSD": 0.5, "costBasis": "list"}},
        })
        fs = FakeFs(files={"/l/1.log": line.encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(store.usage_backfilled_logs(), {"/l/1.log"})

    def test_no_result_line_and_nothing_recoverable_skips_the_model_lookup(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/1.log": b'{"type":"assistant","message":{"id":"msg-1","content":[]}}'})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(store.get_node_calls, [])
        self.assertEqual(
            store.record_usage_calls, [(tid, 0, 0, 0, 0, 0.0, None, None)],
        )

    def test_reaping_a_dead_worker_without_a_store_does_not_raise(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": "s-1", "log": "/l/1.log", "started": 0}]
        )
        fs = FakeFs(files={"/l/1.log": b'{"type":"result","modelUsage":{}}'})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(workers.checked, ["sp-1"])


class TestBreakerGatePoolWideSpin(unittest.TestCase):
    def _dead_worker(self, spawnid, pid, step, no_work=True):
        return {"spawnid": spawnid, "pid": pid, "step": step, "log": "/l/%s.log" % spawnid, "started": 0}

    def _no_work_fs(self, files):
        return FakeFs(files=files)

    def test_two_no_work_deaths_with_steps_trips_the_pool_wide_guard_and_parks_a_step(self):
        s = FakeStore()
        step1 = create_owned_step(s, "build: a", step="build", role="agent")
        step2 = create_owned_step(s, "build: b", step="build", role="agent")
        workers = FakeWorkers(
            workers=[
                self._dead_worker("w1", 1, step1),
                self._dead_worker("w2", 2, step2),
            ]
        )
        fs = FakeFs(files={"/l/w1.log": _NO_WORK_LOG, "/l/w2.log": _NO_WORK_LOG})
        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=1),
            spin_port=FakeSpinPort(), store=s, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertTrue(result.spin_open)
        self.assertTrue(result.spin_opened)
        parked = [n for n in (step1, step2) if s.get_node(n).role == "human"]
        self.assertEqual(len(parked), 1)

    def test_a_single_dead_worker_with_no_work_does_not_trip_the_guard(self):
        s = FakeStore()
        step1 = create_owned_step(s, "build: a", step="build", role="agent")
        workers = FakeWorkers(workers=[self._dead_worker("w1", 1, step1)])
        fs = FakeFs(files={"/l/w1.log": _NO_WORK_LOG})
        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=2),
            spin_port=FakeSpinPort(), store=s, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertFalse(result.spin_open)
        self.assertFalse(result.spin_opened)

    def test_a_rejection_takes_precedence_over_the_pool_wide_no_work_tally(self):
        s = FakeStore()
        step1 = create_owned_step(s, "build: a", step="build", role="agent")
        step2 = create_owned_step(s, "build: b", step="build", role="agent")
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
            spin_port=FakeSpinPort(), store=s, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertFalse(result.spin_open)

    def test_a_dead_worker_with_no_assigned_step_never_counts(self):
        s = FakeStore()
        workers = FakeWorkers(workers=[self._dead_worker("w1", 1, None)])
        fs = FakeFs(files={"/l/w1.log": _NO_WORK_LOG})
        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=1),
            spin_port=FakeSpinPort(), store=s, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertFalse(result.spin_open)

    def test_real_activity_resets_an_advancing_streak(self):
        s = FakeStore()
        step1 = create_owned_step(s, "build: a", step="build", role="agent")
        step2 = create_owned_step(s, "build: b", step="build", role="agent")
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
            spin_port=spin_port, store=s, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertFalse(result.spin_open)
        self.assertEqual(spin_port.load().pool_streak, 0)

    def test_streak_accumulates_one_check_at_a_time_until_the_cap(self):
        s = FakeStore()
        spin_port = FakeSpinPort()
        config = FakeConfig(spin_cap=3)
        for i in range(3):
            step1 = create_owned_step(s, "build: a%d" % i, step="build", role="agent")
            step2 = create_owned_step(s, "build: b%d" % i, step="build", role="agent")
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
                workers, fs, FakeBreakerPort(), config, spin_port=spin_port, store=s, stream=ClaudeStreamAdapter()).execute(now=100 + i)
            if i < 2:
                self.assertFalse(result.spin_open, "tripped too early on check %d" % i)
            else:
                self.assertTrue(result.spin_open)

    def test_a_dead_worker_with_resume_state_gets_a_corrected_delta_recorded(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {"id": "msg-1", "content": [
                    {"type": "tool_use", "id": "tu-1", "name": "Read"},
                ]},
            }),
            json.dumps({
                "type": "user",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tu-1", "content": "hello"},
                ]},
            }),
            json.dumps({
                "type": "assistant",
                "message": {"id": "msg-2", "content": [
                    {"type": "tool_use", "id": "tu-2", "name": "Read"},
                ]},
            }),
            json.dumps({
                "type": "user",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tu-2", "content": "worldworld"},
                ]},
            }),
            json.dumps({
                "type": "result",
                "modelUsage": {
                    "claude-sonnet-5": {
                        "inputTokens": 100, "outputTokens": 50,
                        "cacheReadInputTokens": 10, "cacheCreationInputTokens": 5,
                        "costUSD": 1.0, "costBasis": "list",
                    }
                },
            }),
        ]
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        store.record_live_usage(
            spawnid="sp-1",
            resume=UsageResume(
                log_file="/l/1.log", offset=0, message_ids=["msg-1"],
                pending_tool_use={}, posted_turn_count=1,
                posted_tool_usage={"Read": {"calls": 1, "bytes": len(b"hello")}},
                posted_input_tokens=40, posted_output_tokens=20, posted_cache_read_tokens=4,
                posted_cache_creation_tokens=2, posted_cost_usd=0.4,
            ),
            tid=tid, input_tokens=0, output_tokens=0, cache_read_tokens=0,
            cache_creation_tokens=0, cost_usd=0.0, cost_basis=None, thinking_tokens=None,
            turn_count=0, tool_usage={},
        )
        fs = FakeFs(files={"/l/1.log": "\n".join(lines).encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)

        self.assertEqual(
            store.record_usage_calls, [(tid, 60, 30, 6, 3, 0.6, "list", None)],
        )
        self.assertEqual(len(store.record_attribution_calls), 1)
        recorded_tid, turn_count, tool_usage = store.record_attribution_calls[0]
        self.assertEqual(recorded_tid, tid)
        self.assertEqual(turn_count, 1)
        self.assertEqual(tool_usage["Read"].calls, 1)
        self.assertEqual(tool_usage["Read"].bytes, 10)
        self.assertIsNone(store.usage_accrual_state("sp-1"))

    def test_a_negative_token_or_cost_correction_is_written_as_computed_not_clamped(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        line = json.dumps({
            "type": "result",
            "modelUsage": {
                "claude-sonnet-5": {
                    "inputTokens": 100, "outputTokens": 0, "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0, "costUSD": 0.5, "costBasis": "list",
                }
            },
        })
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        store.record_live_usage(
            spawnid="sp-1",
            resume=UsageResume(
                log_file="/l/1.log", offset=0, message_ids=[],
                pending_tool_use={}, posted_turn_count=0, posted_tool_usage={},
                posted_input_tokens=150, posted_output_tokens=0, posted_cache_read_tokens=0,
                posted_cache_creation_tokens=0, posted_cost_usd=0.9,
            ),
            tid=tid, input_tokens=0, output_tokens=0, cache_read_tokens=0,
            cache_creation_tokens=0, cost_usd=0.0, cost_basis=None, thinking_tokens=None,
            turn_count=0, tool_usage={},
        )
        fs = FakeFs(files={"/l/1.log": line.encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        recorded = store.record_usage_calls[0]
        self.assertEqual(recorded[1], -50)
        self.assertAlmostEqual(recorded[5], -0.4)
        self.assertIsNone(store.usage_accrual_state("sp-1"))

    def test_a_dead_worker_with_no_resume_state_behaves_exactly_as_today(self):
        store = RecordingFakeStore()
        tid = create_owned_step(store, "build: t", step="build", role="agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "pid": 1, "step": tid, "log": "/l/1.log", "started": 0}]
        )
        line = json.dumps({
            "type": "result",
            "modelUsage": {
                "claude-sonnet-5": {"inputTokens": 68, "outputTokens": 10, "costUSD": 0.1,
                                    "costBasis": "list"}
            },
        })
        fs = FakeFs(files={"/l/1.log": line.encode()})
        breaker_port = FakeBreakerPort()
        BreakerGateUseCase(workers, fs, breaker_port, FakeConfig(), store=store, stream=ClaudeStreamAdapter()).execute(now=100)
        self.assertEqual(
            store.record_usage_calls, [(tid, 68, 10, 0, 0, 0.1, "list", None)],
        )
        self.assertIsNone(store.usage_accrual_state("sp-1"))


if __name__ == "__main__":
    unittest.main()
