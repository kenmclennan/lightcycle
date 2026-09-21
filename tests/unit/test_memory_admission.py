import unittest

from lightcycle.domain.pool import Worker
from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.domain.pool.memory_admission import (
    admission_cap, admission_veto, worker_to_resume,
    worker_to_suspend,
)


class TestAdmissionCap(unittest.TestCase):
    def test_none_when_headroom_is_none(self):
        self.assertIsNone(admission_cap(None, 2, 0.25))

    def test_none_when_pool_share_is_none(self):
        headroom = MachineHeadroom(pool_share=None)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))

    def test_zero_when_projected_exceeds_ceiling(self):
        headroom = MachineHeadroom(pool_share=0.6, peak_worker_share=0.3)
        self.assertEqual(admission_cap(headroom, 2, 0.25), 0)

    def test_none_when_projected_is_within_ceiling(self):
        headroom = MachineHeadroom(pool_share=0.1)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))

    def test_boundary_at_exactly_the_ceiling_is_not_over(self):
        headroom = MachineHeadroom(pool_share=0.5, peak_worker_share=0.25)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))

    def test_alive_count_zero_floors_to_one(self):
        headroom = MachineHeadroom(pool_share=0.9)
        self.assertEqual(admission_cap(headroom, 0, 0.25), 1)

    def test_floor_does_not_apply_when_a_worker_already_exists(self):
        headroom = MachineHeadroom(pool_share=0.9, peak_worker_share=0.0)
        self.assertEqual(admission_cap(headroom, 2, 0.25), 0)

    def test_uses_peak_worker_share_not_current_pool_share_divided_by_alive_count(self):
        headroom = MachineHeadroom(pool_share=0.1, peak_worker_share=0.5)
        self.assertEqual(admission_cap(headroom, 5, 0.45), 0)

    def test_peak_worker_share_none_falls_back_to_zero(self):
        headroom = MachineHeadroom(pool_share=0.6, peak_worker_share=None)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))

    def test_high_system_pressure_alone_does_not_produce_a_cap(self):
        headroom = MachineHeadroom(pool_share=0.1)
        self.assertIsNone(admission_cap(headroom, 2, 0.25))


class TestAdmissionVeto(unittest.TestCase):
    def test_none_below_suspend_pressure(self):
        self.assertIsNone(admission_veto(0.5, 0.85, alive_count=2))

    def test_none_when_pressure_is_none(self):
        self.assertIsNone(admission_veto(None, 0.85, alive_count=2))

    def test_zero_at_or_above_suspend_pressure_when_a_worker_is_already_alive(self):
        self.assertEqual(admission_veto(0.9, 0.85, alive_count=2), 0)

    def test_boundary_at_exactly_suspend_pressure_vetoes(self):
        self.assertEqual(admission_veto(0.85, 0.85, alive_count=1), 0)

    def test_floors_to_one_when_no_worker_is_alive(self):
        self.assertEqual(admission_veto(0.9, 0.85, alive_count=0), 1)


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
        workers = [_worker("a", 1), _worker("c", 3), _worker("b", 5, suspended=True)]
        target = worker_to_suspend(workers, 0.9, 0.85)
        self.assertEqual(target.spawnid, "c")

    def test_none_when_all_are_already_suspended(self):
        workers = [_worker("a", 1, suspended=True)]
        self.assertIsNone(worker_to_suspend(workers, 0.9, 0.85))

    def test_never_suspends_the_last_working_worker(self):
        workers = [_worker("a", 1)]
        self.assertIsNone(worker_to_suspend(workers, 0.9, 0.85))

    def test_never_suspends_the_last_working_worker_beside_a_suspended_one(self):
        workers = [_worker("a", 1), _worker("b", 5, suspended=True)]
        self.assertIsNone(worker_to_suspend(workers, 0.9, 0.85))

    def test_suspends_the_newer_of_two_and_no_more_on_a_further_tick(self):
        workers = [_worker("a", 1), _worker("b", 5)]
        self.assertEqual(worker_to_suspend(workers, 0.9, 0.85).spawnid, "b")
        workers = [_worker("a", 1), _worker("b", 5, suspended=True)]
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
