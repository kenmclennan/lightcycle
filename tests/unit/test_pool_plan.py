import unittest

from the_grid.domain.pool import PoolPlan, ReadyQueue
from the_grid.domain.work import Task


def tasks(*roles):
    return [Task(id="t-%d" % i, role=r) for i, r in enumerate(roles)]


class TestReadyQueue(unittest.TestCase):
    def test_roles_keeps_repeats_and_skips_human(self):
        self.assertEqual(ReadyQueue(tasks("coder", "coder", "human", "reviewer")).roles(),
                         ["coder", "coder", "reviewer"])

    def test_distinct_roles_dedupes_and_skips_human(self):
        self.assertEqual(ReadyQueue(tasks("coder", "coder", "human", "reviewer")).distinct_roles(),
                         ["coder", "reviewer"])


class TestPoolPlan(unittest.TestCase):
    def test_fills_up_to_slots_in_queue_order(self):
        self.assertEqual(PoolPlan({}, 2).roles_to_spawn(["coder", "coder", "coder", "reviewer"]),
                         ["coder", "coder"])

    def test_preserves_role_mix(self):
        self.assertEqual(PoolPlan({}, 5).roles_to_spawn(["coder", "reviewer", "coder"]),
                         ["coder", "reviewer", "coder"])

    def test_inflight_worker_covers_a_ready_task(self):
        self.assertEqual(PoolPlan({"coder": 1}, 5).roles_to_spawn(["coder", "coder", "reviewer"]),
                         ["coder", "reviewer"])

    def test_zero_slots_spawns_nothing(self):
        self.assertEqual(PoolPlan({}, 0).roles_to_spawn(["coder"]), [])

    def test_inflight_does_not_consume_a_slot(self):
        self.assertEqual(PoolPlan({"coder": 1}, 1).roles_to_spawn(["coder"]), [])


if __name__ == "__main__":
    unittest.main()
