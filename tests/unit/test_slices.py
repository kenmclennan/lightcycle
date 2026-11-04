import os
import shutil
import tempfile
import unittest

from lightcycle.adapters.scaffold import ScaffoldAdapter
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.passes import PassBook
from lightcycle.application.inspect.doctor import DoctorUseCase
from lightcycle.application.pool.release_stacked_items import ReleaseStackedItemsUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.application.workflows.bundle_check import check_bundle_references
from lightcycle.application.work.link_artifact import LinkArtifactInput, LinkArtifactUseCase
from lightcycle.application.work.node_read_surface import node_read_surface
from lightcycle.domain.flow.graph import parse_graph
from lightcycle.domain.runs import RunState, parse_slices, run_id, run_round
from lightcycle.application.flow import CompleteInput, CompleteStepUseCase
from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.resolve_merged_prs import ResolveMergedPrsUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_resolve_merged_prs import FakeWorktrees

WORKFLOW = "lightcycle/spec-driven"

_GRAPH = (
    "entry: plan\n\n"
    "nodes:\n"
    "  write  coder\n"
    "  gate   gate\n\n"
    "phase:\n"
    "  plan   spec\n"
    "  write  code\n"
    "  gate   code\n"
    "  cleanup  code\n\n"
    "slices: code from slices\n\n"
    "edges:\n"
    "  plan   done    write\n"
    "  write  done    gate\n"
    "  gate   merged  cleanup\n\n"
    "hooks:\n"
    "  pr_merge  gate  merged\n"
)
_METAS = {
    "plan": {"model": "sonnet", "step": "plan"},
    "coder": {"model": "sonnet", "step": "write"},
    "gate": {"step": "gate"},
    "cleanup": {"model": "sonnet", "step": "cleanup"},
}


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


def _flow(store):
    return FlowService(FakeFs(_METAS, workflow=_GRAPH), store)


class _World:
    def __init__(self, repo=None):
        self.store = FakeStore()
        self.flow = _flow(self.store)
        self.item = self.store.create_item("story", "d", workflow=WORKFLOW)
        if repo:
            self.store.add_artifact(self.item, "repo", repo)
        self.pid = self.store.open_pass(self.item)

    def slice_run(self, n, name, base, branch=None, pr=None, state=RunState.OPEN):
        rid = self.store.open_run(self.item, self.pid, "code", n, name, base)
        if branch:
            self.store.set_branch(rid, branch)
        if pr:
            self.store.set_pr(rid, pr)
        if state != RunState.OPEN:
            self.store.close_run(rid, state)
        return rid

    def slice_step(self, n, stage="write", blocked=False):
        step = self.store.create_step(
            stage=stage, role="agent", item=self.item,
            deps=[self.item] if blocked else None, slice=n)
        self.store.set_step_pass(step, self.pid)
        return step


class TestParseSlices(unittest.TestCase):
    def test_the_three_line_example(self):
        slices = parse_slices("add-schema\nwrite-service on add-schema\nwire-cli on write-service\n")
        self.assertEqual(
            [(s.number, s.name, s.base) for s in slices],
            [(1, "add-schema", None), (2, "write-service", 1), (3, "wire-cli", 2)])

    def test_a_bare_name_stacks_on_the_previous_line(self):
        slices = parse_slices("a\n\nb\nc\n")
        self.assertEqual([s.base for s in slices], [None, 1, 2])

    def test_a_non_linear_base(self):
        slices = parse_slices("a\nb\nc\nd on a\n")
        self.assertEqual(slices[3].base, 1)

    def test_empty_text_has_no_slices(self):
        self.assertEqual(parse_slices(""), ())
        self.assertEqual(parse_slices(None), ())

    def test_a_duplicate_name_is_refused_naming_the_line(self):
        with self.assertRaisesRegex(ValueError, "line 2.*duplicate"):
            parse_slices("a\na\n")

    def test_a_forward_base_is_refused(self):
        with self.assertRaisesRegex(ValueError, "line 1.*earlier"):
            parse_slices("a on b\nb\n")

    def test_an_unknown_base_is_refused(self):
        with self.assertRaisesRegex(ValueError, "line 2.*earlier"):
            parse_slices("a\nb on zzz\n")

    def test_an_invalid_name_is_refused(self):
        with self.assertRaisesRegex(ValueError, "line 1.*match"):
            parse_slices("Bad_Name\n")

    def test_a_malformed_line_is_refused(self):
        with self.assertRaisesRegex(ValueError, "line 1"):
            parse_slices("a b c d\n")


