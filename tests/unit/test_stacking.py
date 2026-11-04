import os
import shutil
import tempfile
import unittest

from lightcycle.adapters.scaffold import ScaffoldAdapter
from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect.doctor import DoctorUseCase
from lightcycle.application.pool.release_stacked_items import ReleaseStackedItemsUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from lightcycle.application.work.inbox import InboxInput, InboxUseCase
from lightcycle.application.work.node_read_surface import node_read_surface
from lightcycle.application.work.return_to_backlog import ReturnToBacklogInput, ReturnToBacklogUseCase
from lightcycle.domain.work.stack_order import order_stacks
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.unit.test_resolve_merged_prs import plant_pr

REPO = "/elsewhere/app"
WORKFLOW = "lightcycle/spec-driven"
PARENT_BRANCH = "feat/parent-code"
PARENT_PR = "https://github.com/o/r/pull/7"

_METAS = {
    "spec-writer": {"model": "sonnet", "step": "spec-writer", "routes": {"done": "write-code"}},
    "coder": {"model": "sonnet", "step": "write-code", "routes": {"done": "open-pr"}},
}

_UNIFIED = (
    "entry: write-code\n\n"
    "nodes:\n"
    "  write-code  coder\n\n"
    "workspace:\n"
    "  spec-writer  specs\n\n"
    "phase:\n"
    "  spec-writer  spec\n"
    "  write-code   code\n\n"
    "edges:\n"
    "  spec-writer  done  write-code\n"
    "  write-code   done  open-pr\n"
)

_SPEC_ONLY = (
    "entry: spec-writer\n\n"
    "nodes:\n"
    "  write-code  coder\n\n"
    "workspace:\n"
    "  spec-writer  specs\n\n"
    "phase:\n"
    "  spec-writer  spec\n\n"
    "edges:\n"
    "  spec-writer  done  open-pr\n"
)


class _Cfg:
    def projects_root(self):
        return "/projects"

    def engine_root(self):
        return "lightcycle"

    def worktree_retries(self):
        return 0

    def worktree_retry_sleep(self):
        return 0

    def branch_prefix(self):
        return "feat"


def _flow(store, workflow=_UNIFIED):
    return FlowService(FakeFs(_METAS, workflow=workflow), store)


def _item(store, title, repo=REPO, workflow=WORKFLOW):
    item = store.create_item(title, "a description", workflow=workflow)
    if repo:
        store.add_artifact(item, "repo", repo)
    return item


def _parent(store, pr=PARENT_PR, spec_pr=None):
    parent = _item(store, "parent story")
    if spec_pr:
        plant_pr(store, parent, spec_pr, phase="spec", branch="feat/parent-spec")
    rid = plant_pr(store, parent, pr, phase="code", branch=PARENT_BRANCH) if pr else None
    if rid is None:
        pid = store.current_pass(parent).id if store.current_pass(parent) else store.open_pass(parent)
        rid = store.open_run(parent, pid, "code")
        store.set_branch(rid, PARENT_BRANCH)
    return parent


def _activate(store, flow, item, parent, step="write-code"):
    return ActivateItemUseCase(store, flow, None, None, ScaffoldAdapter()).execute(
        ActivateItemInput(item=item, workflow=WORKFLOW, step=step, stacks_on=parent)
    )


