import unittest

from lightcycle.application.flow import CompleteInput, CompleteStepUseCase
from lightcycle.application.flow.record_merged_gate_run import (
    RecordMergedGateRunInput, RecordMergedGateRunUseCase,
)
from lightcycle.application.services.flow import FlowService
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.domain.runs import RunState
from lightcycle.ports.github import StackLayer
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore

REPO = "/elsewhere/app"
CODE_BRANCH = "feat/app-code"
SPEC_BRANCH = "feat/app-spec"
CODE_PR = "https://github.com/x/y/pull/7"
SPEC_PR = "https://github.com/x/y/pull/6"
METAS = {
    "coder": {"model": "sonnet", "step": "write-code"},
    "gate": {"step": "gate"},
    "cleaner": {"model": "sonnet", "step": "cleanup"},
}
WORKFLOW = (
    "entry: write-code\n\n"
    "phase:\n"
    "  spec-gate   spec\n"
    "  write-code  code\n"
    "  code-gate   code\n"
    "  pass-gate   code\n\n"
    "nodes:\n"
    "  spec-gate  gate\n"
    "  cleanup    cleaner\n"
    "  code-gate  gate\n"
    "  pass-gate  gate\n\n"
    "edges:\n"
    "  spec-gate  spec-merged  write-code\n"
    "  code-gate  merged       cleanup\n"
    "  pass-gate  merged       cleanup\n\n"
    "hooks:\n"
    "  pr_merge  spec-gate  spec-merged\n"
    "  pr_merge  code-gate  merged\n"
    "  pr_merge  pass-gate  merged\n\n"
    "pass-end:\n"
    "  pass-gate  merged\n\n"
    "disposition:\n"
    "  merged       completed\n"
    "  spec-merged  completed\n"
)


class _Cfg:
    def worktree_retries(self):
        return 0

    def worktree_retry_sleep(self):
        return 0

    def branch_prefix(self):
        return "feat"

    def projects_root(self):
        return "/projects"

    def engine_root(self):
        return "lightcycle"

    def spawn_id(self):
        return None


def _layer(n, state):
    return StackLayer(n, "https://github.com/x/y/pull/%d" % n, "h%d" % n, "b%d" % n, "s%d" % n, state)


class _World:
    def __init__(self, github, beyond=True, gate="code-gate", phase="code", pr=CODE_PR,
                 branch=CODE_BRANCH, stack=None):
        self.git = FakeGit(
            branches={(REPO, CODE_BRANCH), (REPO, SPEC_BRANCH)}, ref="origin/main",
            beyond={(REPO, CODE_BRANCH): ["a1"]} if beyond else {},
        )
        self.store = FakeStore()
        self.github = github
        self.flow = FlowService(FakeFs(METAS, workflow={"wf": WORKFLOW}), self.store)
        self.item = self.store.create_item("story", "a description", workflow="wf")
        self.store.add_artifact(self.item, "repo", REPO)
        self.pass_id = self.store.open_pass(self.item)
        self.run = self._run(phase, branch, pr, stack)
        self.step = self.store.create_step(stage=gate, role="human", item=self.item)
        self.worktrees = WorktreeService(self.store, self.git, fs=None, config=_Cfg())

    def _run(self, phase, branch, pr, stack):
        rid = self.store.open_run(self.item, self.pass_id, phase)
        self.store.set_branch(rid, branch)
        self.store.set_pr(rid, pr)
        if stack:
            self.store.set_stack(rid, stack)
        return rid

    def record(self, outcome="merged"):
        return RecordMergedGateRunUseCase(self.store, self.github, self.flow).execute(
            RecordMergedGateRunInput(step=self.step, outcome=outcome)
        )

    def done(self, outcome="merged"):
        self.record(outcome)
        return CompleteStepUseCase(self.store, self.flow, self.worktrees, _Cfg()).execute(
            CompleteInput(step=self.step, outcome=outcome)
        )

    def pass_end(self, outcome="merged"):
        merged = RecordMergedGateRunUseCase(self.store, self.github, self.flow).merged_prs_at_pass_end(
            RecordMergedGateRunInput(step=self.step, outcome=outcome)
        )
        return CompleteStepUseCase(self.store, self.flow, self.worktrees, _Cfg()).execute(
            CompleteInput(step=self.step, outcome=outcome, merged_prs=merged)
        )

    def removed(self):
        return [c[0] for c in self.git.calls if c[0] in ("remove_worktree", "delete_branch")]

    def finish(self, resp):
        return CompleteStepUseCase(self.store, self.flow, self.worktrees, _Cfg()).execute(
            CompleteInput(step=resp.next_step, outcome="done")
        )

    def states(self):
        return {r.id: r.state for r in self.store.runs_of(self.item)}