class TestSlicesDeclaration(unittest.TestCase):
    def test_parse_graph_reads_the_declaration(self):
        graph = parse_graph("entry: x\n\nslices: code from slices\n")
        self.assertEqual((graph.sliced_phase, graph.slices_artifact), ("code", "slices"))

    def test_a_missing_from_is_refused(self):
        with self.assertRaisesRegex(ValueError, "line 3"):
            parse_graph("entry: x\n\nslices: code slices\n")

    def test_no_declaration_leaves_both_none(self):
        graph = parse_graph("entry: x\n")
        self.assertEqual((graph.sliced_phase, graph.slices_artifact), (None, None))

    def test_the_bundle_check_rejects_a_phase_the_graph_lacks(self):
        class Bundle:
            steps = {"coder": "---\nmodel: sonnet\n---\nx\n"}
            workflows = {"w": "entry: write\n\nnodes:\n  write  coder\n\nphase:\n  write  code\n\n"
                              "slices: nope from slices\n\nedges:\n  write  done\n"}
            fragments = {}

        messages = check_bundle_references(Bundle())["w"]
        self.assertTrue(any("nope" in m and "phase" in m for m in messages))


class TestRunIds(unittest.TestCase):
    def test_slice_zero_keeps_todays_ids(self):
        self.assertEqual(run_id("LC-9.p1", "code"), "LC-9.p1.code")
        self.assertEqual(run_id("LC-9.p1", "code", 2), "LC-9.p1.code.r2")

    def test_slice_ids(self):
        self.assertEqual(run_id("LC-9.p1", "code", 1, 2), "LC-9.p1.code.s2")
        self.assertEqual(run_id("LC-9.p1", "code", 2, 2), "LC-9.p1.code.s2.r2")

    def test_the_round_reads_from_both_forms(self):
        self.assertEqual(run_round("LC-9.p1.code.s2"), 1)
        self.assertEqual(run_round("LC-9.p1.code.s2.r2"), 2)

    def test_a_closed_slice_run_reopens_as_its_second_round(self):
        w = _World()
        first = w.slice_run(2, "b", 1)
        w.store.close_run(first, RunState.MERGED)
        self.assertEqual(w.store.open_run(w.item, w.pid, "code", 2, "b", 1), first + ".r2")

    def test_current_run_filters_by_slice(self):
        w = _World()
        one = w.slice_run(1, "a", None)
        two = w.slice_run(2, "b", 1)
        self.assertEqual(w.store.current_run(w.item, "code", 1).id, one)
        self.assertEqual(w.store.current_run(w.item, "code", 2).id, two)
        self.assertIsNone(w.store.current_run(w.item, "code"))

    def test_a_step_records_its_slice(self):
        w = _World()
        step = w.slice_step(2)
        self.assertEqual(w.store.get_node(step).slice, 2)
        self.assertEqual(w.store.get_node(step).as_dict()["slice"], 2)


