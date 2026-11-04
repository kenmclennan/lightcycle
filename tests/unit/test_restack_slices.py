import unittest

from lightcycle.application.services.worktree import (
    STACK_BASE,
    STACK_BRANCH_RETAINED_LABEL,
    WorktreeService,
)
from lightcycle.application.work.stack_runs import STACK_RETARGETED, StackRuns
from lightcycle.adapters.scaffold import ScaffoldAdapter
from tests.support.fake_fs import FakeFs
from tests.support.restack_world import GATE, REPO, RestackWorld
from tests.unit.test_stacking import _Cfg


def _bases(world, item):
    return {a.label: a.value for a in world.store.item_artifacts(item) if a.type == STACK_BASE}


class TestSettledIsEvaluatedPerSlice(unittest.TestCase):
    def test_a_step_of_another_slice_does_not_unsettle_a_node(self):
        world = RestackWorld()
        slices = world.add_slices("x", plain=(3,))
        world.set_head("x-s1", "moved")

        world.use_case().execute()

        self.assertEqual(len([c for c in world.git.calls if c[0] == "restack"]), 1)
        self.assertNotIn("deferred", world.store.get_node(slices[2]["step"]).notes or "")

    def test_two_open_steps_of_the_nodes_own_slice_unsettle_it(self):
        world = RestackWorld()
        slices = world.add_slices("x", count=2)
        world.store.create_step(stage=GATE, role="agent", item=slices[2]["item"], slice=2)
        world.set_head("x-s1", "moved")

        out = world.use_case().execute()

        self.assertEqual(out.deferred, [slices[2]["item"]])
        self.assertFalse([c for c in world.git.calls if c[0] == "restack"])


class TestStackBaseLabels(unittest.TestCase):
    def test_slice_runs_hold_distinct_labelled_bases_and_slice_zero_stays_unlabelled(self):
        world = RestackWorld()
        slices = world.add_slices("x")
        item = slices[1]["item"]
        self.assertEqual(
            _bases(world, item), {slices[2]["run"]: "x-s1-tip", slices[3]["run"]: "x-s2-tip"})
        world.set_head("x-s1", "moved")

        world.use_case().execute()

        bases = _bases(world, item)
        self.assertEqual(bases[slices[2]["run"]], "moved")
        self.assertTrue(bases[slices[3]["run"]].startswith("restacked-"))
        self.assertNotIn(None, bases)

    def test_slice_zero_nodes_write_the_unlabelled_base(self):
        world = RestackWorld()
        world.add_node("parent", commits=["m1", "p1"])
        world.history["old"] = ["m1", "p1"]
        child = world.add_node("child", parent="parent", commits=["m1", "p1", "c"], stack_base="old")
        world.set_head("parent", "new")

        world.use_case().execute()

        self.assertEqual(_bases(world, child["item"]), {None: "new"})


class TestRunOfNewestSlice(unittest.TestCase):
    def test_run_of_a_three_slice_item_is_the_top_slice(self):
        world = RestackWorld()
        slices = world.add_slices("x")
        world.use_case()

        run = StackRuns(world.store, world.flow).run_of(slices[1]["item"])

        self.assertEqual(run.id, slices[3]["run"])


class TestRetention(unittest.TestCase):
    def _world(self):
        world = RestackWorld()
        self.slices = world.add_slices("x", count=2)
        self.item = self.slices[1]["item"]
        world.store.add_project("acme/app", local_path=REPO)
        world.store.replace_artifact(self.item, "repo", "app")
        world.build()
        self.svc = WorktreeService(
            world.store, world.git, FakeFs(), _Cfg(), flow=world.flow, scaffold=ScaffoldAdapter())
        return world

    def _run(self, world, n):
        return world.store.get_run(self.slices[n]["run"])

    def test_a_merged_slice_with_an_unretargeted_slice_above_keeps_its_branch(self):
        world = self._world()
        world.store.close_run(self.slices[1]["run"], "merged")

        self.svc.release_run(self._run(world, 1))

        self.assertEqual(world.git.remote_deletes, [])
        self.assertIn(STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(self.item))

    def test_the_marker_a_missing_slice_above_or_an_unmerged_slice_delete_it(self):
        world = self._world()
        world.store.close_run(self.slices[1]["run"], "merged")
        world.store.replace_artifact(
            self.item, STACK_RETARGETED, "1", label=self.slices[2]["run"], internal=True)

        self.svc.release_run(self._run(world, 1))

        self.assertEqual(world.git.remote_deletes, [(REPO, self.slices[1]["branch"])])

    def test_a_slice_that_is_not_merged_is_deleted(self):
        world = self._world()
        world.store.close_run(self.slices[1]["run"], "abandoned")

        self.svc.release_run(self._run(world, 1))

        self.assertEqual(world.git.remote_deletes, [(REPO, self.slices[1]["branch"])])

    def test_the_sweep_deletes_after_the_marker_and_clears_the_label(self):
        world = self._world()
        world.store.close_run(self.slices[1]["run"], "merged")
        world.store.label_add(self.item, STACK_BRANCH_RETAINED_LABEL)
        uc = world.use_case()

        uc.execute()
        self.assertEqual(world.git.remote_deletes, [])
        self.assertIn(STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(self.item))

        world.store.replace_artifact(
            self.item, STACK_RETARGETED, "1", label=self.slices[2]["run"], internal=True)
        uc.execute()

        self.assertEqual(world.git.remote_deletes, [(REPO, self.slices[1]["branch"])])
        self.assertNotIn(STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(self.item))

    def test_a_failed_delete_keeps_the_label(self):
        world = RestackWorld(remote_delete_fails=True)
        slices = world.add_slices("x", count=2)
        world.store.close_run(slices[1]["run"], "merged")
        world.store.label_add(slices[1]["item"], STACK_BRANCH_RETAINED_LABEL)
        world.store.replace_artifact(
            slices[1]["item"], STACK_RETARGETED, "1", label=slices[2]["run"], internal=True)

        world.use_case().execute()

        self.assertIn(STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(slices[1]["item"]))

    def test_a_branch_gone_from_origin_does_not_hold_the_label(self):
        world = RestackWorld()
        slices = world.add_slices("x", count=2)
        world.store.close_run(slices[1]["run"], "merged")
        world.store.label_add(slices[1]["item"], STACK_BRANCH_RETAINED_LABEL)
        world.store.replace_artifact(
            slices[1]["item"], STACK_RETARGETED, "1", label=slices[2]["run"], internal=True)
        world.remote_branches.discard((REPO, slices[1]["branch"]))

        world.use_case().execute()

        self.assertEqual(world.git.remote_deletes, [])
        self.assertNotIn(STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(slices[1]["item"]))

    def test_two_merged_runs_delete_only_the_one_no_slice_depends_on(self):
        world = RestackWorld()
        slices = world.add_slices("x", count=3, bases={3: 1})
        world.store.close_run(slices[1]["run"], "merged")
        world.store.close_run(slices[2]["run"], "merged")
        world.store.label_add(slices[1]["item"], STACK_BRANCH_RETAINED_LABEL)

        world.use_case().execute()

        self.assertEqual(world.git.remote_deletes, [(REPO, slices[2]["branch"])])
        self.assertIn(STACK_BRANCH_RETAINED_LABEL, world.store.labels_of(slices[1]["item"]))


if __name__ == "__main__":
    unittest.main()
