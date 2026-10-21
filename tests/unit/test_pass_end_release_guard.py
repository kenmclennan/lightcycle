import unittest

from lightcycle.application.flow import CompleteInput, CompleteStepUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.domain.runs import RunState
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore

REPO = "/elsewhere/app"
BRANCH = "feat/app-x"
METAS = {"finaliser": {"model": "sonnet", "step": "finalise"}}


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


class _PassEndFlow(FlowService):
    def ends_pass(self, stage, outcome, name=None):
        return stage == "finalise" and outcome == "done"


def _world(git, branches=((BRANCH, "code"),)):
    store = FakeStore()
    item = store.create_item("story", "a description")
    store.add_artifact(item, "repo", REPO)
    pid = store.open_pass(item)
    runs = []
    for branch, phase in branches:
        rid = store.open_run(item, pid, phase)
        store.set_branch(rid, branch)
        runs.append(rid)
    step = store.create_step(stage="finalise", role="agent", item=item)
    svc = WorktreeService(store, git, fs=None, config=_Cfg())
    return store, svc, item, step, runs, pid


def _complete(store, svc, step):
    return CompleteStepUseCase(store, _PassEndFlow(FakeFs(METAS), store), svc).execute(
        CompleteInput(step=step, outcome="done")
    )


def _removed(git):
    return [c for c in git.calls if c[0] in ("remove_worktree", "delete_branch")]


class TestPassEndRelease(unittest.TestCase):
    def test_clean_run_with_nothing_beyond_the_base_is_released(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, step, runs, pid = _world(git)

        resp = _complete(store, svc, step)

        self.assertIsNone(resp.teardown_refusal)
        self.assertEqual(store.get_node(step).state, "done")
        self.assertEqual(store.open_runs_of(item, pid), [])
        self.assertIn("remove_worktree", [c[0] for c in _removed(git)])

    def test_dirty_worktree_refuses_the_pass_end_and_removes_nothing(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, step, runs, pid = _world(git)
        path = svc.path_for_run(store.get_run(runs[0]))
        git._registered = {path}
        git._uncommitted = {path: ["a.py", "b/c.py"]}

        resp = _complete(store, svc, step)

        self.assertIn("a.py, b/c.py", resp.teardown_refusal)
        self.assertIn("cannot end the pass", resp.teardown_refusal)
        self.assertIsNone(resp.next_step)
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(len(store.open_runs_of(item, pid)), 1)
        self.assertEqual(_removed(git), [])
        park = store.get_node(step).park
        self.assertIn("a.py, b/c.py", park.reason)
        self.assertIn("lc done", park.needs)
        self.assertTrue(park.reason.startswith("pass end refused:"))

    def test_open_run_one_commit_beyond_the_base_is_refused_naming_the_branch(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, step, runs, pid = _world(git)

        resp = _complete(store, svc, step)

        self.assertIn(BRANCH, resp.teardown_refusal)
        self.assertEqual(_removed(git), [])
        self.assertNotEqual(store.get_node(step).state, "done")

    def test_open_run_with_zero_commits_beyond_the_base_proceeds(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): []})
        store, svc, item, step, runs, pid = _world(git)

        resp = _complete(store, svc, step)

        self.assertIsNone(resp.teardown_refusal)
        self.assertEqual(store.get_node(step).state, "done")

    def test_merged_run_with_commits_beyond_the_base_proceeds(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main", beyond={(REPO, BRANCH): ["a1"]})
        store, svc, item, step, runs, pid = _world(git)
        store.close_run(runs[0], RunState.MERGED)
        svc_runs = [store.get_run(runs[0])]

        self.assertEqual(svc.pass_release_refusals(item, svc_runs), [])

    def test_clean_and_dirty_runs_are_both_kept_and_only_the_dirty_one_is_named(self):
        git = FakeGit(branches={(REPO, "feat/spec"), (REPO, BRANCH)}, ref="origin/main")
        store, svc, item, step, runs, pid = _world(
            git, branches=(("feat/spec", "spec"), (BRANCH, "code"))
        )
        clean_path = svc.path_for_run(store.get_run(runs[0]))
        dirty_path = svc.path_for_run(store.get_run(runs[1]))
        git._registered = {clean_path, dirty_path}
        git._uncommitted = {dirty_path: ["x.py"]}

        resp = _complete(store, svc, step)

        self.assertIn(dirty_path, resp.teardown_refusal)
        self.assertNotIn(clean_path, resp.teardown_refusal)
        self.assertEqual(_removed(git), [])
        self.assertEqual(len(store.open_runs_of(item, pid)), 2)

    def test_unreadable_git_state_refuses_the_pass_end(self):
        for method in ("uncommitted_paths", "commits_beyond"):
            with self.subTest(method=method):
                git = FakeGit(
                    branches={(REPO, BRANCH)}, ref="origin/main", raises={method}
                )
                store, svc, item, step, runs, pid = _world(git)
                git._registered = {svc.path_for_run(store.get_run(runs[0]))}

                resp = _complete(store, svc, step)

                self.assertIn("could not read", resp.teardown_refusal)
                self.assertEqual(_removed(git), [])

    def test_completing_twice_over_a_dirty_tree_leaves_one_park_note(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, step, runs, pid = _world(git)
        path = svc.path_for_run(store.get_run(runs[0]))
        git._registered = {path}
        git._uncommitted = {path: ["a.py"]}

        _complete(store, svc, step)
        _complete(store, svc, step)

        notes = store._get(step).get("notes") or ""
        self.assertEqual(notes.count("BLOCKED:"), 1)

    def test_no_teardown_refused_artifact_is_written(self):
        git = FakeGit(branches={(REPO, BRANCH)}, ref="origin/main")
        store, svc, item, step, runs, pid = _world(git)
        path = svc.path_for_run(store.get_run(runs[0]))
        git._registered = {path}
        git._uncommitted = {path: ["a.py"]}

        _complete(store, svc, step)

        self.assertEqual(
            [a for a in store.item_artifacts(item) if a.type == "teardown-refused"], []
        )
