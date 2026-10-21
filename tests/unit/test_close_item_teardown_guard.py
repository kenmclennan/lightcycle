import os
import unittest

from lightcycle.application.flow import CompleteInput, CompleteStepUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.application.work.close_item import (
    TEARDOWN_REFUSED_ARTIFACT, CloseItemInput, CloseItemUseCase, TeardownRefused,
)
from lightcycle.domain.runs import RunState
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore

REPO = "/elsewhere/app"
BRANCH = "feat/app-x"
PATH = os.path.join(REPO, ".worktrees", "%s")


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


def _world(git, branch=BRANCH, pr=None, run_state=None):
    store = FakeStore()
    item = store.create_item("story", "a description")
    store.add_artifact(item, "repo", REPO)
    pid = store.open_pass(item)
    rid = store.open_run(item, pid, None)
    store.set_branch(rid, branch)
    if pr:
        store.set_pr(rid, pr)
    if run_state:
        store.close_run(rid, run_state)
    step = store.create_step(step="finalise", role="agent", parent=item)
    svc = WorktreeService(store, git, fs=None, config=_Cfg())
    return store, svc, item, step


def _close(store, svc, item, **kw):
    CloseItemUseCase(store, svc).execute(
        CloseItemInput(item=item, reason="done", disposition="completed", **kw)
    )


def _removed(git):
    return [c for c in git.calls if c[0] in ("remove_worktree", "delete_branch")]