class TestReleaseSweep(unittest.TestCase):
    def setUp(self):
        self.w = _World()
        self.sweep = ReleaseStackedItemsUseCase(self.w.store, self.w.flow)

    def _world(self, base_pr=None, base_branch="feat/a", base_state=RunState.OPEN):
        self.w.slice_run(1, "a", None, branch=base_branch, pr=base_pr, state=base_state)
        self.w.slice_run(2, "b", 1)
        return self.w.slice_step(2, blocked=True)

    def test_the_slice_is_released_when_its_base_holds_a_pr(self):
        step = self._world(base_pr="https://github.com/o/r/pull/1")
        self.assertEqual(self.sweep.execute(), [step])
        self.assertEqual(self.w.store.get_node(step).blocked_by, [])

    def test_a_base_with_a_branch_but_no_pr_stays_blocked(self):
        step = self._world()
        self.assertEqual(self.sweep.execute(), [])
        self.assertEqual(self.w.store.get_node(step).blocked_by, [self.w.item])

    def test_the_sweep_is_idempotent(self):
        self._world(base_pr="https://github.com/o/r/pull/1")
        self.sweep.execute()
        self.assertEqual(self.sweep.execute(), [])

    def test_a_merged_base_with_a_pr_still_releases(self):
        step = self._world(base_pr="https://github.com/o/r/pull/1", base_state=RunState.MERGED)
        self.assertEqual(self.sweep.execute(), [step])

    def test_only_a_dependency_on_the_items_own_id_is_removed(self):
        self.w.slice_run(1, "a", None, branch="feat/a", pr="https://github.com/o/r/pull/1")
        self.w.slice_run(2, "b", 1)
        other = self.w.store.create_item("other", "d")
        step = self.w.slice_step(2, blocked=True)
        self.w.store.dep_add(step, other)
        self.sweep.execute()
        self.assertEqual(self.w.store.get_node(step).blocked_by, [other])

    def test_the_first_slice_is_never_touched(self):
        self.w.slice_run(1, "a", None, branch="feat/a", pr="https://github.com/o/r/pull/1")
        first = self.w.slice_step(1, blocked=True)
        self.assertEqual(self.sweep.execute(), [])
        self.assertEqual(self.w.store.get_node(first).blocked_by, [self.w.item])


class TestDeferral(unittest.TestCase):
    def setUp(self):
        self.w = _World()
        self.book = PassBook(self.w.store, self.w.flow)

    def _gate(self, n):
        return self.w.store.get_node(self.w.slice_step(n, stage="gate"))

    def test_true_for_a_slice_gate_with_another_open_slice_run(self):
        self.w.slice_run(1, "a", None)
        self.w.slice_run(2, "b", 1)
        self.assertTrue(self.book.defers_to_last_slice(self._gate(1), "merged", WORKFLOW))

    def test_false_for_the_last_open_slice(self):
        self.w.slice_run(1, "a", None, state=RunState.MERGED)
        self.w.slice_run(2, "b", 1)
        self.assertFalse(self.book.defers_to_last_slice(self._gate(2), "merged", WORKFLOW))

    def test_false_for_a_different_outcome(self):
        self.w.slice_run(1, "a", None)
        self.w.slice_run(2, "b", 1)
        self.assertFalse(self.book.defers_to_last_slice(self._gate(1), "changes", WORKFLOW))

    def test_false_for_slice_zero(self):
        self.w.slice_run(1, "a", None)
        gate = self.w.store.get_node(self.w.store.create_step(
            stage="gate", role="human", item=self.w.item))
        self.assertFalse(self.book.defers_to_last_slice(gate, "merged", WORKFLOW))


class TestResolveMergedSlices(unittest.TestCase):
    PR1 = "https://github.com/o/r/pull/1"
    PR2 = "https://github.com/o/r/pull/2"

    def _resolve(self, merged):
        github = FakeGitHub(merged_prs=merged)
        use = ResolveMergedPrsUseCase(
            self.w.store, github, FakeWorktrees(), self.w.flow,
            CompleteStepUseCase(self.w.store, self.w.flow),
            CheckContentPinUseCase(
                self.w.store, github, self.w.flow, trusted_authors=lambda: frozenset()),
        )
        return use.execute()

    def setUp(self):
        self.w = _World()
        self.one = self.w.slice_run(1, "a", None, branch="feat/a", pr=self.PR1)
        self.two = self.w.slice_run(2, "b", 1, branch="feat/b", pr=self.PR2)
        self.gate1 = self.w.slice_step(1, stage="gate")
        self.gate2 = self.w.slice_step(2, stage="gate")

    def test_only_the_merged_slices_gate_completes(self):
        result = self._resolve({self.PR1})

        self.assertEqual(result.merged, [self.w.item])
        self.assertEqual(self.w.store.get_node(self.gate1).state, "done")
        self.assertEqual(self.w.store.get_run(self.one).state, RunState.MERGED)
        self.assertNotEqual(self.w.store.get_node(self.gate2).state, "done")
        self.assertEqual(self.w.store.get_run(self.two).state, RunState.OPEN)
        self.assertNotEqual(self.w.store.get_node(self.w.item).state, "done")

    def test_a_deferred_completion_creates_no_successor(self):
        self._resolve({self.PR1})

        self.assertEqual(
            [s.stage for s in self.w.store.children(self.w.item) if s.state != "done"],
            ["gate"])

    def test_the_last_merge_takes_the_transition(self):
        self._resolve({self.PR1})
        self._resolve({self.PR1, self.PR2})

        cleanups = [s for s in self.w.store.children(self.w.item) if s.stage == "cleanup"]
        self.assertEqual(len(cleanups), 1)
        self.assertEqual(cleanups[0].slice, 2)

    def test_a_manual_completion_of_a_non_last_gate_behaves_the_same(self):
        CompleteStepUseCase(self.w.store, self.w.flow).execute(
            CompleteInput(step=self.gate1, outcome="merged"))

        self.assertEqual(self.w.store.get_node(self.gate1).state, "done")
        self.assertEqual(self.w.store.get_run(self.one).state, RunState.MERGED)
        self.assertEqual([s.stage for s in self.w.store.children(self.w.item)
                          if s.stage == "cleanup"], [])


