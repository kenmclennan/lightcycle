import unittest

from lightcycle.application.pool.memory_gate import MemoryGateUseCase
from lightcycle.domain.pool import WorkerPool
from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.memory_gate_status import MemoryGateStatusPort
from tests.support.fake_fs import FakeFs
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
    def __init__(self, memory_reserve_fraction=0.25, suspend_pressure=0.85, resume_pressure=0.70):
        self._mrf = memory_reserve_fraction
        self._sp = suspend_pressure
        self._rp = resume_pressure

    def memory_reserve_fraction(self):
        return self._mrf

    def suspend_pressure(self):
        return self._sp

    def resume_pressure(self):
        return self._rp


def _gate(workers, machine, config=None, worker_log=None, memory_gate_status=None):
    return MemoryGateUseCase(
        machine, workers, worker_log if worker_log is not None else FakeFs(),
        config or FakeConfig(), memory_gate_status or FakeMemoryGateStatus(),
    )


def _execute(workers, machine, **kwargs):
    pool = WorkerPool(workers.workers_state())
    return _gate(workers, machine, **kwargs).execute(pool, workers.pid_alive, now=1000)


class TestMemoryGateUseCase(unittest.TestCase):
    def test_suspends_the_newest_worker_when_pressure_at_or_above_suspend_threshold(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"},
                {"spawnid": "b", "pid": 2, "started": 5, "step": "s-2"},
            ],
            alive_pids=(1, 2),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.9, pool_share=0.9))
        result = _execute(workers, machine)

        self.assertEqual(result.suspended, "b")
        self.assertEqual(workers.suspended, [2])
        self.assertTrue(
            any(w.get("spawnid") == "b" and w.get("suspended") for w in workers._workers)
        )

    def test_resumes_the_most_recently_suspended_worker_below_resume_threshold(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "a", "pid": 1, "started": 1, "step": "s-1", "suspended": True,
                 "suspended_at": 10, "log": "/logs/a.log"},
            ],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.5, pool_share=0.05))
        worker_log = FakeFs()
        result = _execute(workers, machine, worker_log=worker_log)

        self.assertEqual(result.resumed, "a")
        self.assertEqual(workers.resumed, [1])
        self.assertFalse(any(w.get("suspended") for w in workers._workers))
        self.assertEqual(worker_log.log_mtime("/logs/a.log"), float("inf"))

    def test_neither_fires_when_pressure_is_between_the_thresholds(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.8, pool_share=0.8))
        result = _execute(workers, machine)

        self.assertIsNone(result.suspended)
        self.assertIsNone(result.resumed)
        self.assertEqual(workers.suspended, [])
        self.assertEqual(workers.resumed, [])

    def test_neither_fires_when_headroom_is_unavailable(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=None, pool_share=None))
        result = _execute(workers, machine)

        self.assertIsNone(result.cap)
        self.assertIsNone(result.suspended)
        self.assertIsNone(result.resumed)

    def test_only_one_branch_fires_per_tick_given_the_config_invariant(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"},
                {"spawnid": "b", "pid": 2, "started": 5, "step": "s-2", "suspended": True,
                 "suspended_at": 10, "log": "/logs/b.log"},
            ],
            alive_pids=(1, 2),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.9, pool_share=0.9))
        result = _execute(workers, machine)

        self.assertEqual(result.suspended, "a")
        self.assertIsNone(result.resumed)

    def test_persists_the_tick_decision_to_the_memory_gate_status(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.8, pool_share=0.8))
        status = FakeMemoryGateStatus()
        result = _execute(workers, machine, memory_gate_status=status)

        self.assertEqual(
            status.load(),
            {"cap": result.cap, "pool_share": result.pool_share,
             "system_pressure": result.system_pressure,
             "peak_worker_share": result.peak_worker_share},
        )

    def test_resume_does_not_fire_when_headroom_is_unavailable_and_a_worker_is_suspended(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "a", "pid": 1, "started": 1, "step": "s-1", "suspended": True,
                 "suspended_at": 10, "log": "/logs/a.log"},
            ],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=None, pool_share=None))
        result = _execute(workers, machine)

        self.assertIsNone(result.resumed)
        self.assertEqual(workers.resumed, [])

    def test_admission_is_capped_to_zero_when_system_pressure_alone_is_at_suspend_threshold_and_a_worker_is_already_alive(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.9, pool_share=0.1))
        result = _execute(workers, machine)

        self.assertEqual(result.cap, 0)

    def test_admission_is_not_vetoed_when_pressure_is_between_the_thresholds(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.8, pool_share=0.1))
        result = _execute(workers, machine)

        self.assertIsNone(result.cap)

    def test_admission_still_floors_to_one_worker_when_none_are_alive_despite_high_system_pressure(self):
        workers = FakeWorkers(workers=[], alive_pids=())
        machine = FakeMachine(MachineHeadroom(system_pressure=0.95, pool_share=0.05))
        result = _execute(workers, machine)

        self.assertEqual(result.cap, 1)

    def test_suspends_on_system_pressure_alone_when_pool_share_is_low(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.9, pool_share=0.1))
        result = _execute(workers, machine)

        self.assertIsNotNone(result.suspended)
        self.assertEqual(workers.suspended, [1])

    def test_does_not_resume_while_system_pressure_remains_high_even_though_pool_share_is_low(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "a", "pid": 1, "started": 1, "step": "s-1", "suspended": True,
                 "suspended_at": 10, "log": "/logs/a.log"},
            ],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.9, pool_share=0.05))
        result = _execute(workers, machine)

        self.assertIsNone(result.resumed)
        self.assertEqual(workers.resumed, [])

    def test_persisted_cap_stays_pool_only_when_the_veto_alone_zeroes_the_returned_cap(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        machine = FakeMachine(MachineHeadroom(system_pressure=0.9, pool_share=0.1))
        status = FakeMemoryGateStatus()
        result = _execute(workers, machine, memory_gate_status=status)

        self.assertEqual(result.cap, 0)
        self.assertIsNone(status.load()["cap"])
