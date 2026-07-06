import unittest

from the_grid.application.pool import (
    BreakerGateResponse,
    HookCompletionsUseCase,
    ListWorkersUseCase,
    ResolveLogInput,
    ResolveLogUseCase,
    SweepUseCase,
    TickInput,
    TickUseCase,
)
from the_grid.application.services.flow import FlowService
from the_grid.application.work.close_story import CloseStoryInput, CloseStoryUseCase
from the_grid.domain.pool import Breaker
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class FakeWorkers:
    def __init__(self, workers=None, alive_pids=(), pruned=0):
        self._workers = workers or []
        self._alive = set(alive_pids)
        self._pruned = pruned
        self.killed = []

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid):
        return pid in self._alive

    def kill(self, pid):
        self.killed.append(pid)

    def prune_workers(self):
        return self._pruned

    def mark_checked(self, spawnid):
        pass


class FakeBreakerGate:
    def __init__(self, breaker):
        self._breaker = breaker

    def execute(self, now):
        return BreakerGateResponse(breaker=self._breaker)


class FakeWorktrees:
    def __init__(self):
        self.removed = []

    def remove(self, story):
        self.removed.append(story)


class FakeSpawner:
    def __init__(self):
        self.spawned = []

    def spawn_worker(self, role):
        self.spawned.append(role)
        return {"spawnid": "x"}


class FakeConfig:
    def __init__(self, max_agents=4, max_boot=120, root="/grid"):
        self._ma = max_agents
        self._mb = max_boot
        self._root = root

    def max_agents(self):
        return self._ma

    def max_boot_seconds(self):
        return self._mb

    def grid_root(self):
        return self._root


class TestListWorkers(unittest.TestCase):
    def test_marks_liveness(self):
        workers = FakeWorkers(
            workers=[{"role": "coder", "pid": 1}, {"role": "reviewer", "pid": 2}], alive_pids={1}
        )
        rows = ListWorkersUseCase(workers).execute().workers
        self.assertEqual([r["alive"] for r in rows], [True, False])


class TestResolveLog(unittest.TestCase):
    def test_run_target(self):
        resp = ResolveLogUseCase(FakeWorkers(), FakeConfig(root="/grid")).execute(
            ResolveLogInput(target="run")
        )
        self.assertEqual(resp.path, "/grid/logs/run.log")

    def test_by_task_or_role_most_recent_wins(self):
        workers = FakeWorkers(
            workers=[
                {"role": "coder", "task": "b1", "log": "/l/old.log"},
                {"role": "coder", "task": "b2", "log": "/l/new.log"},
            ]
        )
        self.assertEqual(
            ResolveLogUseCase(workers, FakeConfig()).execute(ResolveLogInput(target="b1")).path,
            "/l/old.log",
        )
        self.assertEqual(
            ResolveLogUseCase(workers, FakeConfig()).execute(ResolveLogInput(target="coder")).path,
            "/l/new.log",
        )

    def test_unknown_target_is_none(self):
        self.assertIsNone(
            ResolveLogUseCase(FakeWorkers(), FakeConfig())
            .execute(ResolveLogInput(target="nope"))
            .path
        )


