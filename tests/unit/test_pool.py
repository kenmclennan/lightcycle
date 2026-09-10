import json
import os
import tempfile
import unittest

from lightcycle.adapters.claude_stream import ClaudeStreamAdapter
from lightcycle.application.pool import (
    BackupResponse,
    BreakerGateResponse,
    HookCompletionsUseCase,
    ListWorkersUseCase,
    ResolveLogInput,
    ResolveLogUseCase,
    SweepUseCase,
    TailLogInput,
    TailLogUseCase,
    TickInput,
    TickUseCase,
)
from lightcycle.application.pool.no_op_gates import (
    NoOpBackupGate,
    NoOpBreakerGate,
    NoOpCadenceGate,
    NoOpFlowService,
    NoOpFs,
    NoOpGit,
    NoOpHookCompletions,
    NoOpMonitor,
    NoOpSpinPort,
    NoOpStream,
    NoOpUsageGate,
    NoOpWorktrees,
)
from lightcycle.application.pool.retro_cadence import RetroCadenceResponse
from lightcycle.application.pool.sweep import SweepResponse
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.cli import _tick_event_lines
from lightcycle.domain.pool import Breaker, SpinLedger, Worker
from lightcycle.ports.git import GitReadError
from lightcycle.ports.workers import RegistryUnreadable
from tests.support.fake_fs import FakeFs
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


class FakeWorkers:
    def __init__(self, workers=None, alive_pids=(), pruned=0,
                 raise_workers_state=False, raise_prune_workers=False,
                 workers_state_raise_after=None):
        self._workers = workers or []
        self._alive = set(alive_pids)
        self._pruned = pruned
        self.killed = []
        self.reaped = 0
        self.calls = []
        self.checked = []
        self._raise_workers_state = raise_workers_state
        self._raise_prune_workers = raise_prune_workers
        self._workers_state_raise_after = workers_state_raise_after
        self._workers_state_calls = 0

    def workers_state(self):
        self._workers_state_calls += 1
        if self._raise_workers_state:
            raise RegistryUnreadable("boom")
        if (
            self._workers_state_raise_after is not None
            and self._workers_state_calls > self._workers_state_raise_after
        ):
            raise RegistryUnreadable("boom")
        return [Worker.from_state(d) for d in self._workers]

    def pid_alive(self, pid, started=None):
        self.calls.append("probe")
        return pid in self._alive

    def reap(self):
        self.reaped += 1
        self.calls.append("reap")

    def kill(self, pid):
        self.killed.append(pid)

    def prune_workers(self):
        if self._raise_prune_workers:
            raise RegistryUnreadable("boom")
        self.workers_state()
        return self._pruned

    def mark_checked(self, spawnid):
        self.checked.append(spawnid)


class FakeBreakerGate:
    def __init__(self, breaker, spin_open=False):
        self._breaker = breaker
        self._spin_open = spin_open

    def execute(self, now):
        return BreakerGateResponse(breaker=self._breaker, spin_open=self._spin_open)


class FakeBackupGate:
    def __init__(self, response):
        self._response = response

    def execute(self, now):
        return self._response


class FakeUsageGate:
    def __init__(self):
        self.calls = []

    def execute(self, now):
        self.calls.append(now)


class FakeCadenceGate:
    def __init__(self, fired):
        self._fired = fired

    def execute(self, now):
        return RetroCadenceResponse(fired=self._fired)


class FakeWorktrees:
    def release_run(self, run, delete_remote=True):
        self.released = getattr(self, "released", [])
        self.released.append(run.id)

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
    def __init__(self, dirty=(), non_git=(), fail=(), unreadable=()):
        self._dirty = set(dirty)
        self._non_git = set(non_git)
        self._fail = set(fail)
        self._unreadable = set(unreadable)
        self.commits = []

    def is_git_repo(self, root):
        return root not in self._non_git

    def has_tracked_changes(self, root):
        if root in self._unreadable:
            raise GitReadError("git status failed in %s: fatal: not a git repository" % root)
        return root in self._dirty

    def commit_tracked(self, root, message):
        self.commits.append((root, message))
        return root not in self._fail


class FakeSpawner:
    def __init__(self):
        self.spawned = []

    def spawn_worker(self, role):
        self.spawned.append(role)
        return {"spawnid": "x"}


class FakeConfig:
    def __init__(self, max_agents=4, max_boot=120, stall_seconds=1800, root="/grid",
                 poll_seconds=5):
        self._ma = max_agents
        self._mb = max_boot
        self._ss = stall_seconds
        self._root = root
        self._ps = poll_seconds

    def max_agents(self):
        return self._ma

    def max_boot_seconds(self):
        return self._mb

    def stall_seconds(self):
        return self._ss

    def poll_seconds(self):
        return self._ps

    def spin_cap(self):
        return 3

    def engine_root(self):
        return self._root

    def data_root(self):
        return self._root

    def prompts_root(self):
        return self._root


