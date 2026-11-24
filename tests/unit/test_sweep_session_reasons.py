import json
import unittest

from lightcycle.adapters.claude_stream import ClaudeStreamAdapter
from lightcycle.application.pool.no_op_gates import NoOpSpinPort
from lightcycle.application.pool.sweep import SweepUseCase
from lightcycle.domain.work import State
from tests.feature.test_stalled_worker_reclaim import FakeFs, FakeWorkers, FakeWorktrees
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore

NOW = 1_000_000.0
MAX_BOOT = 120
STALL = 1800
LOG = "/logs/sp-1.log"
NON_TERMINAL = json.dumps(
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "input": {"command": "echo"}}]}}
).encode()


def _rig(entry_extra=None, alive=True, stale=False):
    store = FakeStore()
    item = store.create_item("feature", "d")
    step = store.create_step(stage="build", role="agent", item=item)
    store.update_state(step, State.RUNNING)
    store.assign(step, "sp-1")
    store.set_log(step, "/logs/older.log")
    store.set_log(step, LOG)
    workers = FakeWorkers()
    fs = FakeFs()
    if entry_extra is not None:
        entry = {"spawnid": "sp-1", "pid": 4242, "step": step, "started": NOW - MAX_BOOT - 1, "log": LOG}
        entry.update(entry_extra)
        workers.register(entry, alive=alive)
        fs.files[LOG] = NON_TERMINAL
        fs.set_log_mtime(LOG, NOW - STALL - 1 if stale else NOW)
    return store, step, workers, fs


def _sweep(store, workers, fs):
    return SweepUseCase(
        store, workers, worktrees=FakeWorktrees(), git=FakeGit(events=[]), worker_log=fs,
        spin_port=NoOpSpinPort(), spin_cap=99, stream=ClaudeStreamAdapter(),
    ).execute(NOW, MAX_BOOT, STALL)


class TestSweepRecordsWhySessionEnded(unittest.TestCase):
    def _assert_reason(self, store, step, result, reason):
        sessions = store.step_sessions(step)
        self.assertEqual(len(sessions), 2)
        self.assertEqual([s.ended_reason for s in sessions], [None, reason])
        self.assertEqual(result.swept, [step])
        self.assertEqual(result.ended[step].reason, reason)
        self.assertEqual(result.ended[step].session, 2)

    def test_a_killed_stalled_step_records_stalled(self):
        store, step, workers, fs = _rig(entry_extra={}, stale=True)
        self._assert_reason(store, step, _sweep(store, workers, fs), "stalled")

    def test_a_dead_worker_record_records_died(self):
        store, step, workers, fs = _rig(entry_extra={}, alive=False)
        self._assert_reason(store, step, _sweep(store, workers, fs), "died")

    def test_a_halted_dead_worker_record_records_pool_stopped(self):
        store, step, workers, fs = _rig(entry_extra={"halted": True}, alive=False)
        self._assert_reason(store, step, _sweep(store, workers, fs), "pool-stopped")

    def test_a_claim_with_no_worker_record_records_reclaimed(self):
        store, step, workers, fs = _rig()
        self._assert_reason(store, step, _sweep(store, workers, fs), "reclaimed")