class TestSweep(unittest.TestCase):
    def test_reclaims_orphans_keeps_live_and_prunes(self):
        s = FakeStore()
        orphan = s.create_task("o", step="build", role="coder")
        s.update_status(orphan, "in_progress")
        s.assign(orphan, "dead-sp")
        held = s.create_task("h", step="build", role="coder")
        s.update_status(held, "in_progress")
        s.assign(held, "live-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "live-sp", "pid": 111, "task": held, "started": 100}],
            alive_pids={111},
            pruned=2,
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(result.swept, [orphan])
        self.assertEqual(result.pruned, 2)
        self.assertEqual(s.get_task(orphan).status, "ready")
        self.assertEqual(s.get_task(held).status, "in-progress")

    def test_kills_and_prunes_a_live_past_boot_worker_owning_no_task(self):
        s = FakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "zombie-sp", "pid": 222, "task": None, "started": 100}],
            alive_pids={222},
            pruned=1,
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(workers.killed, [222])
        self.assertEqual(result.killed, ["zombie-sp"])
        self.assertEqual(result.pruned, 1)

    def test_does_not_kill_a_live_worker_still_within_the_boot_window(self):
        s = FakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "booting-sp", "pid": 333, "task": None, "started": 950}],
            alive_pids={333},
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.killed, [])

    def test_does_not_kill_a_live_worker_on_a_claimed_task(self):
        s = FakeStore()
        held = s.create_task("h", step="build", role="coder")
        s.update_status(held, "in_progress")
        s.assign(held, "busy-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "busy-sp", "pid": 444, "task": held, "started": 100}],
            alive_pids={444},
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.killed, [])

    def test_live_worker_holding_task_kept_when_claimed_by_is_none(self):
        s = FakeStore()
        held = s.create_task("h", step="build", role="coder")
        s.update_status(held, "in_progress")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp", "pid": 555, "task": held, "started": 100}],
            alive_pids={555},
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.swept, [])
        self.assertEqual(s.get_task(held).status, "in-progress")

    def test_kills_the_worker_of_a_task_whose_story_was_closed_out_from_under_it(self):
        s = FakeStore()
        story = s.create_story("merged feature", epic=s.create_epic("epic"))
        task = s.create_task("build: merged feature", step="build", role="coder", parent=story)
        s.update_status(task, "in_progress")
        s.assign(task, "live-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "live-sp", "pid": 888, "task": task, "started": 100}],
            alive_pids={888},
        )
        CloseStoryUseCase(s, FakeWorktrees()).execute(CloseStoryInput(story=story, reason="merged"))

        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)

        self.assertEqual(workers.killed, [888])
        self.assertEqual(result.killed, ["live-sp"])

    def test_booting_worker_suppresses_reclaim_of_uncovered_task(self):
        s = FakeStore()
        t = s.create_task("t", step="build", role="coder")
        s.update_status(t, "in_progress")
        workers = FakeWorkers(
            workers=[{"spawnid": "boot", "pid": 666, "task": None, "started": 950}],
            alive_pids={666},
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(result.swept, [])
        self.assertEqual(s.get_task(t).status, "in-progress")


class TestTick(unittest.TestCase):
    def test_spawns_for_ready_roles_when_slots_free(self):
        s = FakeStore()
        s.create_task("b1", step="build", role="coder")
        s.create_task("b2", step="build", role="coder")
        spawner = FakeSpawner()
        result = TickUseCase(s, FakeWorkers(), spawner, FakeConfig(max_agents=4)).execute(
            TickInput(now=1000.0)
        )
        self.assertIn("coder", spawner.spawned)
        self.assertEqual(spawner.spawned, result.spawned)
        self.assertLessEqual(len(spawner.spawned), 4)

    def test_no_spawn_when_no_slots(self):
        s = FakeStore()
        s.create_task("b1", step="build", role="coder")
        spawner = FakeSpawner()
        result = TickUseCase(s, FakeWorkers(), spawner, FakeConfig(max_agents=0)).execute(
            TickInput(now=1000.0)
        )
        self.assertEqual(spawner.spawned, [])
        self.assertEqual(result.spawned, [])

    def test_breaker_open_pre_reset_spawns_nothing(self):
        s = FakeStore()
        s.create_task("b1", step="build", role="coder")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker().trip(2000.0))
        result = TickUseCase(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(spawner.spawned, [])
        self.assertTrue(result.breaker_open)
        self.assertEqual(result.breaker_reset_at, 2000.0)

    def test_breaker_half_open_spawns_exactly_one_probe(self):
        s = FakeStore()
        s.create_task("b1", step="build", role="coder")
        s.create_task("b2", step="build", role="coder")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker().trip(1000.0))
        TickUseCase(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(len(spawner.spawned), 1)

    def test_breaker_closed_spawns_normally(self):
        s = FakeStore()
        s.create_task("b1", step="build", role="coder")
        s.create_task("b2", step="build", role="coder")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker())
        result = TickUseCase(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(len(spawner.spawned), 2)
        self.assertFalse(result.breaker_open)

    def test_hook_completions_surfaced_generically(self):
        s = FakeStore()
        flow_svc = FlowService(
            FakeFs({"auditor": {"model": "sonnet", "step": "audit", "on_epic_close": True}}), s
        )
        tid = s.create_task("audit: epic", step="audit", role="auditor")
        s.note(tid, "no finding")
        s.close(tid, "done")
        s._records[tid]["closed_at"] = "2026-01-01T12:00:00"
        result = TickUseCase(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4),
            hook_completions=HookCompletionsUseCase(s, flow_svc),
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.hook_completed, [("audit", tid, "no finding")])

    def test_no_hook_completions_use_case_yields_empty(self):
        s = FakeStore()
        result = TickUseCase(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4)
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.hook_completed, [])


if __name__ == "__main__":
    unittest.main()
