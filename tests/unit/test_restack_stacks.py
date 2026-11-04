import os
import shutil
import tempfile
import unittest

from lightcycle.adapters.scaffold import ScaffoldAdapter
from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool.detect_head_moved import PR_HEAD_SHA, DetectHeadMovedUseCase
from lightcycle.application.pool.pr_sync_reads import PrSyncReads
from lightcycle.application.services.worktree import (
    STACK_BRANCH_RETAINED_LABEL,
    WorktreeService,
)
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.support.restack_world import RestackWorld
from tests.support.fake_workers import FakeWorkers
from tests.unit.test_pool import FakeSpawner, make_tick
from tests.unit.test_tick_github_poll import _Config
from tests.unit.test_tick_lifecycle_gate import _Reload
from lightcycle.application.pool.no_op_gates import NoOpMonitor
from lightcycle.application.pool.tick import TickInput
from tests.unit.test_stacking import PARENT_BRANCH, _activate, _Cfg, _flow, _item, _parent


def _pushed_world():
    world = RestackWorld()
    world.add_node("parent", commits=["m1", "p1"])
    world.history["p-old-head"] = ["m1", "p1"]
    world.add_node("child", parent="parent", commits=["m1", "p1", "c1"], stack_base="p-old-head")
    world.set_head("parent", "p-new-head")
    return world


def _restacks(world):
    return [c for c in world.git.calls if c[0] == "restack"]


class TestRestackFallbackAndFailures(unittest.TestCase):
    def test_a_child_with_no_stack_base_derives_it_from_the_merge_base(self):
        world = RestackWorld()
        world.add_node("parent", commits=["m1", "p1"])
        world.add_node("child", parent="parent", commits=["m1", "p1", "c1"])
        world.merge_bases[("origin/feat/child", "origin/feat/parent")] = "derived-base"
        world.set_head("parent", "p-new-head")

        world.use_case().execute()

        self.assertEqual(_restacks(world)[0][2][0].old_base, "derived-base")

    def test_a_merged_parent_without_a_stack_base_uses_the_parents_pr_head(self):
        world = RestackWorld()
        world.add_node("parent", commits=["m1", "p1"])
        world.add_node("child", parent="parent", commits=["m1", "p1", "c1"])
        world.merge("parent")
        world.merge_bases[("origin/feat/child", "parent-head")] = "derived-base"
        world.set_head("parent", "parent-head")
        world.github._head_shas[world.nodes["parent"]["pr"]] = "parent-head"

        world.use_case().execute()

        self.assertEqual(_restacks(world)[0][2][0].old_base, "derived-base")

    def test_an_underivable_base_defers_instead_of_guessing(self):
        world = RestackWorld()
        world.add_node("parent", commits=["m1"])
        world.add_node("child", parent="parent", commits=["m1", "c1"])
        world.set_head("parent", "p-new-head")

        world.use_case().execute()

        self.assertEqual(_restacks(world), [])

    def test_a_failed_base_edit_defers_with_nothing_moved(self):
        world = RestackWorld()
        world.add_node("parent", commits=["m1", "p1"])
        world.add_node("child", parent="parent", commits=["m1", "p1", "c1"],
                       stack_base="p-old-head")
        world.merge("parent")
        world.github._failing_calls.add("set_pr_base")

        world.use_case().execute()

        self.assertEqual(_restacks(world), [])
        self.assertEqual(
            world.store.get_item(world.item("child")).stacks_on, world.item("parent"))
        notes = world.store.get_node(world.step("child")).notes or ""
        self.assertIn("could not retarget", notes)

    def test_a_deferral_note_is_written_once_across_ticks(self):
        world = _pushed_world()
        world.dirty.add("/repo/.worktrees/%s" % world.item("child"))
        use_case = world.use_case()

        use_case.execute()
        first = world.store.get_node(world.step("child")).notes
        use_case.execute()

        self.assertEqual(world.store.get_node(world.step("child")).notes, first)

    def test_an_unreadable_worktree_defers(self):
        world = _pushed_world()
        world.git_kwargs["raises"] = {"has_uncommitted"}

        world.use_case().execute()

        self.assertEqual(_restacks(world), [])

    def test_a_deferred_child_settles_on_a_later_tick(self):
        world = _pushed_world()
        path = "/repo/.worktrees/%s" % world.item("child")
        world.dirty.add(path)
        use_case = world.use_case()

        use_case.execute()
        self.assertEqual(_restacks(world), [])
        world.git.dirty.discard(path)
        use_case.execute()

        self.assertEqual(len(_restacks(world)), 1)

    def test_a_lease_failure_is_retried_and_the_park_clears_on_success(self):
        world = _pushed_world()
        branch = world.nodes["child"]["branch"]
        world.remote_tips[branch] = "someone-else"
        use_case = world.use_case()

        use_case.execute()
        parked = world.store.get_node(world.step("child")).park
        self.assertIn("restack of feat/child not applied", parked.reason)
        world.git.remote_tips[branch] = "child-tip"
        use_case.execute()

        self.assertFalse(world.store.get_node(world.step("child")).park.reason)
        self.assertEqual(len(_restacks(world)), 2)

    def test_a_pushed_restack_moves_the_head_and_the_gate_closes_head_moved(self):
        world = _pushed_world()
        pr = world.nodes["child"]["pr"]
        world.store.add_artifact(world.step("child"), PR_HEAD_SHA, "child-tip", internal=True)

        world.use_case().execute()
        world.github._head_shas[pr] = world.git.remote_tips[world.nodes["child"]["branch"]]
        complete = CompleteStepUseCase(world.store, world.flow)
        detected = DetectHeadMovedUseCase(world.store, world.flow, complete).execute(
            PrSyncReads(world.github))

        self.assertIn(world.item("child"), detected.head_moved)
        self.assertEqual(world.store.get_node(world.step("child")).outcome, "head-moved")

    def test_a_pushed_restack_records_the_new_stack_base(self):
        world = _pushed_world()

        world.use_case().execute()

        values = [
            a.value for a in world.store.item_artifacts(world.item("child"))
            if a.type == "stack-base"
        ]
        self.assertEqual(values[-1], "p-new-head")

    def test_a_child_with_no_branch_is_only_unstacked_when_the_parent_merges(self):
        world = RestackWorld()
        world.add_node("parent", commits=["m1", "p1"])
        child = world.store.create_item("late", "d")
        world.store.set_stacks_on(child, world.item("parent"))
        world.merge("parent")

        world.use_case().execute()

        self.assertIsNone(world.store.get_item(child).stacks_on)