def make_sweep(store, workers, **overrides):
    kwargs = dict(
        worktrees=NoOpWorktrees(), git=NoOpGit(), fs=NoOpFs(), spin_port=NoOpSpinPort(),
        spin_cap=3, stream=NoOpStream(),
    )
    kwargs.update(overrides)
    return SweepUseCase(store, workers, **kwargs)


def make_tick(store, workers, spawner, config, **overrides):
    kwargs = dict(
        monitor=NoOpMonitor(), cadence_gate=NoOpCadenceGate(), breaker_gate=NoOpBreakerGate(),
        hook_completions=NoOpHookCompletions(), worktrees=NoOpWorktrees(), git=NoOpGit(),
        backup_gate=NoOpBackupGate(), fs=NoOpFs(), flow_service=NoOpFlowService(),
        spin_port=NoOpSpinPort(), usage_gate=NoOpUsageGate(), stream=NoOpStream(),
    )
    kwargs.update(overrides)
    return TickUseCase(store, workers, spawner, config, **kwargs)


class TestListWorkers(unittest.TestCase):
    def test_marks_liveness(self):
        workers = FakeWorkers(
            workers=[{"role": "coder", "pid": 1}, {"role": "reviewer", "pid": 2}], alive_pids={1}
        )
        rows = ListWorkersUseCase(workers).execute().workers
        self.assertEqual([r["alive"] for r in rows], [True, False])


class TestResolveLog(unittest.TestCase):
    def test_run_target(self):
        resp = ResolveLogUseCase(FakeStore(), FakeWorkers(), FakeConfig(root="/grid")).execute(
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
            ResolveLogUseCase(FakeStore(), workers, FakeConfig())
            .execute(ResolveLogInput(target="b1")).path,
            "/l/old.log",
        )
        self.assertEqual(
            ResolveLogUseCase(FakeStore(), workers, FakeConfig())
            .execute(ResolveLogInput(target="coder")).path,
            "/l/new.log",
        )

    def test_unknown_target_is_none(self):
        self.assertIsNone(
            ResolveLogUseCase(FakeStore(), FakeWorkers(), FakeConfig())
            .execute(ResolveLogInput(target="nope"))
            .path
        )

    def test_resolves_log_from_disk_when_registry_entry_is_pruned(self):
        s = FakeStore()
        step_id = create_owned_step(s, "build: x", step="build", role="agent")
        s.assign(step_id, "sp1")
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "logs"))
        log_path = os.path.join(root, "logs", "worker-agent-sp1.log")
        with open(log_path, "w") as f:
            f.write("log\n")
        resp = ResolveLogUseCase(s, FakeWorkers(), FakeConfig(root=root)).execute(
            ResolveLogInput(target=step_id)
        )
        self.assertEqual(resp.path, log_path)

    def test_role_only_target_is_not_covered_by_the_durable_fallback(self):
        resp = ResolveLogUseCase(FakeStore(), FakeWorkers(), FakeConfig()).execute(
            ResolveLogInput(target="coder")
        )
        self.assertIsNone(resp.path)

    def test_step_never_claimed_by_a_spawned_worker_is_none(self):
        s = FakeStore()
        step_id = create_owned_step(s, "build: x", step="build", role="agent")
        resp = ResolveLogUseCase(s, FakeWorkers(), FakeConfig()).execute(
            ResolveLogInput(target=step_id)
        )
        self.assertIsNone(resp.path)


class TestTailLog(unittest.TestCase):
    def test_max_bytes_set_calls_read_tail_and_ignores_offset(self):
        fs = FakeFs(files={"/l/x.log": b"01234\n6789"})
        workers = FakeWorkers(workers=[{"role": "coder", "step": "s1", "log": "/l/x.log", "pid": 1}])
        result = TailLogUseCase(FakeStore(), workers, fs, FakeConfig()).execute(
            TailLogInput(target="s1", offset=999, max_bytes=4)
        )
        self.assertEqual(result.data, b"6789")
        self.assertEqual(result.offset, 10)

    def test_max_bytes_unset_is_unchanged_from_today(self):
        fs = FakeFs(files={"/l/x.log": b"0123456789"})
        workers = FakeWorkers(workers=[{"role": "coder", "step": "s1", "log": "/l/x.log", "pid": 1}])
        result = TailLogUseCase(FakeStore(), workers, fs, FakeConfig()).execute(
            TailLogInput(target="s1", offset=4)
        )
        self.assertEqual(result.data, b"456789")
        self.assertEqual(result.offset, 10)


_NO_WORK_LOG = (
    b"session started\n"
    b"Failed to authenticate: OAuth session expired and could not be refreshed\n"
    b"error: api_error"
)
_REAL_ACTIVITY_LOG = b'{"type":"result","subtype":"success"}'


