import contextlib
import io
import os
import unittest

from lightcycle.application.pool.monitor_prs import MonitorPrsResponse
from lightcycle.application.pool.release_interrupted_runs import (
    ReleaseInterruptedRunsResponse,
    ReleaseInterruptedRunsUseCase,
)
from lightcycle.application.pool.tick import TickInput
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.application.work.close_item import RELEASE_PENDING_LABEL
from lightcycle.domain.work import State
from lightcycle.ports.git import GitReadError
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_pool import FakeSpawner, make_tick
from tests.unit.test_tick_lifecycle_gate import _Config
from tests.unit.test_worktree_service import _Cfg, _FakeFlow, plant_run

PROJECTS = "/projects"
TARGET = os.path.join(PROJECTS, "app")
BRANCH = "feat/app-code-login"


class _Scaffold:
    def is_dir(self, path):
        return True

    def make_dir(self, path):
        return None


class _Fixture:
    def __init__(self, git=None, step_state=State.QUEUED, run_state="merged"):
        self.store = FakeStore()
        self.item = self.store.create_item("Login", "a description")
        self.store.add_project("acme/app", local_path=TARGET)
        self.store.add_artifact(self.item, "repo", "app")
        role = "human" if step_state == State.WAITING else "agent"
        self.step = self.store.create_step(stage="cleanup", role=role, item=self.item)
        self.run_id = plant_run(self.store, self.item, "code", BRANCH, state=run_state)
        self.run = self.store.get_run(self.run_id)
        self.git = git or FakeGit(repos={TARGET}, base="origin/main")
        self.worktrees = WorktreeService(
            self.store, self.git, FakeFs(), _Cfg(PROJECTS), flow=_FakeFlow(),
            scaffold=_Scaffold())
        self.path = self.worktrees.path_for_run(self.run)
        self.git._registered.add(self.path)
        self.git._branches.add((TARGET, BRANCH))
        self.use_case = ReleaseInterruptedRunsUseCase(self.store, self.worktrees)

    def removals(self):
        return [c for c in self.git.calls if c[0] == "remove_worktree"]


class TestReleaseInterruptedRuns(unittest.TestCase):
    def test_a_merged_run_with_a_leftover_is_released_and_ensure_makes_a_fresh_worktree(self):
        fx = _Fixture()

        response = fx.use_case.execute()

        self.assertEqual(response.released, [fx.run_id])
        self.assertEqual(response.failed, [])
        kinds = [c[0] for c in fx.git.calls]
        for kind in ("remove_worktree", "delete_branch", "delete_remote_branch"):
            self.assertIn(kind, kinds)
        self.assertFalse(fx.git.worktree_registered(TARGET, fx.path))
        fx.worktrees.ensure(fx.store.get_node(fx.step))
        self.assertIn("add_worktree", [c[0] for c in fx.git.calls])

    def test_an_abandoned_run_is_released_like_a_merged_one(self):
        fx = _Fixture(run_state="abandoned")

        self.assertEqual(fx.use_case.execute().released, [fx.run_id])

    def test_a_repeated_execute_after_a_complete_release_is_a_no_op(self):
        fx = _Fixture()
        fx.use_case.execute()
        before = len(fx.removals())

        again = fx.use_case.execute()
        fresh = ReleaseInterruptedRunsUseCase(fx.store, fx.worktrees).execute()

        self.assertEqual(again, ReleaseInterruptedRunsResponse())
        self.assertEqual(fresh, ReleaseInterruptedRunsResponse())
        self.assertEqual(len(fx.removals()), before)

    def test_a_worktree_registered_again_after_the_first_execute_is_not_released(self):
        fx = _Fixture()
        fx.use_case.execute()
        fx.git._registered.add(fx.path)
        before = len(fx.removals())

        fx.use_case.execute()

        self.assertEqual(len(fx.removals()), before)

    def test_an_open_run_is_never_released(self):
        fx = _Fixture(run_state="open")

        response = fx.use_case.execute()

        self.assertEqual(response, ReleaseInterruptedRunsResponse())
        self.assertEqual(fx.removals(), [])
        self.assertTrue(fx.git.worktree_registered(TARGET, fx.path))

    def test_a_closed_run_is_skipped_when_an_open_run_shares_its_branch(self):
        fx = _Fixture()
        pid = fx.store.open_pass(fx.item)
        open_id = fx.store.open_run(fx.item, pid, "code")
        fx.store.set_branch(open_id, BRANCH)

        response = fx.use_case.execute()

        self.assertEqual(response, ReleaseInterruptedRunsResponse())
        self.assertEqual(fx.removals(), [])

    def test_a_run_whose_item_step_is_waiting_is_not_a_candidate(self):
        fx = _Fixture(step_state=State.WAITING)

        response = fx.use_case.execute()

        self.assertEqual(response, ReleaseInterruptedRunsResponse())
        self.assertEqual(fx.removals(), [])

    def test_a_clean_run_is_in_neither_released_nor_failed(self):
        fx = _Fixture()
        clean = plant_run(fx.store, fx.item, "spec", "spec/login", n=2, state="merged")

        response = fx.use_case.execute()

        self.assertEqual(response.released, [fx.run_id])
        self.assertNotIn(clean, [r for r, _ in response.failed])
        self.assertNotIn(clean, response.released)

    def test_a_failing_git_read_is_reported_and_retried_on_a_later_call(self):
        git = FakeGit(repos={TARGET}, base="origin/main", raises=("worktree_registered",))
        fx = _Fixture(git=git)

        first = fx.use_case.execute()

        self.assertEqual(first.released, [])
        self.assertEqual([r for r, _ in first.failed], [fx.run_id])
        self.assertIn("worktree_registered", first.failed[0][1])
        self.assertEqual(fx.removals(), [])
        git._raises.clear()
        self.assertEqual(fx.use_case.execute().released, [fx.run_id])

    def test_a_failed_removal_keeps_the_marker_and_the_next_scan_retries(self):
        git = FakeGit(repos={TARGET}, base="origin/main", raises=("remove_worktree",))
        fx = _Fixture(git=git)
        fx.store.label_add(fx.item, RELEASE_PENDING_LABEL)
        fx.use_case._pending = []

        first = fx.use_case.execute()

        self.assertEqual([r for r, _ in first.failed], [fx.run_id])
        self.assertIn(RELEASE_PENDING_LABEL, fx.store.labels_of(fx.item))
        self.assertTrue(git.worktree_registered(TARGET, fx.path))
        git._raises.clear()
        again = fx.use_case.execute()
        self.assertEqual(again.released, [fx.run_id])
        self.assertNotIn(RELEASE_PENDING_LABEL, fx.store.labels_of(fx.item))

    def test_a_successful_removal_clears_the_marker(self):
        fx = _Fixture()
        fx.store.label_add(fx.item, RELEASE_PENDING_LABEL)
        fx.use_case._pending = []

        fx.use_case.execute()

        self.assertNotIn(RELEASE_PENDING_LABEL, fx.store.labels_of(fx.item))

    def test_a_partial_failure_is_finished_by_the_next_scan(self):
        class FlakyDelete(FakeGit):
            failures = 1

            def delete_branch(self, root, branch):
                if self.failures:
                    self.failures -= 1
                    raise GitReadError("branch busy")
                super().delete_branch(root, branch)

        git = FlakyDelete(repos={TARGET}, base="origin/main")
        fx = _Fixture(git=git)
        fx.store.label_add(fx.item, RELEASE_PENDING_LABEL)
        fx.use_case._pending = []

        first = fx.use_case.execute()

        self.assertEqual([r for r, _ in first.failed], [fx.run_id])
        self.assertIn(RELEASE_PENDING_LABEL, fx.store.labels_of(fx.item))
        self.assertFalse(git.worktree_registered(TARGET, fx.path))
        fx.use_case.execute()
        self.assertFalse(git.branch_exists(TARGET, BRANCH))
        self.assertNotIn(RELEASE_PENDING_LABEL, fx.store.labels_of(fx.item))