class TestTerminalGate(unittest.TestCase):
    def test_squash_merged_pr_closes_the_item_with_every_run_merged(self):
        w = _World(FakeGitHub(merged_prs={CODE_PR}))

        closed = w.finish(w.done())

        self.assertIsNone(closed.teardown_refusal)
        self.assertEqual(w.store.get_node(w.item).state, "done")
        self.assertEqual(w.states()[w.run], RunState.MERGED)
        self.assertNotIn("commits_beyond", [c[0] for c in w.git.calls])

    def test_pr_not_merged_leaves_the_run_open_and_keeps_the_park(self):
        w = _World(FakeGitHub())

        closed = w.finish(w.done())

        self.assertIn(CODE_BRANCH, closed.teardown_refusal)
        self.assertNotEqual(w.store.get_node(w.item).state, "done")
        self.assertEqual(w.states()[w.run], RunState.OPEN)

    def test_unreadable_merge_state_changes_nothing(self):
        w = _World(FakeGitHub(merged_prs={CODE_PR}, failing_calls={"is_merged"}))

        self.assertFalse(w.record())
        self.assertEqual(w.states()[w.run], RunState.OPEN)
        closed = w.finish(w.done())

        self.assertIn(CODE_BRANCH, closed.teardown_refusal)


class TestNonTerminalGate(unittest.TestCase):
    def test_spec_merged_closes_the_spec_run_merged_immediately(self):
        w = _World(FakeGitHub(merged_prs={SPEC_PR}), gate="spec-gate", phase="spec",
                   pr=SPEC_PR, branch=SPEC_BRANCH, beyond=False)

        w.done("spec-merged")

        self.assertEqual(w.states()[w.run], RunState.MERGED)


class TestStackedRun(unittest.TestCase):
    URL = "https://github.com/x/y/stack/1"

    def _world(self, last_state):
        gh = FakeGitHub()
        gh.script_stack(self.URL, [_layer(5, "merged"), _layer(7, last_state)])
        return _World(gh, stack=self.URL)

    def test_merged_when_the_last_layer_is_merged(self):
        w = self._world("merged")

        self.assertTrue(w.record())
        self.assertEqual(w.states()[w.run], RunState.MERGED)

    def test_not_merged_when_the_last_layer_is_open(self):
        w = self._world("open")

        self.assertFalse(w.record())
        self.assertEqual(w.states()[w.run], RunState.OPEN)


class TestSkips(unittest.TestCase):
    def test_pass_ending_outcome_is_left_to_the_pass_book(self):
        w = _World(FakeGitHub(merged_prs={CODE_PR}), gate="pass-gate", beyond=False)

        self.assertFalse(w.record())
        w.done()

        self.assertEqual(w.states()[w.run], RunState.MERGED)

    def test_outcome_other_than_the_merge_hook_is_skipped(self):
        w = _World(FakeGitHub(merged_prs={CODE_PR}))

        self.assertFalse(w.record("changes"))
        self.assertEqual(w.states()[w.run], RunState.OPEN)

    def test_already_done_step_is_skipped_on_repair(self):
        w = _World(FakeGitHub(merged_prs={CODE_PR}))
        w.done()
        reopened = w.store.open_run(w.item, w.pass_id, "code")
        w.store.set_pr(reopened, CODE_PR)

        self.assertFalse(w.record())
        self.assertEqual(w.states()[reopened], RunState.OPEN)

    def test_only_the_gates_run_turns_merged(self):
        w = _World(FakeGitHub(merged_prs={CODE_PR}))
        other = w.store.open_run(w.item, w.pass_id, "spec")
        w.store.set_branch(other, SPEC_BRANCH)

        self.assertTrue(w.record())

        self.assertEqual(w.states()[w.run], RunState.MERGED)
        self.assertEqual(w.states()[other], RunState.OPEN)