class TestCleanWorktree(unittest.TestCase):
    def test_clean_worktree_with_nothing_beyond_the_base_is_removed(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, _ = _world(git)

        _close(store, svc, item)

        self.assertEqual(store.get_node(item).state, "done")
        names = [c[0] for c in _removed(git)]
        self.assertEqual(names, ["remove_worktree", "delete_branch"])

    def test_branch_with_one_commit_beyond_the_base_is_refused(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, step = _world(git)

        with self.assertRaises(TeardownRefused) as ctx:
            _close(store, svc, item)

        self.assertIn(BRANCH, str(ctx.exception))
        self.assertEqual(_removed(git), [])
        self.assertNotEqual(store.get_node(item).state, "done")
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(len(store.open_runs_of(item)), 1)
        self.assertIn(BRANCH, store.get_node(step).park.reason)

    def test_base_falls_back_to_the_worktree_base(self):
        git = FakeGit(branches={(REPO, BRANCH)}, base="origin/master",
                      beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, _ = _world(git)

        with self.assertRaises(TeardownRefused):
            _close(store, svc, item)

        self.assertIn(("commits_beyond", REPO, "origin/master", BRANCH), git.calls)

    def test_no_base_found_refuses_an_existing_branch(self):
        git = FakeGit(branches={(REPO, BRANCH)})
        store, svc, item, _ = _world(git)

        with self.assertRaises(TeardownRefused) as ctx:
            _close(store, svc, item)

        self.assertIn("no base branch", str(ctx.exception))

    def test_a_failed_fetch_does_not_refuse_by_itself(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", fetch_ok=False)
        store, svc, item, _ = _world(git)

        _close(store, svc, item)

        self.assertEqual(store.get_node(item).state, "done")

    def test_branch_that_does_not_exist_is_not_checked(self):
        git = FakeGit(ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, _ = _world(git)

        _close(store, svc, item)

        self.assertEqual(store.get_node(item).state, "done")


class TestDirtyWorktree(unittest.TestCase):
    def test_dirty_worktree_is_left_in_place_naming_the_paths(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, step = _world(git)
        git._registered = {PATH % item}
        git._uncommitted = {PATH % item: ["a.py", "b/c.py"]}

        with self.assertRaises(TeardownRefused) as ctx:
            _close(store, svc, item)

        self.assertIn("a.py", str(ctx.exception))
        self.assertIn("b/c.py", str(ctx.exception))
        self.assertEqual(_removed(git), [])
        self.assertNotEqual(store.get_node(item).state, "done")
        self.assertEqual(len(store.open_runs_of(item)), 1)
        self.assertIn("a.py", store.get_node(step).park.reason)
        artifact = [a for a in store.item_artifacts(item) if a.type == TEARDOWN_REFUSED_ARTIFACT]
        self.assertEqual(len(artifact), 1)
        self.assertIn("a.py", artifact[0].value)

    def test_dirty_worktree_on_a_merged_run_is_still_refused(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, _ = _world(git, run_state=RunState.MERGED)
        git._registered = {PATH % item}
        git._uncommitted = {PATH % item: ["a.py"]}

        with self.assertRaises(TeardownRefused):
            _close(store, svc, item)

        self.assertEqual(_removed(git), [])

    def test_unreadable_status_refuses(self):
        git = FakeGit(raises={"uncommitted_paths"}, branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, _ = _world(git)
        git._registered = {PATH % item}

        with self.assertRaises(TeardownRefused):
            _close(store, svc, item)

        self.assertEqual(_removed(git), [])

    def test_unreadable_commits_refuse(self):
        git = FakeGit(raises={"commits_beyond"}, branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, _ = _world(git)

        with self.assertRaises(TeardownRefused):
            _close(store, svc, item)

        self.assertEqual(_removed(git), [])

    def test_a_second_refusal_does_not_stack_park_notes(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, step = _world(git)

        for _ in range(2):
            with self.assertRaises(TeardownRefused):
                _close(store, svc, item)

        notes = (store.get_node(step).notes or "").count("BLOCKED:")
        self.assertEqual(notes, 1)
        refusals = [a for a in store.item_artifacts(item) if a.type == TEARDOWN_REFUSED_ARTIFACT]
        self.assertEqual(len(refusals), 1)


class TestProofOfMerge(unittest.TestCase):
    def test_merged_run_with_commits_beyond_is_removed(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, _ = _world(git, run_state=RunState.MERGED)

        _close(store, svc, item)

        self.assertEqual(store.get_node(item).state, "done")
        self.assertNotIn("commits_beyond", [c[0] for c in git.calls])

    def test_run_whose_pr_is_in_merged_prs_is_removed(self):
        pr = "https://github.com/x/y/pull/1"
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, _ = _world(git, pr=pr)

        _close(store, svc, item, merged_prs=frozenset({pr}))

        self.assertEqual(store.get_node(item).state, "done")

    def test_run_whose_pr_is_not_in_merged_prs_is_refused(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, _ = _world(git, pr="https://github.com/x/y/pull/1")

        with self.assertRaises(TeardownRefused):
            _close(store, svc, item, merged_prs=frozenset({"https://github.com/x/y/pull/2"}))


class TestMixedWorktrees(unittest.TestCase):
    def test_clean_sibling_is_left_in_place_and_not_named(self):
        git = FakeGit(branches={(REPO, "feat/spec"), (REPO, BRANCH)}, ref="origin/main")
        store = FakeStore()
        item = store.create_item("story", "a description")
        store.add_artifact(item, "repo", REPO)
        pid = store.open_pass(item)
        clean = store.open_run(item, pid, "spec")
        dirty = store.open_run(item, pid, "code")
        store.set_branch(clean, "feat/spec")
        store.set_branch(dirty, BRANCH)
        store.create_step(step="finalise", role="agent", parent=item)
        svc = WorktreeService(store, git, fs=None, config=_Cfg())
        dirty_path = svc.path_for_run(store.get_run(dirty))
        clean_path = svc.path_for_run(store.get_run(clean))
        git._registered = {dirty_path, clean_path}
        git._uncommitted = {dirty_path: ["x.py"]}

        with self.assertRaises(TeardownRefused) as ctx:
            _close(store, svc, item)

        self.assertIn(dirty_path, str(ctx.exception))
        self.assertNotIn(clean_path, str(ctx.exception))
        self.assertEqual(_removed(git), [])


class TestCascadePath(unittest.TestCase):
    METAS = {"finaliser": {"model": "sonnet", "step": "finalise"}}

    def test_refused_cascade_records_the_artifact_and_a_later_close_succeeds(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, step = _world(git)

        resp = CompleteStepUseCase(store, FlowService(FakeFs(self.METAS), store), svc).execute(
            CompleteInput(step=step, outcome="done")
        )

        self.assertIn(BRANCH, resp.teardown_refusal)
        self.assertEqual(store.get_node(step).state, "done")
        self.assertNotEqual(store.get_node(item).state, "done")
        self.assertTrue(
            [a for a in store.item_artifacts(item) if a.type == TEARDOWN_REFUSED_ARTIFACT]
        )
        git._beyond = {}

        _close(store, svc, item)

        self.assertEqual(store.get_node(item).state, "done")