class TestActivationGate(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.flow = _flow(self.store)

    def test_a_parent_without_a_pr_blocks_the_first_step_on_the_parent(self):
        parent = _parent(self.store, pr=None)
        child = _item(self.store, "child story", workflow=None)

        step = _activate(self.store, self.flow, child, parent).step

        self.assertEqual(self.store.get_node(step).blocked_by, [parent])
        self.assertEqual(self.store.get_item(child).stacks_on, parent)
        self.assertNotIn(step, [s.id for s in self.store.ready_steps()])

    def test_a_parent_that_already_holds_a_pr_leaves_the_first_step_unblocked(self):
        parent = _parent(self.store)
        child = _item(self.store, "child story", workflow=None)

        step = _activate(self.store, self.flow, child, parent).step

        self.assertEqual(self.store.get_node(step).blocked_by, [])
        self.assertIn(step, [s.id for s in self.store.ready_steps()])

    def test_the_parents_spec_phase_pr_does_not_release_the_child(self):
        parent = _parent(self.store, pr=None, spec_pr="https://github.com/o/specs/pull/1")
        child = _item(self.store, "child story", workflow=None)

        step = _activate(self.store, self.flow, child, parent).step

        self.assertEqual(self.store.get_node(step).blocked_by, [parent])


class TestActivationRefusals(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.flow = _flow(self.store)
        self.child = _item(self.store, "child story", workflow=None)

    def _refused(self, parent, flow=None):
        with self.assertRaises(UseCaseError) as caught:
            ActivateItemUseCase(self.store, flow or self.flow, None, None).execute(
                ActivateItemInput(
                    item=self.child, workflow=WORKFLOW, step="write-code", stacks_on=parent)
            )
        self.assertEqual(self.store.get_item(self.child).state, "backlogged")
        self.assertIsNone(self.store.get_item(self.child).workflow)
        self.assertIsNone(self.store.get_item(self.child).stacks_on)
        self.assertEqual(self.store.children(self.child), [])
        return str(caught.exception)

    def test_stacking_on_itself_is_refused(self):
        self.assertIn("cannot stack on itself", self._refused(self.child))

    def test_a_done_parent_is_refused_naming_its_state(self):
        parent = _parent(self.store)
        self.store.complete_node(parent, "done")
        self.assertIn("done", self._refused(parent))

    def test_a_never_activated_parent_is_refused(self):
        parent = _item(self.store, "parent story", workflow=None)
        self.assertIn("activate the parent first", self._refused(parent))

    def test_a_parent_whose_workflow_has_no_project_phase_is_refused(self):
        parent = _parent(self.store)
        flow = _flow(self.store, workflow=_SPEC_ONLY)
        message = self._refused(parent, flow)
        self.assertIn(WORKFLOW, message)
        self.assertIn("no phase in the project repo", message)

    def test_a_parent_in_another_repo_is_refused_naming_both(self):
        parent = _item(self.store, "parent story", repo="/elsewhere/other")
        message = self._refused(parent)
        self.assertIn("/elsewhere/other", message)
        self.assertIn(REPO, message)


class TestReturnToBacklogClearsTheRelation(unittest.TestCase):
    def test_backlogging_clears_stacks_on(self):
        store = FakeStore()
        flow = _flow(store)
        parent = _parent(store, pr=None)
        child = _item(store, "child story", workflow=None)
        _activate(store, flow, child, parent)

        ReturnToBacklogUseCase(store).execute(ReturnToBacklogInput(item=child))

        self.assertIsNone(store.get_item(child).stacks_on)


class TestReleaseSweep(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.flow = _flow(self.store)
        self.sweep = ReleaseStackedItemsUseCase(self.store, self.flow)

    def _stacked(self, pr=None, spec_pr=None):
        parent = _parent(self.store, pr=None, spec_pr=spec_pr)
        child = _item(self.store, "child story", workflow=None)
        step = _activate(self.store, self.flow, child, parent).step
        if pr:
            self.store.set_pr(self.store.current_run(parent, "code").id, pr)
        return parent, child, step

    def test_a_parent_pr_releases_the_step_and_only_that_dependency(self):
        parent, _child, step = self._stacked()
        other = _item(self.store, "other")
        self.store.dep_add(step, other)
        self.store.set_pr(self.store.current_run(parent, "code").id, PARENT_PR)

        self.assertEqual(self.sweep.execute(), [step])

        self.assertEqual(self.store.get_node(step).blocked_by, [other])

    def test_the_sweep_is_idempotent(self):
        parent, _child, step = self._stacked(pr=PARENT_PR)

        self.assertEqual(self.sweep.execute(), [step])
        self.assertEqual(self.sweep.execute(), [])
        self.assertIn(step, [s.id for s in self.store.ready_steps()])

    def test_a_branch_without_a_pr_leaves_the_step_blocked(self):
        _parent_id, _child, step = self._stacked()

        self.assertEqual(self.sweep.execute(), [])
        self.assertEqual(self.store.get_node(step).blocked_by, [_parent_id])

    def test_only_a_spec_phase_pr_leaves_the_step_blocked(self):
        parent, _child, step = self._stacked(spec_pr="https://github.com/o/specs/pull/1")

        self.assertEqual(self.sweep.execute(), [])
        self.assertEqual(self.store.get_node(step).blocked_by, [parent])

    def test_a_depends_gated_item_is_left_alone(self):
        blocker = _parent(self.store)
        gated = _item(self.store, "gated", workflow=None)
        step = ActivateItemUseCase(self.store, self.flow, None, None).execute(
            ActivateItemInput(item=gated, workflow=WORKFLOW, step="write-code", deps=[blocker])
        ).step

        self.assertEqual(self.sweep.execute(), [])
        self.assertEqual(self.store.get_node(step).blocked_by, [blocker])


class TestStackedWorktreeBase(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.flow = _flow(self.store)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.repo = os.path.join(self.root, "app")
        os.makedirs(self.repo)
        self.store.add_project("acme/app", local_path=self.repo)

    def _world(self, remote_branches=(), parent_done=False, pr=PARENT_PR):
        parent = _item(self.store, "parent story", repo="app")
        plant_pr(self.store, parent, pr, phase="code", branch=PARENT_BRANCH) if pr else None
        child = _item(self.store, "child story", repo="app", workflow=None)
        step = _activate(self.store, self.flow, child, parent).step
        self.store.dep_remove(step, parent)
        if parent_done:
            self.store.complete_node(parent, "done")
        git = FakeGit(
            repos={self.repo}, sync_result=True, base="origin/main",
            remote_branches={(self.repo, b) for b in remote_branches},
        )
        svc = WorktreeService(
            self.store, git, FakeFs(), _Cfg(), flow=self.flow, scaffold=ScaffoldAdapter())
        return step, git, svc

    @staticmethod
    def _base_of(git):
        return next(c for c in git.calls if c[0] == "add_worktree")[4]

    def test_the_branch_starts_from_the_parents_branch_head(self):
        step, git, svc = self._world(remote_branches=[PARENT_BRANCH])

        svc.ensure(self.store.get_node(step))

        self.assertIn(("remote_branch_exists", self.repo, PARENT_BRANCH), git.calls)
        self.assertEqual(self._base_of(git), "origin/" + PARENT_BRANCH)

    def test_a_done_parent_whose_branch_is_gone_falls_back_to_the_default_base(self):
        step, git, svc = self._world(parent_done=True)

        svc.ensure(self.store.get_node(step))

        self.assertEqual(self._base_of(git), "origin/main")

    def test_an_open_parent_whose_branch_is_gone_fails_visibly(self):
        step, git, svc = self._world()

        with self.assertRaises(UseCaseError) as caught:
            svc.ensure(self.store.get_node(step))

        self.assertIn("no longer exists on origin", str(caught.exception))
        self.assertNotIn("add_worktree", [c[0] for c in git.calls])

    def test_a_parent_without_a_pr_uses_the_default_base(self):
        step, git, svc = self._world(pr=None)

        svc.ensure(self.store.get_node(step))

        self.assertEqual(self._base_of(git), "origin/main")

    def test_an_item_that_is_not_stacked_uses_the_default_base(self):
        item = _item(self.store, "plain", repo="app", workflow=None)
        step = ActivateItemUseCase(
            self.store, self.flow, None, None, ScaffoldAdapter()
        ).execute(ActivateItemInput(item=item, workflow=WORKFLOW, step="write-code")).step
        git = FakeGit(repos={self.repo}, sync_result=True, base="origin/main")
        svc = WorktreeService(
            self.store, git, FakeFs(), _Cfg(), flow=self.flow, scaffold=ScaffoldAdapter())

        svc.ensure(self.store.get_node(step))

        self.assertEqual(self._base_of(git), "origin/main")
        self.assertNotIn("remote_branch_exists", [c[0] for c in git.calls])


class TestReadSurface(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.flow = _flow(self.store)
        self.parent = _parent(self.store)
        self.child = _item(self.store, "child story", workflow=None)
        self.step = _activate(self.store, self.flow, self.child, self.parent).step

    def _surface(self, node_id):
        return node_read_surface(self.store, self.flow, self.store.node_view(node_id))

    def test_the_step_reports_its_stack(self):
        self.assertEqual(self._surface(self.step)["stack"], {
            "parent": self.parent, "parent_title": "parent story",
            "branch": PARENT_BRANCH, "pr": PARENT_PR,
        })

    def test_the_child_reports_stacks_on_and_the_parent_lists_its_children(self):
        self.assertEqual(self._surface(self.child)["stacks_on"], self.parent)
        self.assertEqual(self._surface(self.parent)["stacked_children"], [self.child])
        self.assertEqual(self._surface(self.child)["stacked_children"], [])

    def test_a_specs_workspace_step_reports_no_stack(self):
        spec_step = self.store.create_step(stage="spec-writer", role="agent", item=self.child)

        self.assertIsNone(self._surface(spec_step)["stack"])

    def test_an_unstacked_step_reports_no_stack(self):
        item = _item(self.store, "plain", workflow=None)
        step = ActivateItemUseCase(self.store, self.flow, None, None).execute(
            ActivateItemInput(item=item, workflow=WORKFLOW, step="write-code")).step

        self.assertIsNone(self._surface(step)["stack"])


class TestInboxOrder(unittest.TestCase):
    PARENTS = {"c": "p", "g": "c"}

    def _order(self, entries):
        return order_stacks(entries, lambda e: e, self.PARENTS.get)

    def test_a_three_deep_stack_renders_bottom_up(self):
        self.assertEqual(self._order(["g", "c", "p"]), ["p", "c", "g"])

    def test_a_child_whose_parent_has_no_row_stays_in_place(self):
        self.assertEqual(self._order(["x", "c", "y"]), ["x", "c", "y"])

    def test_an_unrelated_row_keeps_its_position(self):
        self.assertEqual(self._order(["g", "x", "p", "c"]), ["x", "p", "c", "g"])

    def test_a_grandchild_follows_its_nearest_ancestor_with_a_row(self):
        self.assertEqual(self._order(["g", "p"]), ["p", "g"])

    def test_the_use_case_orders_gates_parent_first(self):
        store = FakeStore()
        flow = _flow(store)
        parent = _parent(store)
        child = _item(store, "child story", workflow=None)
        _activate(store, flow, child, parent)
        store.set_stacks_on(child, parent)
        child_gate = store.create_step(stage="ready-merge", role="human", item=child)
        parent_gate = store.create_step(stage="ready-merge", role="human", item=parent)

        rows = InboxUseCase(store, flow).execute(InboxInput()).rows

        ids = [r.step.id for r in rows]
        self.assertLess(ids.index(parent_gate), ids.index(child_gate))


class TestDoctorStackFindings(unittest.TestCase):
    def _problems(self, remote_branches, parent_done=False, child_done=False, second=False):
        store = FakeStore()
        flow = _flow(store)
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        repo = os.path.join(root, "app")
        os.makedirs(repo)
        store.add_project("acme/app", local_path=repo)
        parent = _item(store, "parent story", repo="app")
        plant_pr(store, parent, PARENT_PR, phase="code", branch=PARENT_BRANCH)
        child = _item(store, "child story", repo="app", workflow=None)
        _activate(store, flow, child, parent)
        if second:
            other = _item(store, "other parent", repo="app")
            plant_pr(store, other, "https://github.com/o/r/pull/8", phase="code", branch="feat/other")
            other_child = _item(store, "other child", repo="app", workflow=None)
            _activate(store, flow, other_child, other)
        if parent_done:
            store.complete_node(parent, "done")
        if child_done:
            store.complete_node(child, "done")
        git = FakeGit(
            repos={repo}, remote_branches={(repo, b) for b in remote_branches})
        doctor = DoctorUseCase.__new__(DoctorUseCase)
        doctor._store = store
        doctor._flow = flow
        doctor._git = git
        doctor._worktrees = WorktreeService(store, git, FakeFs(), _Cfg(), flow=flow)
        return doctor._stack_problems(), child

    def test_a_missing_parent_branch_is_one_finding(self):
        problems, child = self._problems([])
        self.assertEqual([p.node_id for p in problems], [child])
        self.assertEqual(problems[0].category, "stack")
        self.assertIn(PARENT_BRANCH, problems[0].message)

    def test_a_present_parent_branch_is_clean(self):
        self.assertEqual(self._problems([PARENT_BRANCH])[0], [])

    def test_a_done_stacked_item_is_clean(self):
        self.assertEqual(self._problems([], child_done=True)[0], [])

    def test_a_done_parent_is_clean(self):
        self.assertEqual(self._problems([], parent_done=True)[0], [])

    def test_two_children_one_failing_yields_exactly_one_finding(self):
        problems, child = self._problems(["feat/other"], second=True)
        self.assertEqual([p.node_id for p in problems], [child])


class TestCmdSetStacksOn(unittest.TestCase):
    def setUp(self):
        from tests.support.harness import DEFAULT_WORKFLOW, Harness
        self.h = Harness(["coder", "reviewer"])
        self.workflow = DEFAULT_WORKFLOW
        self.item = self.h.store.create_item("st", "a description")

    def _activate(self, *extra):
        return self.h.run(
            "set", self.item, "--state", "active", "--workflow", self.workflow,
            "--step", "build", *extra)

    def _assert_untouched(self):
        self.assertEqual(self.h.store.get_node(self.item).state, "backlogged")
        self.assertEqual(self.h.store.children(self.item), [])

    def test_stacks_on_with_depends_is_refused_naming_both_flags(self):
        parent = self.h.store.create_item("parent", "a description")
        blocker = self.h.store.create_item("blocker", "a description")

        rc, _out, err = self._activate("--stacks-on", parent, "--depends", blocker)

        self.assertEqual(rc, 2)
        self.assertIn("--stacks-on", err)
        self.assertIn("--depends", err)
        self._assert_untouched()

    def test_an_unknown_parent_is_refused(self):
        rc, _out, err = self._activate("--stacks-on", "does-not-exist")

        self.assertEqual(rc, 1)
        self.assertIn("unknown node 'does-not-exist'", err)
        self._assert_untouched()

    def test_a_step_id_is_refused_naming_the_item_to_pass(self):
        from tests.support.step_factory import create_owned_step
        step = create_owned_step(self.h.store, "parent step", role="agent")

        rc, _out, err = self._activate("--stacks-on", step)

        self.assertEqual(rc, 1)
        self.assertIn("is a step, not an item", err)
        self.assertIn("--stacks-on", err)
        self._assert_untouched()

    def test_stacks_on_outside_activation_is_refused(self):
        parent = self.h.store.create_item("parent", "a description")

        rc, _out, err = self.h.run("set", self.item, "--stacks-on", parent)

        self.assertEqual(rc, 2)
        self.assertIn("--stacks-on", err)


class TestStackVisibility(unittest.TestCase):
    def test_the_blocked_line_names_the_stack_parent(self):
        from lightcycle.adapters.tui.hub_render import _dependency_escalation
        from lightcycle.domain.work import Step, State

        step = Step(id="s", item="i", state=State.BLOCKED, blocked_by=["P-1"])

        self.assertEqual(
            _dependency_escalation(step, "P-1"),
            ("Blocked · stacked on P-1 (waiting for its PR)", "P-1"))
        self.assertEqual(_dependency_escalation(step), ("Blocked · depends on P-1", "P-1"))

    def test_an_item_line_carries_the_stacked_on_suffix(self):
        from lightcycle.domain.work import Item
        from lightcycle.render import node_extra

        self.assertIn("[stacked on P-1]", node_extra(Item(id="i", stacks_on="P-1")))
        self.assertNotIn("stacked", node_extra(Item(id="i")))

    def test_status_marks_a_stacked_step(self):
        from tests.support.harness import Harness

        h = Harness(["coder", "reviewer"])
        parent = h.store.create_item("parent", "a description")
        child = h.store.create_item("child", "a description")
        step = h.store.create_step(stage="build", role="agent", item=child, deps=[parent])
        h.store.set_stacks_on(child, parent)

        rc, out, err = h.run("status")

        self.assertEqual(rc, 0, err)
        line = next(l for l in out.splitlines() if step in l)
        self.assertIn("[stacked on %s]" % parent, line)

    def test_the_node_view_carries_stacks_on_for_the_owning_item(self):
        store = FakeStore()
        parent = store.create_item("parent", "d")
        child = store.create_item("child", "d")
        step = store.create_step(stage="build", role="agent", item=child)
        store.set_stacks_on(child, parent)

        self.assertEqual(store.node_view(step).stacks_on, parent)
        self.assertEqual(store.node_view(child).stacks_on, parent)
        self.assertIsNone(store.node_view(parent).stacks_on)

    def test_the_hierarchy_label_of_a_stacked_item_names_its_parent(self):
        from lightcycle.adapters.tui.hub_render import _hierarchy_label
        from lightcycle.domain.work import Item

        self.assertEqual(
            _hierarchy_label(Item(id="i", title="Child", stacks_on="P-1"), None, False),
            "Child · Stacked on: P-1")
        self.assertEqual(_hierarchy_label(Item(id="i", title="Child"), None, False), "Child")
