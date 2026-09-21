import unittest

from lightcycle.application.pool.pool_hold_status import PoolHoldStatusUseCase
from lightcycle.ports.memory_gate_status import MemoryGateStatusPort
from lightcycle.ports.workers import RegistryUnreadable
from tests.support.fake_workers import FakeWorkers


class FakeMemoryGateStatus(MemoryGateStatusPort):
    def __init__(self, state=None):
        self._state = state if state is not None else {}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class FakeConfig:
    def __init__(self, max_agents=5):
        self._max_agents = max_agents

    def max_agents(self):
        return self._max_agents


class UnreadableWorkers(FakeWorkers):
    def workers_state(self):
        raise RegistryUnreadable("boom")


class TestPoolHoldStatusUseCase(unittest.TestCase):
    def test_unreadable_registry_reports_not_holding(self):
        result = PoolHoldStatusUseCase(
            FakeMemoryGateStatus({"cap": 0}), UnreadableWorkers(), FakeConfig(),
        ).execute(lambda pid, started=None: True)

        self.assertFalse(result.holding)
        self.assertEqual(result.alive, 0)

    def test_cap_zero_is_holding(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        result = PoolHoldStatusUseCase(
            FakeMemoryGateStatus({"cap": 0}), workers, FakeConfig(),
        ).execute(workers.pid_alive)

        self.assertTrue(result.holding)

    def test_cap_one_is_not_holding(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        result = PoolHoldStatusUseCase(
            FakeMemoryGateStatus({"cap": 1}), workers, FakeConfig(),
        ).execute(workers.pid_alive)

        self.assertFalse(result.holding)

    def test_cap_none_is_not_holding(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        result = PoolHoldStatusUseCase(
            FakeMemoryGateStatus({"cap": None}), workers, FakeConfig(),
        ).execute(workers.pid_alive)

        self.assertFalse(result.holding)

    def test_missing_state_is_not_holding(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        result = PoolHoldStatusUseCase(
            FakeMemoryGateStatus(), workers, FakeConfig(),
        ).execute(workers.pid_alive)

        self.assertFalse(result.holding)

    def test_alive_and_max_agents_read_live_from_the_worker_registry_not_the_persisted_state(self):
        workers = FakeWorkers(
            workers=[
                {"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"},
                {"spawnid": "b", "pid": 2, "started": 1, "step": "s-2"},
            ],
            alive_pids=(1, 2),
        )
        result = PoolHoldStatusUseCase(
            FakeMemoryGateStatus({"cap": 0}), workers, FakeConfig(max_agents=9),
        ).execute(workers.pid_alive)

        self.assertEqual(result.alive, 2)
        self.assertEqual(result.max_agents, 9)

    def test_holding_true_when_a_worker_is_suspended_even_though_cap_is_not_zero(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1", "suspended": True}],
            alive_pids=(1,),
        )
        result = PoolHoldStatusUseCase(
            FakeMemoryGateStatus({"cap": 1}), workers, FakeConfig(),
        ).execute(workers.pid_alive)

        self.assertTrue(result.holding)

    def test_is_not_holding_when_cap_is_not_zero_and_nothing_is_suspended(self):
        workers = FakeWorkers(
            workers=[{"spawnid": "a", "pid": 1, "started": 1, "step": "s-1"}],
            alive_pids=(1,),
        )
        result = PoolHoldStatusUseCase(
            FakeMemoryGateStatus({"cap": 1}), workers, FakeConfig(),
        ).execute(workers.pid_alive)

        self.assertFalse(result.holding)


if __name__ == "__main__":
    unittest.main()