class TestRetainedBranchSweep(unittest.TestCase):
    def _world(self, **git_kwargs):
        world = RestackWorld(**git_kwargs)
        world.add_node("parent", commits=["m1", "p1"], gate=None)
        world.store.label_add(world.item("parent"), STACK_BRANCH_RETAINED_LABEL)
        world.store.complete_node(world.item("parent"), "done")
        return world

    def test_the_branch_is_deleted_and_the_label_removed_once_no_child_targets_it(self):
        world = self._world()

        world.use_case().execute()

        self.assertEqual(world.git.remote_deletes, [("/repo", "feat/parent")])
        self.assertNotIn(
            STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(world.item("parent")))

    def test_a_failed_delete_keeps_the_label_for_the_next_tick(self):
        world = self._world(remote_delete_fails=True)

        world.use_case().execute()

        self.assertIn(STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(world.item("parent")))

    def test_a_branch_a_child_still_targets_is_kept(self):
        world = self._world()
        world.add_node("child", parent="parent", commits=["m1", "c1"], stack_base="x")

        world.use_case().execute()

        self.assertEqual(world.git.remote_deletes, [])
        self.assertIn(STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(world.item("parent")))


class TestReleaseRetainsTheBranchForChildren(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.flow = _flow(self.store)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.repo = os.path.join(self.root, "app")
        os.makedirs(self.repo)
        self.store.add_project("acme/app", local_path=self.repo)
        self.git = FakeGit(repos={self.repo}, base="origin/main")
        self.svc = WorktreeService(
            self.store, self.git, FakeFs(), _Cfg(), flow=self.flow, scaffold=ScaffoldAdapter())
        self.parent = _parent(self.store)
        self.store.replace_artifact(self.parent, "repo", "app")
        self.run = self.store.current_run(self.parent, "code")

    def _child(self):
        child = _item(self.store, "child story", repo="app", workflow=None)
        _activate(self.store, self.flow, child, self.parent)
        return child

    def test_a_non_done_child_keeps_the_remote_branch_and_labels_the_parent(self):
        self._child()

        self.svc.release_run(self.run)

        self.assertEqual(self.git.remote_deletes, [])
        self.assertIn(STACK_BRANCH_RETAINED_LABEL, self.store.labels_of(self.parent))
        self.assertIn(
            ("delete_branch", self.repo, PARENT_BRANCH), self.git.calls)

    def test_no_child_deletes_the_remote_branch(self):
        self.svc.release_run(self.run)

        self.assertEqual(self.git.remote_deletes, [(self.repo, PARENT_BRANCH)])
        self.assertNotIn(STACK_BRANCH_RETAINED_LABEL, self.store.labels_of(self.parent))

    def test_a_done_child_does_not_keep_the_branch(self):
        child = self._child()
        self.store.complete_node(child, "done")

        self.svc.release_run(self.run)

        self.assertEqual(self.git.remote_deletes, [(self.repo, PARENT_BRANCH)])


class _Order:
    def __init__(self, events, name):
        self._events = events
        self._name = name

    def execute(self):
        self._events.append(self._name)
        return NoOpMonitor().execute()


class TestTickRunsTheRestackGate(unittest.TestCase):
    def test_every_tick_runs_the_gate_before_the_monitor(self):
        events = []
        tick = make_tick(
            FakeStore(), FakeWorkers(), FakeSpawner(), _Config(),
            monitor=_Order(events, "monitor"), restack=_Order(events, "restack"),
            config_reload=_Reload("unchanged"))

        tick.execute(TickInput(now=100.0))

        self.assertEqual(events, ["restack", "monitor"])