class TestSweep(unittest.TestCase):
    def test_reclaims_orphans_keeps_live_and_prunes(self):
        s = FakeStore()
        orphan = create_owned_step(s, "o", step="build", role="agent")
        s.update_state(orphan, "in_progress")
        s.assign(orphan, "dead-sp")
        held = create_owned_step(s, "h", step="build", role="agent")
        s.update_state(held, "in_progress")
        s.assign(held, "live-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "live-sp", "pid": 111, "step": held, "started": 100}],
            alive_pids={111},
            pruned=2,
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(result.swept, [orphan])
        self.assertEqual(result.pruned, 2)
        self.assertEqual(s.get_node(orphan).state, "queued")
        self.assertEqual(s.get_node(held).state, "running")

    def test_reclaims_no_step_when_the_registry_is_unreadable(self):
        s = FakeStore()
        held = create_owned_step(s, "h", step="build", role="agent")
        s.update_state(held, "in_progress")
        s.assign(held, "live-sp")
        workers = FakeWorkers(raise_workers_state=True)
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(result, SweepResponse(swept=[], killed=[], pruned=0))
        self.assertEqual(s.get_node(held).state, "running")

    def test_second_registry_read_failing_during_prune_still_reports_the_rest(self):
        s = FakeStore()
        orphan = create_owned_step(s, "o", step="build", role="agent")
        s.update_state(orphan, "in_progress")
        s.assign(orphan, "dead-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "zombie-sp", "pid": 222, "step": None, "started": 100}],
            alive_pids={222},
            workers_state_raise_after=1,
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(result.swept, [orphan])
        self.assertEqual(result.killed, ["zombie-sp"])
        self.assertEqual(result.pruned, 0)

    def test_kills_and_prunes_a_live_past_boot_worker_owning_no_task(self):
        s = FakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "zombie-sp", "pid": 222, "step": None, "started": 100}],
            alive_pids={222},
            pruned=1,
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [222])
        self.assertEqual(result.killed, ["zombie-sp"])
        self.assertEqual(result.pruned, 1)

    def test_does_not_kill_a_live_worker_still_within_the_boot_window(self):
        s = FakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "booting-sp", "pid": 333, "step": None, "started": 950}],
            alive_pids={333},
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.killed, [])

    def test_does_not_kill_a_live_worker_on_a_claimed_task(self):
        s = FakeStore()
        held = create_owned_step(s, "h", step="build", role="agent")
        s.update_state(held, "in_progress")
        s.assign(held, "busy-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "busy-sp", "pid": 444, "step": held, "started": 100}],
            alive_pids={444},
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.killed, [])

    def test_live_worker_holding_task_kept_when_claimed_by_is_none(self):
        s = FakeStore()
        held = create_owned_step(s, "h", step="build", role="agent")
        s.update_state(held, "in_progress")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp", "pid": 555, "step": held, "started": 100}],
            alive_pids={555},
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.swept, [])
        self.assertIn(held, [t.id for t in s.claimed_steps()])

    def test_kills_the_worker_of_a_task_whose_story_was_closed_out_from_under_it(self):
        s = FakeStore()
        item = s.create_item("merged feature", "a description")
        step = s.create_step("build: merged feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        s.assign(step, "live-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "live-sp", "pid": 888, "step": step, "started": 100}],
            alive_pids={888},
        )
        CloseItemUseCase(s, FakeWorktrees()).execute(CloseItemInput(item=item, reason="merged", disposition="completed"))

        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)

        self.assertEqual(workers.killed, [888])
        self.assertEqual(result.killed, ["live-sp"])

    def test_booting_worker_suppresses_reclaim_of_uncovered_task(self):
        s = FakeStore()
        t = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(t, "in_progress")
        workers = FakeWorkers(
            workers=[{"spawnid": "boot", "pid": 666, "step": None, "started": 950}],
            alive_pids={666},
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(result.swept, [])
        self.assertIn(t, [n.id for n in s.claimed_steps()])

    def test_live_worker_mid_claim_past_the_boot_window_is_not_reclaimed(self):
        s = FakeStore()
        t = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(t, "in_progress")
        s.assign(t, "worker-sp")
        workers = FakeWorkers(
            workers=[{"spawnid": "worker-sp", "pid": 777, "step": None, "started": 100}],
            alive_pids={777},
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(result.swept, [])
        self.assertIn(t, [n.id for n in s.claimed_steps()])

    def test_reclaiming_a_dirty_worktree_commits_it_before_reclaim(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(dirty={"/worktrees/%s" % item})

        result = make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [step])
        self.assertEqual(git.commits, [("/worktrees/%s" % item, "wip: preserved %s on reclaim" % step)])
        self.assertEqual(s.get_node(step).state, "queued")

    def test_reclaiming_a_clean_worktree_does_not_commit(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit()

        result = make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(git.commits, [])
        self.assertEqual(s.get_node(step).state, "queued")

    def test_reclaiming_a_non_git_worktree_does_not_commit(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(non_git={"/worktrees/%s" % item})

        result = make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(git.commits, [])
        self.assertEqual(s.get_node(step).state, "queued")

    def test_reclaiming_with_noop_worktrees_and_git_is_still_a_noop(self):
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        workers = FakeWorkers()

        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(s.get_node(step).state, "queued")

    def test_reclaiming_a_repo_less_step_does_not_consult_git(self):
        s = FakeStore()
        step = create_owned_step(s, "build: t", step="build", role="agent")
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(has_repo=False)
        git = FakeCaptureGit()

        result = make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(git.commits, [])
        self.assertEqual(s.get_node(step).state, "queued")

    def test_a_repo_less_step_is_reported_as_not_checked_not_silently_clean(self):
        s = FakeStore()
        step = create_owned_step(s, "build: t", step="build", role="agent")
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(has_repo=False)
        git = FakeCaptureGit()

        result = make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(result.not_checked, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.capture_failed, [])

    def test_a_checked_clean_repo_is_distinguishable_from_not_checked(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(dirty=())

        result = make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(result.not_checked, [])
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.capture_failed, [])

    def test_a_failed_commit_still_reclaims_and_is_reported(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(dirty={"/worktrees/%s" % item}, fail={"/worktrees/%s" % item})

        result = make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.capture_failed, [step])
        self.assertEqual(s.get_node(step).state, "queued")

    def test_an_unreadable_worktree_is_reported_as_a_capture_failure_not_a_silent_skip(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(unreadable={"/worktrees/%s" % item})

        result = make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(result.swept, [step])
        self.assertEqual(result.preserved, [])
        self.assertEqual(result.capture_failed, [step])
        self.assertEqual(s.get_node(step).state, "queued")

    def test_capture_happens_before_reclaim(self):
        events = []

        class OrderTrackingStore(FakeStore):
            def reclaim(self, tid):
                events.append(("reclaim", tid))
                return super().reclaim(tid)

        class OrderTrackingGit(FakeCaptureGit):
            def commit_tracked(self, root, message):
                events.append(("commit", root))
                return super().commit_tracked(root, message)

        s = OrderTrackingStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = OrderTrackingGit(dirty={"/worktrees/%s" % item})

        make_sweep(s, workers, worktrees=worktrees, git=git).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )

        self.assertEqual(events, [("commit", "/worktrees/%s" % item), ("reclaim", step)])

    def test_kills_a_stalled_worker_marks_checked_and_reclaims_its_step(self):
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        s.assign(step, "stalled-sp")
        workers = FakeWorkers(
            workers=[
                {"spawnid": "stalled-sp", "pid": 999, "step": step, "started": 100, "log": "/l/1.log"}
            ],
            alive_pids={999},
        )
        fs = FakeFs(log_mtimes={"/l/1.log": 1000 - 1800 - 1})
        result = make_sweep(s, workers, fs=fs, stream=ClaudeStreamAdapter()).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [999])
        self.assertEqual(workers.checked, ["stalled-sp"])
        self.assertIn(step, result.swept)
        self.assertEqual(s.get_node(step).state, "queued")

    def test_leaves_a_worker_alone_whose_log_grew_within_the_stall_threshold(self):
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        s.assign(step, "busy-sp")
        workers = FakeWorkers(
            workers=[
                {"spawnid": "busy-sp", "pid": 999, "step": step, "started": 100, "log": "/l/1.log"}
            ],
            alive_pids={999},
        )
        fs = FakeFs(log_mtimes={"/l/1.log": 1000 - 1800 + 1})
        result = make_sweep(s, workers, fs=fs, stream=ClaudeStreamAdapter()).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.swept, [])
        self.assertEqual(s.get_node(step).state, "running")

    def test_a_worker_still_in_its_boot_window_is_never_evaluated_for_staleness(self):
        s = FakeStore()
        workers = FakeWorkers(
            workers=[{"spawnid": "boot-sp", "pid": 999, "step": None, "started": 950, "log": "/l/1.log"}],
            alive_pids={999},
        )
        fs = FakeFs(log_mtimes={"/l/1.log": 0})
        result = make_sweep(s, workers, fs=fs, stream=ClaudeStreamAdapter()).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.killed, [])

    def test_a_stalled_worker_with_a_terminal_marker_in_its_log_is_not_killed_for_staleness(self):
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        s.assign(step, "closing-sp")
        workers = FakeWorkers(
            workers=[
                {"spawnid": "closing-sp", "pid": 999, "step": step, "started": 100, "log": "/l/1.log"}
            ],
            alive_pids={999},
        )
        log_line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "input": {"command": "lc done t done"}}]
                },
            }
        )
        fs = FakeFs(
            files={"/l/1.log": log_line.encode()},
            log_mtimes={"/l/1.log": 1000 - 1800 - 1},
        )
        result = make_sweep(s, workers, fs=fs, stream=ClaudeStreamAdapter()).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.swept, [])
        self.assertEqual(s.get_node(step).state, "running")

    def test_a_stalled_worker_with_no_mtime_available_is_left_alone_this_tick(self):
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        s.assign(step, "unreadable-sp")
        workers = FakeWorkers(
            workers=[
                {
                    "spawnid": "unreadable-sp",
                    "pid": 999,
                    "step": step,
                    "started": 100,
                    "log": "/l/missing.log",
                }
            ],
            alive_pids={999},
        )
        result = make_sweep(s, workers).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [])
        self.assertEqual(result.swept, [])
        self.assertEqual(s.get_node(step).state, "running")

    def test_a_stalled_worker_is_killed_even_when_fs_is_not_wired(self):
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        s.assign(step, "stalled-sp")
        workers = FakeWorkers(
            workers=[
                {"spawnid": "stalled-sp", "pid": 999, "step": step, "started": 100, "log": "/l/1.log"}
            ],
            alive_pids={999},
        )
        fs = FakeFs(log_mtimes={"/l/1.log": 1000 - 1800 - 1})
        result = make_sweep(s, workers, fs=fs, stream=ClaudeStreamAdapter()).execute(now=1000, max_boot=120, stall_seconds=1800)
        self.assertEqual(workers.killed, [999])
        self.assertIn(step, result.swept)
        self.assertEqual(s.get_node(step).state, "queued")

    def _dead_no_work_setup(self, spin_port, spawnid="dead-sp", pid=1):
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        s.assign(step, spawnid)
        log = "/l/%s.log" % spawnid
        workers = FakeWorkers(workers=[{"spawnid": spawnid, "pid": pid, "step": step, "started": 0, "log": log}])
        fs = FakeFs(files={log: _NO_WORK_LOG})
        return s, step, workers, fs

    def test_a_no_work_death_below_the_cap_is_reclaimed_not_parked(self):
        spin_port = FakeSpinPort()
        s, step, workers, fs = self._dead_no_work_setup(spin_port)
        result = make_sweep(s, workers, fs=fs, spin_port=spin_port, spin_cap=3, stream=ClaudeStreamAdapter()).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )
        self.assertIn(step, result.swept)
        self.assertEqual(result.parked, [])
        self.assertEqual(s.get_node(step).state, "queued")
        self.assertEqual(s.get_node(step).role, "agent")

    def test_the_spin_cap_th_consecutive_no_work_death_parks_instead_of_reclaiming(self):
        spin_port = FakeSpinPort()
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        for i in range(3):
            s.update_state(step, "in_progress")
            spawnid = "dead-sp-%d" % i
            s.assign(step, spawnid)
            log = "/l/%s.log" % spawnid
            workers = FakeWorkers(
                workers=[{"spawnid": spawnid, "pid": i + 1, "step": step, "started": 0, "log": log}]
            )
            fs = FakeFs(files={log: _NO_WORK_LOG})
            result = make_sweep(s, workers, fs=fs, spin_port=spin_port, spin_cap=3, stream=ClaudeStreamAdapter()).execute(
                now=1000 + i, max_boot=120, stall_seconds=1800
            )
        self.assertEqual(result.parked, [step])
        self.assertNotIn(step, result.swept)
        self.assertEqual(s.get_node(step).role, "human")
        self.assertIn("BLOCKED:", s.get_node(step).notes or "")

    def test_real_session_activity_resets_the_no_work_streak(self):
        spin_port = FakeSpinPort()
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")

        for i in range(2):
            s.update_state(step, "in_progress")
            spawnid = "dead-no-work-%d" % i
            s.assign(step, spawnid)
            log = "/l/%s.log" % spawnid
            workers = FakeWorkers(
                workers=[{"spawnid": spawnid, "pid": i + 1, "step": step, "started": 0, "log": log}]
            )
            fs = FakeFs(files={log: _NO_WORK_LOG})
            make_sweep(s, workers, fs=fs, spin_port=spin_port, spin_cap=3, stream=ClaudeStreamAdapter()).execute(
                now=1000 + i, max_boot=120, stall_seconds=1800
            )

        s.update_state(step, "in_progress")
        s.assign(step, "dead-real-activity")
        log = "/l/dead-real-activity.log"
        workers = FakeWorkers(
            workers=[{"spawnid": "dead-real-activity", "pid": 50, "step": step, "started": 0, "log": log}]
        )
        fs = FakeFs(files={log: _REAL_ACTIVITY_LOG})
        result = make_sweep(s, workers, fs=fs, spin_port=spin_port, spin_cap=3, stream=ClaudeStreamAdapter()).execute(
            now=2000, max_boot=120, stall_seconds=1800
        )
        self.assertIn(step, result.swept)
        self.assertEqual(result.parked, [])

        for i in range(2):
            s.update_state(step, "in_progress")
            spawnid = "dead-after-reset-%d" % i
            s.assign(step, spawnid)
            log = "/l/%s.log" % spawnid
            workers = FakeWorkers(
                workers=[{"spawnid": spawnid, "pid": 60 + i, "step": step, "started": 0, "log": log}]
            )
            fs = FakeFs(files={log: _NO_WORK_LOG})
            result = make_sweep(s, workers, fs=fs, spin_port=spin_port, spin_cap=3, stream=ClaudeStreamAdapter()).execute(
                now=3000 + i, max_boot=120, stall_seconds=1800
            )
        self.assertEqual(result.parked, [], "streak should not yet have reached the cap again")

    def test_no_dead_worker_record_reclaims_normally_and_leaves_spin_state_untouched(self):
        spin_port = FakeSpinPort()
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        result = make_sweep(s, workers, spin_port=spin_port, spin_cap=3).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )
        self.assertIn(step, result.swept)
        self.assertEqual(result.parked, [])
        self.assertEqual(spin_port.load(), SpinLedger())

    def test_a_stalled_alive_reclaim_never_touches_the_spin_state(self):
        spin_port = FakeSpinPort()
        s = FakeStore()
        step = create_owned_step(s, "t", step="build", role="agent")
        s.update_state(step, "in_progress")
        s.assign(step, "stalled-sp")
        workers = FakeWorkers(
            workers=[
                {"spawnid": "stalled-sp", "pid": 999, "step": step, "started": 100, "log": "/l/1.log"}
            ],
            alive_pids={999},
        )
        fs = FakeFs(log_mtimes={"/l/1.log": 1000 - 1800 - 1})
        result = make_sweep(s, workers, fs=fs, spin_port=spin_port, spin_cap=3, stream=ClaudeStreamAdapter()).execute(
            now=1000, max_boot=120, stall_seconds=1800
        )
        self.assertIn(step, result.swept)
        self.assertEqual(result.parked, [])
        self.assertEqual(spin_port.load(), SpinLedger())