class TestAttach(unittest.TestCase):
    def setUp(self):
        self.w = _World()
        self.use = LinkArtifactUseCase(self.w.store, self.w.flow)

    def _attach(self, value, step=None):
        self.use.execute(LinkArtifactInput(
            item=self.w.item, atype="slices", value=value, step=step))

    def test_a_malformed_list_is_refused_and_nothing_is_written(self):
        with self.assertRaisesRegex(UseCaseError, "line 1"):
            self._attach("b on a")
        self.assertEqual(self.w.store.item_artifacts(self.w.item), [])

    def test_a_well_formed_list_is_stored(self):
        self._attach("a\nb on a")
        self.assertEqual([a.value for a in self.w.store.item_artifacts(self.w.item)], ["a\nb on a"])

    def test_a_pr_attach_by_a_slice_step_writes_that_slices_run(self):
        self.w.slice_run(1, "a", None)
        two = self.w.slice_run(2, "b", 1)
        step = self.w.slice_step(2)
        self.use.execute(LinkArtifactInput(
            item=self.w.item, atype="pr", value="https://github.com/o/r/pull/2", step=step))
        self.assertEqual(self.w.store.get_run(two).pr, "https://github.com/o/r/pull/2")

    def test_a_pr_attach_without_a_step_refuses_when_two_slices_are_open(self):
        self.w.slice_run(1, "a", None)
        self.w.slice_run(2, "b", 1)
        self.w.slice_step(1)
        with self.assertRaisesRegex(UseCaseError, "slices"):
            self.use.execute(LinkArtifactInput(
                item=self.w.item, atype="pr", value="https://github.com/o/r/pull/2"))


class TestReadSurface(unittest.TestCase):
    def setUp(self):
        self.w = _World()

    def _surface(self, node_id):
        return node_read_surface(
            self.w.store, self.w.flow, self.w.store.node_view(node_id))

    def test_the_item_lists_its_slices_in_order(self):
        self.w.slice_run(1, "a", None, branch="feat/a", pr="u1")
        self.w.slice_run(2, "b", 1, branch="feat/b")
        step = self.w.slice_step(2)
        slices = self._surface(self.w.item)["slices"]
        self.assertEqual(
            [(s["slice"], s["name"], s["base"], s["state"], s["branch"], s["pr"], s["step"])
             for s in slices],
            [(1, "a", None, "open", "feat/a", "u1", None),
             (2, "b", 1, "open", "feat/b", None, step)])

    def test_an_unsliced_item_has_no_slices(self):
        item = self.w.store.create_item("plain", "d", workflow=WORKFLOW)
        self.assertEqual(self._surface(item)["slices"], [])

    def test_the_step_carries_its_slice_and_the_stack(self):
        self.w.slice_run(1, "a", None, branch="feat/a", pr="u1")
        self.w.slice_run(2, "b", 1)
        step = self.w.slice_step(2)
        out = self._surface(step)
        self.assertEqual((out["slice"], out["slice_name"]), (2, "b"))
        self.assertEqual(out["stack"], {
            "parent": self.w.item, "parent_title": "story - slice a",
            "branch": "feat/a", "pr": "u1"})

    def test_a_merged_base_gives_no_stack(self):
        self.w.slice_run(1, "a", None, branch="feat/a", pr="u1", state=RunState.MERGED)
        self.w.slice_run(2, "b", 1)
        step = self.w.slice_step(2)
        self.assertIsNone(self._surface(step)["stack"])


