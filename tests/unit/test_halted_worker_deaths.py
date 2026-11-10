import unittest

from lightcycle.adapters.claude_stream import ClaudeStreamAdapter
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.breaker_gate import BreakerGateUseCase
from lightcycle.application.pool.no_op_gates import NoOpGit, NoOpWorktrees
from lightcycle.application.pool.sweep import SweepUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.step_factory import create_owned_step
from tests.unit.test_breaker_gate import FakeBreakerPort, FakeConfig

HALT_NOTE = "halted by the driver: stop now"
SPIN_CAP = 3


def _halted_row(spawnid, pid, step, halted=True):
    return {
        "spawnid": spawnid, "pid": pid, "step": step, "log": "/l/%s.log" % spawnid,
        "started": 0, "halted": halted,
    }


class TestSweepSkipsHaltedDeaths(unittest.TestCase):
    def _sweep(self, store, workers, spin):
        SweepUseCase(
            store, workers, worktrees=NoOpWorktrees(), git=NoOpGit(),
            worker_log=FakeFs(files={"/l/sp1.log": b""}), spin_port=spin,
            spin_cap=SPIN_CAP, stream=ClaudeStreamAdapter(),
        ).execute(1000.0, 120, 1800)

    def _halted_step(self, store):
        step = create_owned_step(store, "build: t", stage="build", role="agent")
        ParkStepUseCase(store).execute(ParkInput(step, HALT_NOTE, "resume"))
        return step

    def test_a_halted_dead_worker_swept_spin_cap_times_never_parks_the_step(self):
        store = FakeStore()
        step = self._halted_step(store)
        workers = FakeWorkers(workers=[_halted_row("sp1", 1, step)])
        spin = FakeSpinPort()

        for _ in range(SPIN_CAP + 1):
            self._sweep(store, workers, spin)

        node = store.get_node(step)
        self.assertEqual(node.park.reason, HALT_NOTE)
        self.assertEqual(spin.load().steps, {})

    def test_an_unhalted_dead_worker_with_an_empty_log_is_counted(self):
        store = FakeStore()
        step = self._halted_step(store)
        workers = FakeWorkers(workers=[_halted_row("sp1", 1, step, halted=False)])
        spin = FakeSpinPort()

        self._sweep(store, workers, spin)

        self.assertIn(step, spin.load().steps)


class TestBreakerGateSkipsHaltedDeaths(unittest.TestCase):
    def test_only_halted_no_activity_deaths_do_not_open_the_pool_wide_guard(self):
        store = FakeStore()
        steps = [create_owned_step(store, "build: %d" % i, stage="build", role="agent") for i in range(2)]
        workers = FakeWorkers(
            workers=[_halted_row("w%d" % i, i + 1, step) for i, step in enumerate(steps)]
        )
        fs = FakeFs(files={"/l/w0.log": b"", "/l/w1.log": b""})

        result = BreakerGateUseCase(
            workers, fs, FakeBreakerPort(), FakeConfig(spin_cap=1),
            spin_port=FakeSpinPort(), store=store, stream=ClaudeStreamAdapter(),
        ).execute(now=100)

        self.assertFalse(result.spin_open)
        self.assertFalse(result.spin_opened)
        self.assertEqual(
            sorted(w.spawnid for w in workers.workers_state() if w.checked), ["w0", "w1"]
        )
        self.assertTrue(all(store.get_node(s).role == "agent" for s in steps))
