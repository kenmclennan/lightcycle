import unittest

from lightcycle.application.pool.memory_gate import MemoryGateUseCase
from lightcycle.application.pool.pool_hold_status import PoolHoldStatusUseCase
from lightcycle.domain.pool import WorkerPool
from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.memory_gate_status import MemoryGateStatusPort
from tests.support.fake_machine import FakeMachine
from tests.support.fake_workers import FakeWorkers


class FakeMemoryGateStatus(MemoryGateStatusPort):
    def __init__(self, state=None):
        self._state = state if state is not None else {}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class FakeConfig:
    def __init__(self, memory_reserve_fraction=0.65):
        self._mrf = memory_reserve_fraction

    def memory_reserve_fraction(self):
        return self._mrf


class FakeHoldConfig:
    def max_agents(self):
        return 5


def _gate(machine, config=None, memory_gate_status=None):
    return MemoryGateUseCase(
        machine, config or FakeConfig(), memory_gate_status or FakeMemoryGateStatus(),
    )


def _execute(workers, machine, **kwargs):
    pool = WorkerPool(workers.workers_state())
    return _gate(machine, **kwargs).execute(pool, workers.pid_alive)


def _legacy_flagged(spawnid, pid, started=1):
    return {"spawnid": spawnid, "pid": pid, "started": started, "step": "s-%d" % pid,
            "suspended": True}


def _working(spawnid, pid, started=1):
    return {"spawnid": spawnid, "pid": pid, "started": started, "step": "s-%d" % pid}


class TestMemoryGateUseCase(unittest.TestCase):
    def test_gate_is_inert_at_the_measured_worst_normal_case(self):
        workers = FakeWorkers(
            workers=[_working(str(i), i, started=i) for i in range(1, 6)],
            alive_pids=(1, 2, 3, 4, 5),
        )
        machine = FakeMachine(MachineHeadroom(pool_share=0.1318, peak_worker_share=0.0963))
        result = _execute(workers, machine)

        self.assertIsNone(result.cap)

    def test_caps_admission_to_zero_above_the_ceiling(self):
        workers = FakeWorkers(
            workers=[_working("a", 1), _working("b", 2, started=5)],
            alive_pids=(1, 2),
        )
        machine = FakeMachine(MachineHeadroom(pool_share=0.30, peak_worker_share=0.10))
        result = _execute(workers, machine)

        self.assertEqual(result.cap, 0)

    def test_floors_admission_to_one_above_the_ceiling_when_none_is_working(self):
        workers = FakeWorkers(workers=[], alive_pids=())
        machine = FakeMachine(MachineHeadroom(pool_share=0.30, peak_worker_share=0.10))
        result = _execute(workers, machine)

        self.assertEqual(result.cap, 1)

    def test_a_legacy_flagged_entry_counts_as_working(self):
        workers = FakeWorkers(workers=[_legacy_flagged("a", 1)], alive_pids=(1,))
        machine = FakeMachine(MachineHeadroom(pool_share=0.30, peak_worker_share=0.10))
        result = _execute(workers, machine)

        self.assertEqual(result.cap, 0)

    def test_persisted_status_equals_the_returned_cap_and_shares(self):
        workers = FakeWorkers(workers=[_working("a", 1)], alive_pids=(1,))
        machine = FakeMachine(MachineHeadroom(pool_share=0.30, peak_worker_share=0.10))
        status = FakeMemoryGateStatus()
        result = _execute(workers, machine, memory_gate_status=status)

        self.assertEqual(
            status.load(), {"cap": result.cap, "pool_share": 0.30, "peak_worker_share": 0.10},
        )
        self.assertEqual(result.cap, 0)

    def test_persisted_zero_cap_reads_as_a_hold(self):
        workers = FakeWorkers(workers=[_working("a", 1)], alive_pids=(1,))
        machine = FakeMachine(MachineHeadroom(pool_share=0.30, peak_worker_share=0.10))
        status = FakeMemoryGateStatus()
        _execute(workers, machine, memory_gate_status=status)

        hold = PoolHoldStatusUseCase(status, workers, FakeHoldConfig()).execute(workers.pid_alive)
        self.assertTrue(hold.holding)

    def test_unavailable_headroom_yields_no_cap(self):
        workers = FakeWorkers(workers=[_working("a", 1)], alive_pids=(1,))
        machine = FakeMachine(MachineHeadroom(pool_share=None))
        result = _execute(workers, machine)

        self.assertIsNone(result.cap)

    def test_response_and_saved_status_carry_no_system_pressure(self):
        workers = FakeWorkers(workers=[_working("a", 1)], alive_pids=(1,))
        machine = FakeMachine(MachineHeadroom(pool_share=0.2, peak_worker_share=0.1))
        status = FakeMemoryGateStatus()
        result = _execute(workers, machine, memory_gate_status=status)

        self.assertFalse(hasattr(result, "system_pressure"))
        self.assertFalse(hasattr(result, "suspended"))
        self.assertEqual(
            status.load(), {"cap": None, "pool_share": 0.2, "peak_worker_share": 0.1},
        )
