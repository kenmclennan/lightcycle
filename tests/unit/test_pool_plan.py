import unittest

from the_grid.domain.pool import pool_plan, ready_roles, ready_task_roles
from the_grid.domain.work import Task


def tasks(*roles):
    return [Task(id="t-%d" % i, role=r) for i, r in enumerate(roles)]


class TestReadyRoles(unittest.TestCase):
    def test_dedupes_and_skips_human(self):
        self.assertEqual(ready_roles(tasks("coder", "coder", "human", "reviewer")),
                         ["coder", "reviewer"])

    def test_task_roles_keeps_repeats_and_skips_human(self):
        self.assertEqual(ready_task_roles(tasks("coder", "coder", "human", "reviewer")),
                         ["coder", "coder", "reviewer"])


class TestPoolPlan(unittest.TestCase):
    def test_fills_up_to_slots_in_queue_order(self):
        self.assertEqual(pool_plan(["coder", "coder", "coder", "reviewer"], {}, 2), ["coder", "coder"])

    def test_preserves_role_mix(self):
        self.assertEqual(pool_plan(["coder", "reviewer", "coder"], {}, 5), ["coder", "reviewer", "coder"])

    def test_inflight_worker_covers_a_ready_task(self):
        self.assertEqual(pool_plan(["coder", "coder", "reviewer"], {"coder": 1}, 5),
                         ["coder", "reviewer"])

    def test_zero_slots_spawns_nothing(self):
        self.assertEqual(pool_plan(["coder"], {}, 0), [])

    def test_inflight_does_not_consume_a_slot(self):
        self.assertEqual(pool_plan(["coder"], {"coder": 1}, 1), [])


if __name__ == "__main__":
    unittest.main()
