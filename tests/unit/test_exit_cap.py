import json
import unittest

from lightcycle.adapters.claude_stream import ClaudeStreamAdapter
from lightcycle.application.pool.no_op_gates import NoOpGit, NoOpWorktrees
from lightcycle.application.pool.sweep import SweepUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.step_factory import create_owned_step

CAP = 3
ASSISTANT = json.dumps({"type": "assistant", "message": {"content": []}}).encode()


def _row(spawnid, pid, step):
    return {
        "spawnid": spawnid, "pid": pid, "step": step, "log": "/l/%s.log" % spawnid,
        "started": 0, "halted": False,
    }


def _sweep(store, workers, spin, log):
    return SweepUseCase(
        store, workers, worktrees=NoOpWorktrees(), git=NoOpGit(),
        worker_log=FakeFs(files={"/l/sp%d.log" % i: log for i in range(10)}), spin_port=spin,
        spin_cap=CAP, stream=ClaudeStreamAdapter(),
    ).execute(1000.0, 120, 1800)


def _claimed_step(store):
    step = create_owned_step(store, "build: t", stage="build", role="agent")
    store.claim_ready("agent", "gone")
    return step


class TestExitCap(unittest.TestCase):
    def test_loop_parks_at_the_cap(self):
        store = FakeStore()
        step = _claimed_step(store)
        spin = FakeSpinPort()
        for i in range(CAP):
            if i:
                store.claim_ready("agent", "gone")
            workers = FakeWorkers(workers=[_row("sp%d" % i, i + 1, step)])
            resp = _sweep(store, workers, spin, ASSISTANT)
            if i < CAP - 1:
                self.assertEqual(resp.swept, [step])
                self.assertEqual(store.get_node(step).state, "queued")
        self.assertEqual(resp.parked, [step])
        node = store.get_node(step)
        self.assertEqual(node.state, "waiting")
        self.assertIn("%d times" % CAP, node.park.reason)
        self.assertEqual(spin.load().exits, {})

    def test_no_activity_deaths_still_use_the_spin_counter(self):
        store = FakeStore()
        step = _claimed_step(store)
        spin = FakeSpinPort()

        _sweep(store, FakeWorkers(workers=[_row("sp0", 1, step)]), spin, b"")

        self.assertIn(step, spin.load().steps)
        self.assertEqual(spin.load().exits, {})

    def test_stale_exit_entries_are_pruned(self):
        store = FakeStore()
        step = _claimed_step(store)
        store.complete_node(step, "done")
        spin = FakeSpinPort({"exits": {step: {"count": 1, "since": 1.0}}})

        _sweep(store, FakeWorkers(workers=[]), spin, b"")

        self.assertEqual(spin.load().exits, {})
