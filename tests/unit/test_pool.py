import unittest

from the_grid.application.pool import Sweep, Tick
from tests.fake_store import FakeStore


class FakeWorkers:
    def __init__(self, workers=None, alive_pids=(), pruned=0):
        self._workers = workers or []
        self._alive = set(alive_pids)
        self._pruned = pruned

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid):
        return pid in self._alive

    def prune_workers(self):
        return self._pruned


class FakeSpawner:
    def __init__(self):
        self.spawned = []

    def spawn_worker(self, role):
        self.spawned.append(role)
        return {"spawnid": "x"}


class FakeConfig:
    def __init__(self, max_agents=4, max_boot=120):
        self._ma = max_agents
        self._mb = max_boot

    def max_agents(self):
        return self._ma

    def max_boot_seconds(self):
        return self._mb


class TestSweep(unittest.TestCase):
    def test_reclaims_orphans_keeps_live_and_prunes(self):
        s = FakeStore()
        orphan = s.create_task("o", step="build", role="coder")
        s.update_status(orphan, "in_progress")
        s.assign(orphan, "dead-sp")
        held = s.create_task("h", step="build", role="coder")
        s.update_status(held, "in_progress")
        s.assign(held, "live-sp")
        workers = FakeWorkers(workers=[{"spawnid": "live-sp", "pid": 111}],
                              alive_pids={111}, pruned=2)
        result = Sweep(s, workers).execute()
        self.assertEqual(result["swept"], [orphan])
        self.assertEqual(result["pruned"], 2)
        self.assertEqual(s.get_task(orphan).status, "ready")
        self.assertEqual(s.get_task(held).status, "in-progress")


class TestTick(unittest.TestCase):
    def test_spawns_for_ready_roles_when_slots_free(self):
        s = FakeStore()
        s.create_task("b1", step="build", role="coder")
        s.create_task("b2", step="build", role="coder")
        spawner = FakeSpawner()
        result = Tick(s, FakeWorkers(), spawner, FakeConfig(max_agents=4)).execute(1000.0)
        self.assertIn("coder", spawner.spawned)
        self.assertEqual(spawner.spawned, result["spawned"])
        self.assertLessEqual(len(spawner.spawned), 4)

    def test_no_spawn_when_no_slots(self):
        s = FakeStore()
        s.create_task("b1", step="build", role="coder")
        spawner = FakeSpawner()
        result = Tick(s, FakeWorkers(), spawner, FakeConfig(max_agents=0)).execute(1000.0)
        self.assertEqual(spawner.spawned, [])
        self.assertEqual(result["spawned"], [])


if __name__ == "__main__":
    unittest.main()