class TestSliceWorktreeBase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.repo = os.path.join(self.root, "app")
        os.makedirs(self.repo)
        self.w = _World(repo="app")
        self.w.store.add_project("acme/app", local_path=self.repo)

    def _ensure(self, base_state=RunState.OPEN, remote=("feat/a",), n=2):
        self.w.slice_run(1, "a", None, branch="feat/a", pr="u1", state=base_state)
        self.w.slice_run(2, "b", 1)
        step = self.w.slice_step(n)
        git = FakeGit(
            repos={self.repo}, sync_result=True, base="origin/main",
            remote_branches={(self.repo, b) for b in remote})
        svc = WorktreeService(
            self.w.store, git, FakeFs(), _Cfg(), flow=self.w.flow, scaffold=ScaffoldAdapter())
        svc.ensure(self.w.store.get_node(step))
        return git, svc, step

    @staticmethod
    def _base_of(git):
        return next(c for c in git.calls if c[0] == "add_worktree")[4]

    def test_an_open_base_slice_is_the_base_of_the_branch(self):
        git, _svc, _step = self._ensure()
        self.assertEqual(self._base_of(git), "origin/feat/a")

    def test_a_merged_base_slice_uses_the_default_base(self):
        git, _svc, _step = self._ensure(base_state=RunState.MERGED, remote=())
        self.assertEqual(self._base_of(git), "origin/main")

    def test_an_open_base_whose_branch_is_gone_is_refused(self):
        with self.assertRaisesRegex(UseCaseError, "base slice a.*no longer exists"):
            self._ensure(remote=())

    def test_two_slice_runs_mint_distinct_branches_and_paths(self):
        _git, svc, step = self._ensure()
        one = self.w.store.get_node(self.w.slice_step(1))
        two = self.w.store.get_node(step)
        self.assertNotEqual(svc.worktree_path(one), svc.worktree_path(two))
        self.assertNotEqual(svc._minted_branch(one), svc._minted_branch(two))

    def test_a_slice_step_without_a_run_is_refused(self):
        step = self.w.slice_step(3)
        git = FakeGit(repos={self.repo}, sync_result=True, base="origin/main")
        svc = WorktreeService(
            self.w.store, git, FakeFs(), _Cfg(), flow=self.w.flow, scaffold=ScaffoldAdapter())
        with self.assertRaisesRegex(UseCaseError, "slice 3 has no run"):
            svc.ensure(self.w.store.get_node(step))


class TestDoctorSliceFindings(unittest.TestCase):
    def _problems(self, remote, base_state=RunState.OPEN, orphan=False):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        repo = os.path.join(root, "app")
        os.makedirs(repo)
        w = _World(repo="app")
        w.store.add_project("acme/app", local_path=repo)
        w.slice_run(1, "a", None, branch="feat/a", pr="u1", state=base_state)
        w.slice_run(2, "b", 1, branch="feat/b", pr="u2")
        if orphan:
            w.slice_run(3, "c", 9)
        git = FakeGit(repos={repo}, remote_branches={(repo, b) for b in remote})
        doctor = DoctorUseCase.__new__(DoctorUseCase)
        doctor._store = w.store
        doctor._flow = w.flow
        doctor._git = git
        doctor._worktrees = WorktreeService(w.store, git, FakeFs(), _Cfg(), flow=w.flow)
        return doctor._slice_problems()

    def test_a_missing_base_branch_is_one_finding(self):
        problems = self._problems([])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].category, "slice")
        self.assertIn("feat/a", problems[0].message)

    def test_a_present_base_branch_is_clean(self):
        self.assertEqual(self._problems(["feat/a"]), [])

    def test_a_merged_base_is_clean(self):
        self.assertEqual(self._problems([], base_state=RunState.MERGED), [])

    def test_a_base_slice_with_no_run_is_a_finding(self):
        problems = self._problems(["feat/a"], orphan=True)
        self.assertEqual(len(problems), 1)
        self.assertIn("slice c", problems[0].message)


if __name__ == "__main__":
    unittest.main()