class _RecordingGate:
    def __init__(self, events, failed=()):
        self._events = events
        self._failed = list(failed)

    def execute(self):
        self._events.append("release")
        return ReleaseInterruptedRunsResponse(failed=self._failed)


class _RecordingMonitor:
    def __init__(self, events):
        self._events = events

    def execute(self):
        self._events.append("monitor")
        return MonitorPrsResponse(merged=[])


class TestTickReleaseGate(unittest.TestCase):
    def _tick(self, gate, monitor=None):
        overrides = dict(release_gate=gate)
        if monitor is not None:
            overrides["monitor"] = monitor
        return make_tick(FakeStore(), FakeWorkers(), FakeSpawner(), _Config(), **overrides)

    def test_the_gate_runs_once_per_tick_before_the_monitor(self):
        events = []
        tick = self._tick(_RecordingGate(events), _RecordingMonitor(events))

        tick.execute(TickInput(now=1.0))

        self.assertEqual(events, ["release", "monitor"])

    def test_a_failure_is_surfaced_on_the_response_and_warned_on_stderr(self):
        gate = _RecordingGate([], failed=[("APP-1.p1.code", "boom")])
        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            response = self._tick(gate).execute(TickInput(now=1.0))

        self.assertEqual(response.released.failed, [("APP-1.p1.code", "boom")])
        self.assertIn(
            "warning: interrupted-run release failed for APP-1.p1.code: boom", err.getvalue())


class TestPhaseLessRounds(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item("Nightly", "a description")
        self.store.add_project("acme/app", local_path=TARGET)
        self.store.add_artifact(self.item, "repo", "app")
        self.store.create_step(stage="run", role="agent", item=self.item)
        self.git = FakeGit(repos={TARGET}, base="origin/main")
        self.worktrees = WorktreeService(
            self.store, self.git, FakeFs(), _Cfg(PROJECTS), flow=_FakeFlow(),
            scaffold=_Scaffold())
        self.first = self.store.get_run(plant_run(self.store, self.item, None, "auto/one"))

    def test_round_one_of_a_phase_less_run_keeps_the_item_only_path(self):
        self.assertEqual(self.first.round, 1)
        self.assertEqual(
            self.worktrees.path_for_run(self.first),
            os.path.join(TARGET, ".worktrees", self.item))

    def test_a_closed_phase_less_round_is_released_while_a_later_round_is_open(self):
        self.store.close_run(self.first.id, "merged")
        pid = self.store.current_pass(self.item).id
        self.second = self.store.get_run(self.store.open_run(self.item, pid, None))
        self.store.set_branch(self.second.id, "auto/two")
        first = self.store.get_run(self.first.id)
        path = self.worktrees.path_for_run(first)
        self.git._registered.add(path)
        self.git._branches.add((TARGET, "auto/one"))

        response = ReleaseInterruptedRunsUseCase(self.store, self.worktrees).execute()

        self.assertEqual(self.second.round, 2)
        self.assertNotEqual(path, self.worktrees.path_for_run(self.second))
        self.assertEqual(response.released, [self.first.id])