class TestTick(unittest.TestCase):
    def test_reaps_dead_children_before_probing_liveness(self):
        s = FakeStore()
        workers = FakeWorkers(workers=[{"spawnid": "sp-1", "pid": 1, "started": 0}], alive_pids={1})
        make_tick(s, workers, FakeSpawner(), FakeConfig(max_agents=4)).execute(
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
        create_owned_step(s, "b1", step="build", role="agent")
        create_owned_step(s, "b2", step="build", role="agent")
        spawner = FakeSpawner()
        result = make_tick(s, FakeWorkers(), spawner, FakeConfig(max_agents=4)).execute(
            TickInput(now=1000.0)
        )
        self.assertEqual(spawner.spawned, ["agent", "agent"])
        self.assertEqual(spawner.spawned, result.spawned)
        self.assertLessEqual(len(spawner.spawned), 4)

    def test_no_spawn_when_no_slots(self):
        s = FakeStore()
        create_owned_step(s, "b1", step="build", role="agent")
        spawner = FakeSpawner()
        result = make_tick(s, FakeWorkers(), spawner, FakeConfig(max_agents=0)).execute(
            TickInput(now=1000.0)
        )
        self.assertEqual(spawner.spawned, [])
        self.assertEqual(result.spawned, [])
        self.assertEqual(result.pool.free_slots, 0)

    def test_breaker_open_pre_reset_spawns_nothing(self):
        s = FakeStore()
        create_owned_step(s, "b1", step="build", role="agent")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker().trip(2000.0))
        result = make_tick(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(spawner.spawned, [])
        self.assertTrue(result.breaker.open)
        self.assertEqual(result.breaker.reset_at, 2000.0)
        self.assertEqual(result.pool.free_slots, 0)

    def test_free_slots_reflects_available_capacity(self):
        result = make_tick(
            FakeStore(), FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4)
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.pool.free_slots, 4)

    def test_free_slots_positive_when_ready_role_already_has_an_inflight_worker(self):
        s = FakeStore()
        create_owned_step(s, "b1", step="build", role="agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "boot", "role": "agent", "pid": 1, "step": None, "started": 1000.0}],
            alive_pids={1},
        )
        result = make_tick(
            s, workers, FakeSpawner(), FakeConfig(max_agents=4)
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.spawned, [])
        self.assertEqual(result.pool.free_slots, 3)

    def test_no_spawn_when_the_registry_is_unreadable(self):
        s = FakeStore()
        create_owned_step(s, "b1", step="build", role="agent")
        spawner = FakeSpawner()
        workers = FakeWorkers(raise_workers_state=True)
        backup_gate = FakeBackupGate(
            BackupResponse(created="store-1000.db.gz", pruned=["store-1.db.gz"])
        )
        result = make_tick(
            s, workers, spawner, FakeConfig(max_agents=4), backup_gate=backup_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.spawned, [])
        self.assertEqual(spawner.spawned, [])
        self.assertEqual(result.pool.free_slots, 0)
        self.assertEqual(result.backup.created, "store-1000.db.gz")
        self.assertEqual(result.backup.pruned, ["store-1.db.gz"])

    def test_breaker_half_open_spawns_exactly_one_probe(self):
        s = FakeStore()
        create_owned_step(s, "b1", step="build", role="agent")
        create_owned_step(s, "b2", step="build", role="agent")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker().trip(1000.0))
        make_tick(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(len(spawner.spawned), 1)

    def test_breaker_closed_spawns_normally(self):
        s = FakeStore()
        create_owned_step(s, "b1", step="build", role="agent")
        create_owned_step(s, "b2", step="build", role="agent")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker())
        result = make_tick(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(len(spawner.spawned), 2)
        self.assertFalse(result.breaker.open)

    def test_spin_open_caps_slots_at_one_even_with_more_free_slots(self):
        s = FakeStore()
        create_owned_step(s, "b1", step="build", role="agent")
        create_owned_step(s, "b2", step="build", role="agent")
        create_owned_step(s, "b3", step="build", role="agent")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker(), spin_open=True)
        result = make_tick(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertLessEqual(len(spawner.spawned), 1)
        self.assertTrue(result.breaker.spin_open)

    def test_spin_closed_does_not_limit_slots(self):
        s = FakeStore()
        create_owned_step(s, "b1", step="build", role="agent")
        create_owned_step(s, "b2", step="build", role="agent")
        spawner = FakeSpawner()
        breaker_gate = FakeBreakerGate(Breaker(), spin_open=False)
        result = make_tick(
            s, FakeWorkers(), spawner, FakeConfig(max_agents=4), breaker_gate=breaker_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(len(spawner.spawned), 2)
        self.assertFalse(result.breaker.spin_open)

    def test_hook_completions_surfaced_generically(self):
        s = FakeStore()
        flow_svc = FlowService(
            FakeFs({"auditor": {"model": "sonnet", "step": "audit", "on_deploy_green": True}}), s
        )
        tid = s.create_step("audit: release", step="audit", role="agent",
                            parent=s.create_item("i", "a description", workflow="wf"))
        s.note(tid, "no finding")
        s.complete_node(tid, "done")
        s._records[tid]["closed_at"] = "2026-01-01T12:00:00"
        result = make_tick(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4),
            hook_completions=HookCompletionsUseCase(s, flow_svc),
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.hooks.completed, [("audit", tid, "no finding")])

    def test_flow_service_cache_cleared_each_tick_picks_up_bundle_edited_in_place(self):
        s = FakeStore()
        fs = FakeFs({"auditor": {"model": "sonnet", "step": "audit", "on_deploy_green": True}})
        flow_svc = FlowService(fs, s)
        tid = s.create_step("audit: release", step="audit", role="agent",
                            parent=s.create_item("i", "a description", workflow="wf"))
        s.note(tid, "no finding")
        s.complete_node(tid, "done")
        s._records[tid]["closed_at"] = "2026-01-01T12:00:00"
        tick = make_tick(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4),
            hook_completions=HookCompletionsUseCase(s, flow_svc),
            flow_service=flow_svc,
        )

        first = tick.execute(TickInput(now=1000.0))
        self.assertEqual(first.hooks.completed, [("audit", tid, "no finding")])

        fs._metas["auditor"] = {"model": "sonnet", "step": "audit"}
        second = tick.execute(TickInput(now=1000.0))

        self.assertEqual(second.hooks.completed, [])
        self.assertEqual(len(fs.workflow_text_calls), 2)

    def test_no_hook_completions_use_case_yields_empty(self):
        s = FakeStore()
        result = make_tick(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4)
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.hooks.completed, [])

    def test_backup_gate_wired_in_populates_backed_up_and_pruned(self):
        s = FakeStore()
        backup_gate = FakeBackupGate(
            BackupResponse(created="store-1000.db.gz", pruned=["store-1.db.gz"])
        )
        result = make_tick(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4), backup_gate=backup_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.backup.created, "store-1000.db.gz")
        self.assertEqual(result.backup.pruned, ["store-1.db.gz"])

    def test_no_backup_gate_leaves_defaults(self):
        s = FakeStore()
        result = make_tick(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4)
        ).execute(TickInput(now=1000.0))
        self.assertIsNone(result.backup.created)
        self.assertEqual(result.backup.pruned, [])

    def test_usage_gate_wired_in_is_called_with_now(self):
        s = FakeStore()
        usage_gate = FakeUsageGate()
        make_tick(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4), usage_gate=usage_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(usage_gate.calls, [1000.0])

    def test_no_usage_gate_is_a_noop(self):
        s = FakeStore()
        result = make_tick(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4)
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.pool.alive, 0)

    def test_active_seconds_credited_for_covered_step_under_the_cap(self):
        s = FakeStore()
        tid = create_owned_step(s, "b1", step="build", role="agent")
        s.claim_ready("agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "role": "agent", "pid": 1, "step": tid,
                      "started": 900.0}],
            alive_pids={1},
        )
        make_tick(s, workers, FakeSpawner(), FakeConfig(max_agents=4)).execute(
            TickInput(now=1005.0, since=1000.0)
        )
        self.assertEqual(s.get_node(tid).active_seconds, 5.0)

    def test_active_seconds_capped_on_a_large_gap(self):
        s = FakeStore()
        tid = create_owned_step(s, "b1", step="build", role="agent")
        s.claim_ready("agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "role": "agent", "pid": 1, "step": tid,
                      "started": 500.0}],
            alive_pids={1},
        )
        make_tick(s, workers, FakeSpawner(), FakeConfig(max_agents=4)).execute(
            TickInput(now=1000.0, since=600.0)
        )
        self.assertEqual(s.get_node(tid).active_seconds, 15.0)

    def test_active_seconds_credits_every_covered_step_the_same_delta(self):
        s = FakeStore()
        tid_a = create_owned_step(s, "b1", step="build", role="agent")
        tid_b = create_owned_step(s, "b2", step="build", role="agent")
        s.claim_ready("agent")
        s.claim_ready("agent")
        workers = FakeWorkers(
            workers=[
                {"spawnid": "sp-1", "role": "agent", "pid": 1, "step": tid_a, "started": 900.0},
                {"spawnid": "sp-2", "role": "agent", "pid": 2, "step": tid_b, "started": 900.0},
            ],
            alive_pids={1, 2},
        )
        make_tick(s, workers, FakeSpawner(), FakeConfig(max_agents=4)).execute(
            TickInput(now=1005.0, since=1000.0)
        )
        self.assertEqual(s.get_node(tid_a).active_seconds, 5.0)
        self.assertEqual(s.get_node(tid_b).active_seconds, 5.0)

    def test_active_seconds_stays_none_without_a_live_worker(self):
        s = FakeStore()
        tid = create_owned_step(s, "b1", step="build", role="agent")
        s.claim_ready("agent")
        make_tick(s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4)).execute(
            TickInput(now=1005.0, since=1000.0)
        )
        self.assertIsNone(s.get_node(tid).active_seconds)

    def test_active_seconds_untouched_when_since_is_none(self):
        s = FakeStore()
        tid = create_owned_step(s, "b1", step="build", role="agent")
        s.claim_ready("agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "role": "agent", "pid": 1, "step": tid,
                      "started": 900.0}],
            alive_pids={1},
        )
        make_tick(s, workers, FakeSpawner(), FakeConfig(max_agents=4)).execute(
            TickInput(now=1005.0)
        )
        self.assertIsNone(s.get_node(tid).active_seconds)

    def test_active_seconds_not_credited_when_delta_is_not_positive(self):
        s = FakeStore()
        tid = create_owned_step(s, "b1", step="build", role="agent")
        s.claim_ready("agent")
        workers = FakeWorkers(
            workers=[{"spawnid": "sp-1", "role": "agent", "pid": 1, "step": tid,
                      "started": 900.0}],
            alive_pids={1},
        )
        make_tick(s, workers, FakeSpawner(), FakeConfig(max_agents=4)).execute(
            TickInput(now=1000.0, since=1000.0)
        )
        self.assertIsNone(s.get_node(tid).active_seconds)

    def test_cadence_gate_wired_in_surfaces_fired_audits(self):
        s = FakeStore()
        cadence_gate = FakeCadenceGate(fired=["audit.1"])
        result = make_tick(
            s, FakeWorkers(), FakeSpawner(), FakeConfig(max_agents=4), cadence_gate=cadence_gate
        ).execute(TickInput(now=1000.0))
        self.assertEqual(result.cadence.fired, ["audit.1"])

    def test_lc_start_tick_loop_surfaces_preserved_uncommitted_work_on_reclaim(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkers()
        worktrees = FakeWorktrees(paths={item: "/worktrees/%s" % item})
        git = FakeCaptureGit(dirty={"/worktrees/%s" % item})

        result = make_tick(
            s, workers, FakeSpawner(), FakeConfig(max_agents=4), worktrees=worktrees, git=git,
        ).execute(TickInput(now=1000.0))

        self.assertEqual(result.sweep.preserved, [step])
        lines = _tick_event_lines(result, "12:00:00")
        self.assertTrue(any("preserve" in l and step in l for l in lines))


if __name__ == "__main__":
    unittest.main()
