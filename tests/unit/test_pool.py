import unittest

from lightcycle.application.pool import (
    BackupResponse,
    BreakerGateResponse,
    HookCompletionsUseCase,
    ListWorkersUseCase,
    ResolveLogInput,
    ResolveLogUseCase,
    SweepUseCase,
    TickInput,
    TickUseCase,
)
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.domain.pool import Breaker
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class FakeWorkers:
    def __init__(self, workers=None, alive_pids=(), pruned=0):
        self._workers = workers or []
        self._alive = set(alive_pids)
        self._pruned = pruned
        self.killed = []
        self.reaped = 0
        self.calls = []

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid, started=None):
        self.calls.append("probe")
        return pid in self._alive

    def reap(self):
        self.reaped += 1
        self.calls.append("reap")

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


class FakeBackupGate:
    def __init__(self, response):
        self._response = response

    def execute(self, now):
        return self._response


class FakeWorktrees:
    def __init__(self, paths=None, has_repo=True):
        self.removed = []
        self._paths = paths or {}
        self._has_repo = has_repo

    def remove(self, item):
        self.removed.append(item)

    def has_repo(self, item):
        return self._has_repo

    def worktree_path(self, item):
        return self._paths.get(item, "/worktrees/%s" % item)


class FakeCaptureGit:
    def __init__(self, dirty=(), non_git=(), fail=()):
        self._dirty = set(dirty)
        self._non_git = set(non_git)
        self._fail = set(fail)
        self.commits = []

    def is_git_repo(self, root):
        return root not in self._non_git

    def has_uncommitted(self, root):
        return root in self._dirty

    def commit_all(self, root, message):
        self.commits.append((root, message))
        return root not in self._fail


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

    def engine_root(self):
        return self._root

    def data_root(self):
        return self._root

    def prompts_root(self):
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
                {"role": "coder", "step": "b1", "log": "/l/old.log"},
                {"role": "coder", "step": "b2", "log": "/l/new.log"},
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
        orphan = s.create_step("o", step="build", role="coder")
        s.update_state(orphan, "in_progress")
        s.assign(orphan, "dead-sp")
        held = s.create_step("h", step="build", role="coder")
        s.update_state(held, "in_progress")
        s.assign(held, "live-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "live-sp", "pid": 111, "step": held, "started": 100}],
            alive_pids={111},
            pruned=2,
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(result.swept, [orphan])
        self.assertEqual(result.pruned, 2)
        self.assertEqual(s.get_node(orphan).state, "ready")
        self.assertEqual(s.get_node(held).state, "in_progress")

    def test_kills_and_prunes_a_live_past_boot_worker_owning_no_task(self):
        s = FakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "zombie-sp", "pid": 222, "step": None, "started": 100}],
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
            workers=[{"spawnid": "booting-sp", "pid": 333, "step": None, "started": 950}],
            alive_pids={333},
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.killed, [])

    def test_does_not_kill_a_live_worker_on_a_claimed_task(self):
        s = FakeStore()
        held = s.create_step("h", step="build", role="coder")
        s.update_state(held, "in_progress")
        s.assign(held, "busy-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "busy-sp", "pid": 444, "step": held, "started": 100}],
            alive_pids={444},
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.killed, [])

    def test_live_worker_holding_task_kept_when_claimed_by_is_none(self):
        s = FakeStore()
        held = s.create_step("h", step="build", role="coder")
        s.update_state(held, "in_progress")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp", "pid": 555, "step": held, "started": 100}],
            alive_pids={555},
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.swept, [])
        self.assertIn(held, [t.id for t in s.claimed_steps()])

    def test_kills_the_worker_of_a_task_whose_story_was_closed_out_from_under_it(self):
        s = FakeStore()
        item = s.create_item("merged feature", theme=s.create_theme("theme"))
        step = s.create_step("build: merged feature", step="build", role="coder", parent=item)
        s.update_state(step, "in_progress")
        s.assign(step, "live-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "live-sp", "pid": 888, "step": step, "started": 100}],
            alive_pids={888},
        )
        CloseItemUseCase(s, FakeWorktrees()).execute(CloseItemInput(item=item, reason="merged"))

        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)

        self.assertEqual(workers.killed, [888])
        self.assertEqual(result.killed, ["live-sp"])

    def test_booting_worker_suppresses_reclaim_of_uncovered_task(self):
        s = FakeStore()
        t = s.create_step("t", step="build", role="coder")
        s.update_state(t, "in_progress")
        workers = FakeWorkers(
            workers=[{"spawnid": "boot", "pid": 666, "step": None, "started": 950}],
            alive_pids={666},
        )
        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)
        self.assertEqual(result.swept, [])
        self.assertIn(t, [n.id for n in s.claimed_steps()])

    def test_reclaiming_a_dirty_worktree_commits_it_before_reclaim(self):
        s = FakeStore()
        item = s.create_item("feature", theme=s.create_theme("theme"))
        step = s.create_step("build: feature", step="build", role="coder", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(dirty={"/worktrees/%s" % item})

        result = SweepUseCase(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [step])
        self.assertEqual(git.commits, [("/worktrees/%s" % item, "wip: preserved %s on reclaim" % step)])
        self.assertEqual(s.get_node(step).state, "ready")

    def test_reclaiming_a_clean_worktree_does_not_commit(self):
        s = FakeStore()
        item = s.create_item("feature", theme=s.create_theme("theme"))
        step = s.create_step("build: feature", step="build", role="coder", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit()

        result = SweepUseCase(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(git.commits, [])
        self.assertEqual(s.get_node(step).state, "ready")

    def test_reclaiming_a_non_git_worktree_does_not_commit(self):
        s = FakeStore()
        item = s.create_item("feature", theme=s.create_theme("theme"))
        step = s.create_step("build: feature", step="build", role="coder", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(non_git={"/worktrees/%s" % item})

        result = SweepUseCase(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(git.commits, [])
        self.assertEqual(s.get_node(step).state, "ready")

    def test_reclaiming_with_no_worktrees_or_git_ports_wired_is_a_noop(self):
        s = FakeStore()
        step = s.create_step("t", step="build", role="coder")
        s.update_state(step, "in_progress")
        workers = FakeWorkers()

        result = SweepUseCase(s, workers).execute(now=1000, max_boot=120)

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(s.get_node(step).state, "ready")

    def test_reclaiming_a_repo_less_step_does_not_consult_git(self):
        s = FakeStore()
        step = s.create_step("build: t", step="build", role="coder")
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(has_repo=False)
        git = FakeCaptureGit()

        result = SweepUseCase(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(git.commits, [])
        self.assertEqual(s.get_node(step).state, "ready")

    def test_a_failed_commit_still_reclaims_and_is_reported(self):
        s = FakeStore()
        item = s.create_item("feature", theme=s.create_theme("theme"))
        step = s.create_step("build: feature", step="build", role="coder", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(dirty={"/worktrees/%s" % item}, fail={"/worktrees/%s" % item})

        result = SweepUseCase(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.capture_failed, [step])
        self.assertEqual(s.get_node(step).state, "ready")

    def test_capture_happens_before_reclaim(self):
        events = []

        class OrderTrackingStore(FakeStore):
            def reclaim(self, tid):
                events.append(("reclaim", tid))
                return super().reclaim(tid)

        class OrderTrackingGit(FakeCaptureGit):
            def commit_all(self, root, message):
                events.append(("commit", root))
                return super().commit_all(root, message)

        s = OrderTrackingStore()
        item = s.create_item("feature", theme=s.create_theme("theme"))
        step = s.create_step("build: feature", step="build", role="coder", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = OrderTrackingGit(dirty={"/worktrees/%s" % item})

        SweepUseCase(s, workers, worktrees=worktrees, git=git).execute(now=1000, max_boot=120)

        self.assertEqual(events, [("commit", "/worktrees/%s" % item), ("reclaim", step)])


class TestTick(unittest.TestCase):
    def test_reaps_dead_children_before_probing_liveness(self):
        s = FakeStore()
        workers = FakeWorkers(workers=[{"spawnid": "sp-1", "pid": 1, "started": 0}], alive_pids={1})
        TickUseCase(s, workers, FakeSpawner(), FakeConfig(max_agents=4)).execute(
            TickInput(now=1000.0)
        )
        self.assertEqual(workers.reaped, 1)
        self.assertIn("probe", workers.calls)
        self.assertLess(
            workers.calls.index("reap"),
            workers.calls.index("probe"),
            "reap must run before any liveness probe",
        )

    def test_spawns_for_ready_roles_when_slots_free(self):
        s = FakeStore()
        s.create_step("b1", step="build", role="coder")
        s.create_step("b2", step="build", role="coder")
        spawner = FakeSpawner()
        result = TickUseCase(s, FakeWorkers(), spawner, FakeConfig(max_agents=4)).execute(
            TickInput(now=1000.0)
        )
        self.assertIn("coder", spawner.spawned)
        self.assertEqual(spawner.spawned, result.spawned)
        self.assertLessEqual(len(spawner.spawned), 4)

    def test_no_spawn_when_no_slots(self):
        s = FakeStore()
        s.create_step("b1", step="build", role="coder")
        spawner = FakeSpawner()
        result = TickUseCase(s, FakeWorkers(), spawner, FakeConfig(max_agents=0)).execute(
            TickInput(now=1000.0)
        )
        self.assertEqual(spawner.spawned, [])
        self.assertEqual(result.spawned, [])

    def test_breaker_open_pre_reset_spawns_nothing(self):
        s = FakeStore()
        s.create_step("b1", step="build", role="coder")
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
        s.create_step("b1", step="build", role="coder")
        s.create_step("b2", step="build", role="coder")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker().trip(1000.0))
        TickUseCase(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(len(spawner.spawned), 1)

    def test_breaker_closed_spawns_normally(self):
        s = FakeStore()
        s.create_step("b1", step="build", role="coder")
        s.create_step("b2", step="build", role="coder")
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
            FakeFs({"auditor": {"model": "sonnet", "step": "audit", "on_theme_close": True}}), s
        )
        tid = s.create_step("audit: theme", step="audit", role="auditor")
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

    def test_backup_gate_wired_in_populates_backed_up_and_pruned(self):
        s = FakeStore()
        backup_gate = FakeBackupGate(
            BackupResponse(created="store-1000.db.gz", pruned=["store-1.db.gz"])
        )
        result = TickUseCase(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4), backup_gate=backup_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.backed_up, "store-1000.db.gz")
        self.assertEqual(result.backup_pruned, ["store-1.db.gz"])

    def test_no_backup_gate_leaves_defaults(self):
        s = FakeStore()
        result = TickUseCase(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4)
        ).execute(TickInput(now=1000.0))
        self.assertIsNone(result.backed_up)
        self.assertEqual(result.backup_pruned, [])


if __name__ == "__main__":
    unittest.main()
