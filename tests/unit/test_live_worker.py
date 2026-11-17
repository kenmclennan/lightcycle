import unittest

from lightcycle.application.work.live_worker import live_claimed_step
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers


class TestLiveClaimedStep(unittest.TestCase):
    def test_a_step_claimed_by_a_live_spawn_is_reported_and_a_dead_or_unclaimed_one_is_not(self):
        s = FakeStore()
        item = s.create_item("an item", "a description")
        live = s.create_step(stage="build", role="agent", item=item)
        dead = s.create_step(stage="build", role="agent", item=item)
        idle = s.create_step(stage="build", role="agent", item=item)
        s.claim_ready("agent", "live-spawn", item=item)
        s.claim_ready("agent", "dead-spawn", item=item)
        workers = FakeWorkers(
            workers=[
                {"spawnid": "live-spawn", "pid": 7, "started": 1, "step": live},
                {"spawnid": "dead-spawn", "pid": 8, "started": 1, "step": dead},
            ],
            alive_pids=(7,),
        )
        self.assertEqual(live_claimed_step(s, workers, {live, dead, idle}), live)
        self.assertIsNone(live_claimed_step(s, workers, {dead}))
        self.assertIsNone(live_claimed_step(s, workers, {idle}))
        self.assertIsNone(live_claimed_step(s, workers, set()))
