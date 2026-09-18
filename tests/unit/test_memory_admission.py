import unittest

from lightcycle.domain.pool import Worker
from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.domain.pool.memory_admission import (
    admission_cap, combined_pressure, pressure_source, worker_to_resume, worker_to_suspend,
)


class TestCombinedPressure(unittest.TestCase):
    def test_returns_the_greater_regardless_of_order(self):
        self.assertEqual(combined_pressure(0.3, 0.7), 0.7)
        self.assertEqual(combined_pressure(0.7, 0.3), 0.7)

    def test_falls_back_to_whichever_value_is_available(self):
        self.assertEqual(combined_pressure(0.5, None), 0.5)
        self.assertEqual(combined_pressure(None, 0.5), 0.5)

    def test_none_when_both_are_none(self):
        self.assertIsNone(combined_pressure(None, None))

    def test_equal_values(self):
        self.assertEqual(combined_pressure(0.4, 0.4), 0.4)


class TestPressureSource(unittest.TestCase):
    def test_none_when_both_are_none(self):
        self.assertIsNone(pressure_source(None, None))

    def test_pool_when_only_pool_share_is_available(self):
        self.assertEqual(pressure_source(0.5, None), "pool")

    def test_machine_when_only_system_pressure_is_available(self):
        self.assertEqual(pressure_source(None, 0.5), "machine")

    def test_pool_when_pool_share_dominates(self):
        self.assertEqual(pressure_source(0.6, 0.3), "pool")

    def test_machine_when_system_pressure_dominates(self):
        self.assertEqual(pressure_source(0.3, 0.6), "machine")

    def test_pool_wins_the_tie(self):
        self.assertEqual(pressure_source(0.4, 0.4), "pool")


class TestAdmissionCap(unittest.TestCase):
    def test_none_when_headroom_is_none(self):
        self.assertIsNone(admission_cap(None, 2, 0.25))

    def test_none_when_pool_share_is_none(self):
        headroom = MachineHeadroom(system_pressure=0.7, pool_share=None)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))

    def test_zero_when_projected_exceeds_ceiling(self):
        headroom = MachineHeadroom(system_pressure=None, pool_share=0.6, peak_worker_share=0.3)
        self.assertEqual(admission_cap(headroom, 2, 0.25), 0)

    def test_none_when_projected_is_within_ceiling(self):
        headroom = MachineHeadroom(system_pressure=None, pool_share=0.1)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))

    def test_boundary_at_exactly_the_ceiling_is_not_over(self):
        headroom = MachineHeadroom(system_pressure=None, pool_share=0.5, peak_worker_share=0.25)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))

    def test_alive_count_zero_floors_to_one(self):
        headroom = MachineHeadroom(system_pressure=None, pool_share=0.9)
        self.assertEqual(admission_cap(headroom, 0, 0.25), 1)

    def test_floor_does_not_apply_when_a_worker_already_exists(self):
        headroom = MachineHeadroom(system_pressure=None, pool_share=0.9, peak_worker_share=0.0)
        self.assertEqual(admission_cap(headroom, 2, 0.25), 0)

    def test_uses_peak_worker_share_not_current_pool_share_divided_by_alive_count(self):
        headroom = MachineHeadroom(system_pressure=None, pool_share=0.1, peak_worker_share=0.5)
        self.assertEqual(admission_cap(headroom, 5, 0.45), 0)

    def test_peak_worker_share_none_falls_back_to_zero(self):
        headroom = MachineHeadroom(system_pressure=None, pool_share=0.6, peak_worker_share=None)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))

    def test_high_system_pressure_alone_does_not_produce_a_cap(self):
        headroom = MachineHeadroom(system_pressure=0.99, pool_share=0.1)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))


def _worker(spawnid, started, suspended=False, suspended_at=None):
    return Worker(spawnid=spawnid, pid=1, started=started, suspended=suspended, suspended_at=suspended_at)


class TestWorkerToSuspend(unittest.TestCase):
    def test_none_below_suspend_pressure(self):
        workers = [_worker("a", 1)]
        self.assertIsNone(worker_to_suspend(workers, 0.5, 0.85))

    def test_none_when_pressure_is_none(self):
        workers = [_worker("a", 1)]
        self.assertIsNone(worker_to_suspend(workers, None, 0.85))

    def test_returns_the_newest_not_yet_suspended(self):
        workers = [_worker("a", 1), _worker("b", 5), _worker("c", 3)]
        target = worker_to_suspend(workers, 0.9, 0.85)
        self.assertEqual(target.spawnid, "b")

    def test_never_returns_an_already_suspended_worker(self):
        workers = [_worker("a", 1), _worker("b", 5, suspended=True)]
        target = worker_to_suspend(workers, 0.9, 0.85)
        self.assertEqual(target.spawnid, "a")

    def test_none_when_all_are_already_suspended(self):
        workers = [_worker("a", 1, suspended=True)]
        self.assertIsNone(worker_to_suspend(workers, 0.9, 0.85))


class TestWorkerToResume(unittest.TestCase):
    def test_none_at_or_above_resume_pressure(self):
        workers = [_worker("a", 1, suspended=True, suspended_at=10)]
        self.assertIsNone(worker_to_resume(workers, 0.70, 0.70))
        self.assertIsNone(worker_to_resume(workers, 0.9, 0.70))

    def test_returns_the_most_recently_suspended(self):
        workers = [
            _worker("a", 1, suspended=True, suspended_at=10),
            _worker("b", 2, suspended=True, suspended_at=30),
        ]
        target = worker_to_resume(workers, 0.5, 0.70)
        self.assertEqual(target.spawnid, "b")

    def test_none_when_none_are_suspended(self):
        workers = [_worker("a", 1)]
        self.assertIsNone(worker_to_resume(workers, 0.5, 0.70))

    def test_none_when_pressure_is_none(self):
        workers = [_worker("a", 1, suspended=True, suspended_at=10)]
        self.assertIsNone(worker_to_resume(workers, None, 0.70))