class TestPassEndingGate(unittest.TestCase):
    URL = "https://github.com/x/y/stack/1"

    def _world(self, github, **kw):
        return _World(github, gate="pass-gate", **kw)

    def _use_case(self, w):
        return RecordMergedGateRunUseCase(w.store, w.github, w.flow)

    def _input(self, w, outcome="merged"):
        return RecordMergedGateRunInput(step=w.step, outcome=outcome)

    def test_squash_merged_pr_passes_the_pass_end_and_releases_the_worktree(self):
        w = self._world(FakeGitHub(merged_prs={CODE_PR}))

        resp = w.pass_end()

        self.assertIsNone(resp.teardown_refusal)
        self.assertEqual(w.store.get_node(w.step).state, "done")
        self.assertEqual(w.states()[w.run], RunState.MERGED)
        self.assertEqual(w.store.get_pass(w.pass_id).state, "closed")
        self.assertIn("remove_worktree", w.removed())
        self.assertIn("delete_branch", w.removed())

    def test_pr_not_merged_keeps_the_refusal_and_removes_nothing(self):
        w = self._world(FakeGitHub())

        resp = w.pass_end()

        self.assertIn("pass end refused", w.store.get_node(w.step).park.reason)
        self.assertIn(CODE_BRANCH, resp.teardown_refusal)
        self.assertEqual(w.removed(), [])
        self.assertEqual(w.states()[w.run], RunState.OPEN)

    def test_unreadable_merge_state_keeps_the_refusal(self):
        w = self._world(FakeGitHub(merged_prs={CODE_PR}, failing_calls={"is_merged"}))

        resp = w.pass_end()

        self.assertIn(CODE_BRANCH, resp.teardown_refusal)
        self.assertEqual(w.removed(), [])
        self.assertEqual(w.states()[w.run], RunState.OPEN)

    def test_stacked_run_is_proven_only_when_the_last_layer_is_merged(self):
        for last, refused in (("merged", False), ("open", True)):
            gh = FakeGitHub()
            gh.script_stack(self.URL, [_layer(5, "merged"), _layer(7, last)])
            w = self._world(gh, stack=self.URL)

            resp = w.pass_end()

            self.assertEqual(resp.teardown_refusal is not None, refused, last)

    def test_another_open_run_with_an_unmerged_commit_still_refuses(self):
        w = self._world(FakeGitHub(merged_prs={CODE_PR}))
        other = w.store.open_run(w.item, w.pass_id, "spec")
        w.store.set_branch(other, SPEC_BRANCH)
        w.git._beyond[(REPO, SPEC_BRANCH)] = ["b1"]

        resp = w.pass_end()

        self.assertIn(SPEC_BRANCH, resp.teardown_refusal)
        self.assertNotIn(CODE_BRANCH, resp.teardown_refusal)
        self.assertEqual(w.removed(), [])

    def test_dirty_worktree_of_a_merged_gate_run_is_still_refused(self):
        w = self._world(FakeGitHub(merged_prs={CODE_PR}))
        path = w.worktrees.path_for_run(w.store.get_run(w.run))
        w.git._registered = {path}
        w.git._uncommitted = {path: ["a.py"]}

        resp = w.pass_end()

        self.assertIn("a.py", resp.teardown_refusal)
        self.assertEqual(w.removed(), [])

    def test_merged_prs_is_empty_for_a_non_pass_ending_outcome(self):
        w = _World(FakeGitHub(merged_prs={CODE_PR}))

        self.assertEqual(self._use_case(w).merged_prs_at_pass_end(self._input(w)), frozenset())

    def test_merged_prs_is_empty_when_the_outcome_is_not_the_merge_outcome(self):
        w = self._world(FakeGitHub(merged_prs={CODE_PR}))

        self.assertEqual(self._use_case(w).merged_prs_at_pass_end(self._input(w, "changes")), frozenset())

    def test_merged_prs_is_empty_for_a_done_step(self):
        w = self._world(FakeGitHub(merged_prs={CODE_PR}))
        w.pass_end()

        self.assertEqual(self._use_case(w).merged_prs_at_pass_end(self._input(w)), frozenset())

    def test_merged_prs_names_the_gates_pr_and_closes_no_run(self):
        w = self._world(FakeGitHub(merged_prs={CODE_PR}))

        merged = self._use_case(w).merged_prs_at_pass_end(self._input(w))

        self.assertEqual(merged, frozenset({CODE_PR}))
        self.assertEqual(w.states()[w.run], RunState.OPEN)


class TestPassReleaseRefusalsDirect(unittest.TestCase):
    def _run(self, w):
        return list(w.store.open_runs_of(w.item, w.pass_id))

    def test_a_run_in_merged_prs_skips_the_ancestry_check(self):
        w = _World(FakeGitHub(), gate="pass-gate")

        self.assertEqual(w.worktrees.pass_release_refusals(w.item, self._run(w), frozenset({CODE_PR})), [])
        self.assertNotIn("commits_beyond", [c[0] for c in w.git.calls])

    def test_a_run_not_in_merged_prs_keeps_the_ancestry_check(self):
        w = _World(FakeGitHub(), gate="pass-gate")

        findings = w.worktrees.pass_release_refusals(w.item, self._run(w), frozenset({"other"}))

        self.assertEqual(len(findings), 1)
        self.assertIn("commits_beyond", [c[0] for c in w.git.calls])
