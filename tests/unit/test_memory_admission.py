import unittest

from lightcycle.domain.pool import Worker
from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.domain.pool.memory_admission import admission_cap, worker_to_resume


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


def _worker(spawnid, started, suspended=False, suspended_at=None):
    return Worker(spawnid=spawnid, pid=1, started=started, suspended=suspended, suspended_at=suspended_at)


class TestAdmissionCapAtTheCalibratedCeiling(unittest.TestCase):
    def test_projected_exactly_at_the_ceiling_is_not_over(self):
        headroom = MachineHeadroom(pool_share=0.25, peak_worker_share=0.10)
        self.assertIsNone(admission_cap(headroom, 2, 0.65))

    def test_projected_just_over_the_ceiling_caps_to_zero_with_a_worker_working(self):
        headroom = MachineHeadroom(pool_share=0.2501, peak_worker_share=0.10)
        self.assertEqual(admission_cap(headroom, 2, 0.65), 0)

    def test_projected_just_over_the_ceiling_floors_to_one_with_none_working(self):
        headroom = MachineHeadroom(pool_share=0.2501, peak_worker_share=0.10)
        self.assertEqual(admission_cap(headroom, 0, 0.65), 1)


class TestWorkerToResume(unittest.TestCase):
    def test_returns_the_most_recently_suspended(self):
        workers = [
            _worker("a", 1, suspended=True, suspended_at=10),
            _worker("b", 2, suspended=True, suspended_at=30),
        ]
        self.assertEqual(worker_to_resume(workers).spawnid, "b")

    def test_none_when_none_are_suspended(self):
        self.assertIsNone(worker_to_resume([_worker("a", 1)]))

    def test_none_when_there_are_no_workers(self):
        self.assertIsNone(worker_to_resume([]))

    def test_ignores_workers_that_are_not_suspended(self):
        workers = [
            _worker("a", 1, suspended=True, suspended_at=10),
            _worker("b", 2),
        ]
        self.assertEqual(worker_to_resume(workers).spawnid, "a")
