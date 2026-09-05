import json
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work import (
    CloseItemInput,
    CloseItemUseCase,
    EditNodeInput,
    EditNodeUseCase,
    LinkArtifactInput,
    LinkArtifactUseCase,
    RemoveNodeInput,
    RemoveNodeUseCase,
)
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.ports.git import GitReadError
from lightcycle.ports.store import NodeNotFoundError
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

METAS = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}


def _add_reflection(store, node_id, feedback):
    store.add_artifact(
        node_id, "reflection", json.dumps({"step": node_id, "feedback": feedback, "spec_hash": "h"})
    )


class FakeGit:
    def __init__(self, repos=()):
        self._repos = set(repos)

    def is_git_repo(self, path):
        return path in self._repos


class FakeConfig:
    def __init__(self, projects="/projects"):
        self._projects = projects

    def projects_root(self):
        return self._projects

    def engine_root(self):
        return self._projects

    def branch_prefix(self):
        return "feat"


class FakeGitRemove:
    def __init__(self, repos=()):
        self._repos = set(repos)
        self.remote_deletes = []

    def is_git_repo(self, path):
        return path in self._repos

    def remove_worktree(self, root, path):
        pass

    def delete_branch(self, root, branch):
        pass

    def delete_remote_branch(self, root, branch):
        self.remote_deletes.append((root, branch))


class _RaisingFlow:
    def workspace_for_node(self, node):
        raise ValueError("workflow 'lightcycle/spec-driven' is not a pin '<origin>/<name>@<sha>'")

    def phase_for(self, node):
        raise ValueError("workflow 'lightcycle/spec-driven' is not a pin '<origin>/<name>@<sha>'")


class FakeWorktrees:
    def release_run(self, run, delete_remote=True):
        self.released = getattr(self, "released", [])
        self.released.append(run.id)

    def __init__(self):
        self.removed = []

    def remove(self, item):
        self.removed.append(item)


class FakeWorktreesForRemove:
    def __init__(self, target="/projects/app", has_repo=True, has_worktree_history=True):
        self._target = target
        self._has_repo = has_repo
        self._has_worktree_history = has_worktree_history
        self.removed = []

    def has_repo(self, item):
        return self._has_repo

    def has_worktree_history(self, item):
        return self._has_worktree_history

    def target_repo(self, item):
        return self._target

    def worktree_path(self, item):
        return "/projects/app/.worktrees/%s" % item

    def remove(self, item):
        self.removed.append(item)


class FakeWorkersForRemove:
    def __init__(self, workers=None, alive_pids=()):
        self._workers = workers or []
        self._alive = set(alive_pids)

    def workers_state(self):
        return self._workers

    def pid_alive(self, pid, started=None):
        return pid in self._alive


class FakeGitForRemove:
    def __init__(self, registered=(), dirty=()):
        self._registered = set(registered)
        self._dirty = set(dirty)

    def worktree_registered(self, root, path):
        return path in self._registered

    def has_uncommitted(self, path):
        return path in self._dirty


class RaisingGitForRemove:
    def worktree_registered(self, root, path):
        raise AssertionError("worktree_registered should not be called")

    def has_uncommitted(self, path):
        raise AssertionError("has_uncommitted should not be called")


class UnreadableGitForRemove:
    def __init__(self, fails="worktree_registered"):
        self._fails = fails

    def worktree_registered(self, root, path):
        if self._fails == "worktree_registered":
            raise GitReadError("git worktree list failed in %s: fatal: not a git repository" % root)
        return True

    def has_uncommitted(self, path):
        if self._fails == "has_uncommitted":
            raise GitReadError("git status failed in %s: fatal: not a git repository" % path)
        raise AssertionError("has_uncommitted should not be called")


class TestEditNode(unittest.TestCase):
    def test_edits_an_items_title_and_description(self):
        s = FakeStore()
        tid = s.create_item("old title", "old")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, title="new title", description="new"))
        t = s.get_item(tid)
        self.assertEqual(t.title, "new title")
        self.assertEqual(t.description, "new")

    def test_edits_a_steps_title(self):
        s = FakeStore()
        tid = s.create_step("old title", role="human")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, title="new title"))
        self.assertEqual(s.get_step(tid).title, "new title")

    def test_unspecified_fields_unchanged(self):
        s = FakeStore()
        tid = s.create_item("keep title", "keep desc")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, project="p1"))
        t = s.get_item(tid)
        self.assertEqual(t.title, "keep title")
        self.assertEqual(t.description, "keep desc")

    def test_a_description_does_not_land_on_a_step(self):
        s = FakeStore()
        tid = s.create_step("a step", role="human")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, description="nope"))
        self.assertFalse(hasattr(s.get_step(tid), "description"))

class TestLinkArtifact(unittest.TestCase):
    def test_appends_artifact(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="design", value="http://x/1", label="PR 1")
        )
        arts = s.item_artifacts(sid)
        self.assertEqual(arts[0].type, "design")
        self.assertEqual(arts[0].value, "http://x/1")
        self.assertEqual(arts[0].label, "PR 1")

    def test_empty_value_raises_and_writes_no_orphan(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="design", value="")
            )
        self.assertEqual(s.item_artifacts(sid), [])

    def test_replace_empty_value_raises_and_leaves_original(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="spec", value="specs/old.md")
        )
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="spec", value="", replace=True)
            )
        arts = s.item_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].value, "specs/old.md")

    def test_repo_empty_value_raises_and_leaves_repo_unset(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="repo", value="")
            )
        self.assertIsNone(s.get_item(sid).repo)

    def test_repo_empty_value_raises_and_leaves_existing_repo_unchanged(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="repo", value="widget")
        )
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="repo", value="")
            )
        self.assertEqual(s.get_item(sid).repo, "widget")

    def test_run_field_empty_pr_raises_and_leaves_run_unchanged(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), "spec")
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="pr", value="")
            )
        self.assertIsNone(s.get_run(rid).pr)

    def test_run_field_empty_branch_raises_and_leaves_run_unchanged(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), "spec")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="branch", value="grid/x")
        )
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="branch", value="")
            )
        self.assertEqual(s.get_run(rid).branch, "grid/x")

    def test_run_field_empty_comments_handled_raises_and_leaves_run_unchanged(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), "spec")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="comments-handled", value="1700000000")
        )
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="comments-handled", value="")
            )
        self.assertEqual(s.get_run(rid).comments_handled_through, "1700000000")

    def test_empty_spec_value_raises_before_project_mismatch_check(self):
        s = FakeStore()
        s.add_project("acme/widget", local_path="/tmp/widget")
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="repo", value="widget")
        )
        with self.assertRaises(UseCaseError) as ctx:
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="spec", value="")
            )
        message = str(ctx.exception)
        self.assertNotIn("not a registered project", message)

    def test_replace_replaces_same_type_artifact(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="spec", value="specs/old.md")
        )
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="spec", value="specs/new.md", replace=True)
        )
        arts = s.item_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].value, "specs/new.md")

    def test_declared_kind_is_persisted(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="design", value="http://x/1", kind="something-explicit")
        )
        self.assertEqual(s.item_artifacts(sid)[0].kind, "something-explicit")

    def test_undeclared_kind_resolves_from_type_default(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="design", value="http://x/1")
        )
        self.assertEqual(s.item_artifacts(sid)[0].kind, "text")

    def test_internal_defaults_false(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="design", value="http://x/1")
        )
        self.assertFalse(s.item_artifacts(sid)[0].internal)

    def test_internal_true_is_persisted(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="design", value="http://x/1", internal=True)
        )
        self.assertTrue(s.item_artifacts(sid)[0].internal)

    def test_spec_with_worktrees_segment_raises(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(
                    item=sid, atype="spec",
                    value="/home/u/specs/.worktrees/LC-1-spec/widget/LC-1.md",
                )
            )
        self.assertEqual(s.item_artifacts(sid), [])

    def test_spec_under_unregistered_directory_raises_naming_it(self):
        s = FakeStore()
        s.add_project("acme/widget", local_path="/tmp/widget")
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="repo", value="widget")
        )
        with self.assertRaises(UseCaseError) as ctx:
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="spec", value="nowhere/LC-1.md")
            )
        self.assertIn("nowhere", str(ctx.exception))

    def test_spec_under_a_different_registered_project_raises_naming_both(self):
        s = FakeStore()
        s.add_project("acme/widget", local_path="/tmp/widget")
        s.add_project("acme/gadget", local_path="/tmp/gadget")
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="repo", value="widget")
        )
        with self.assertRaises(UseCaseError) as ctx:
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="spec", value="gadget/LC-1.md")
            )
        message = str(ctx.exception)
        self.assertIn("gadget", message)
        self.assertIn("acme/widget", message)

    def test_spec_bare_directory_against_owner_name_repo_succeeds(self):
        s = FakeStore()
        s.add_project("acme/lightcycle", local_path="/tmp/lc")
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="repo", value="lightcycle")
        )
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="spec", value="lightcycle/LC-1.md")
        )
        self.assertEqual(next(a.value for a in s.item_artifacts(sid) if a.type == "spec"), "lightcycle/LC-1.md")

    def test_spec_owner_name_directory_against_bare_repo_succeeds(self):
        s = FakeStore()
        s.add_project("acme/lightcycle", local_path="/tmp/lc")
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="repo", value="acme/lightcycle")
        )
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="spec", value="lightcycle/LC-1.md")
        )
        self.assertEqual(next(a.value for a in s.item_artifacts(sid) if a.type == "spec"), "lightcycle/LC-1.md")

    def test_spec_on_item_with_no_repo_artifact_succeeds_regardless_of_directory(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="spec", value="anywhere/LC-1.md")
        )
        self.assertEqual(s.item_artifacts(sid)[0].value, "anywhere/LC-1.md")

    def test_spec_on_item_with_unresolvable_repo_artifact_succeeds_regardless_of_directory(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="repo", value="unregistered")
        )
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="spec", value="anywhere/LC-1.md")
        )
        self.assertEqual(next(a.value for a in s.item_artifacts(sid) if a.type == "spec"), "anywhere/LC-1.md")

    def test_replace_with_worktrees_segment_raises_and_leaves_original(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="spec", value="specs/old.md")
        )
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(
                    item=sid, atype="spec",
                    value="/home/u/specs/.worktrees/LC-1-spec/widget/LC-1.md",
                    replace=True,
                )
            )
        arts = s.item_artifacts(sid)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].value, "specs/old.md")

    def test_run_field_on_a_step_id_raises_and_writes_no_orphan(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        tid = s.create_step("t", parent=sid)
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=tid, atype="pr", value="http://x/1")
            )
        self.assertEqual(s.item_artifacts(sid), [])
        self.assertEqual(s.item_artifacts(tid), [])

    def test_run_field_on_an_item_with_no_open_run_raises_and_writes_no_orphan(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        with self.assertRaises(UseCaseError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item=sid, atype="branch", value="grid/x")
            )
        self.assertEqual(s.item_artifacts(sid), [])

    def test_run_field_on_an_item_with_an_open_run_routes_to_the_run(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), "spec")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="comments-handled", value="1700000000")
        )
        self.assertEqual(s.get_run(rid).comments_handled_through, "1700000000")
        self.assertEqual(s.item_artifacts(sid), [])

    def test_run_field_on_an_unknown_id_raises_node_not_found(self):
        s = FakeStore()
        with self.assertRaises(NodeNotFoundError):
            LinkArtifactUseCase(s).execute(
                LinkArtifactInput(item="LC-999", atype="pr", value="http://x/1")
            )


class TestCloseItem(unittest.TestCase):
    def test_closes_story_open_children_and_removes_worktree(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        k = s.create_step("build: x", step="build", role="agent", parent=sid)
        wt = FakeWorktrees()
        CloseItemUseCase(s, wt).execute(CloseItemInput(item=sid, reason="merged"))
        self.assertEqual(s.get_node(sid).state, "done")
        self.assertEqual(s.get_node(k).state, "done")
        self.assertEqual(wt.removed, [sid])

    def test_closes_linked_backlog_item_on_item_close(self):
        s = FakeStore()
        backlog = s.create_step("a backlog item", role="human")
        sid = s.create_item("st", "a description")
        s.add_artifact(sid, "resolves", backlog)
        wt = FakeWorktrees()
        CloseItemUseCase(s, wt).execute(CloseItemInput(item=sid, reason="merged"))
        self.assertEqual(s.get_node(backlog).state, "done")
        self.assertEqual(
            [(a.type, a.value) for a in s.item_artifacts(backlog)], [("resolved-by", sid)]
        )

    def test_no_backlog_link_on_item_close_is_unaffected(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        wt = FakeWorktrees()
        CloseItemUseCase(s, wt).execute(CloseItemInput(item=sid, reason="merged"))
        self.assertEqual(s.get_node(sid).state, "done")

    def test_closes_a_never_activated_backlogged_item_without_crashing(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        wt = WorktreeService(s, FakeGit(), FakeFs(), FakeConfig(), flow=_RaisingFlow())
        CloseItemUseCase(s, wt).execute(CloseItemInput(item=sid, reason="wontfix"))
        self.assertEqual(s.get_node(sid).state, "done")


class TestCloseItemBacklogResolution(unittest.TestCase):
    def test_closes_every_linked_backlog_item_on_item_close(self):
        s = FakeStore()
        b1 = s.create_step("a backlog item", role="human")
        b2 = s.create_step("another backlog item", role="human")
        item = s.create_item("my item", "a description")
        s.add_artifact(item, "resolves", b1)
        s.add_artifact(item, "resolves", b2)
        _close_item(s, item)
        self.assertEqual(s.get_node(b1).state, "done")
        self.assertEqual(s.get_node(b2).state, "done")
        self.assertEqual(
            [(a.type, a.value) for a in s.item_artifacts(b1)], [("resolved-by", item)]
        )

    def test_already_done_backlog_item_is_left_alone(self):
        s = FakeStore()
        backlog = s.create_step("a backlog item", role="human")
        item = s.create_item("my item", "a description")
        s.add_artifact(item, "resolves", backlog)
        s.close(backlog, "already handled")
        _close_item(s, item)
        self.assertEqual(s.get_node(backlog).outcome, "already handled")
        self.assertEqual(s.item_artifacts(backlog), [])

    def test_no_backlog_link_is_a_no_op(self):
        s = FakeStore()
        item = s.create_item("my item", "a description")
        _close_item(s, item)
        self.assertEqual(s.get_node(item).state, "done")


def _close_item(store, item):
    CloseItemUseCase(
        store, WorktreeService(store, FakeGit(), FakeFs(), FakeConfig())
    ).execute(CloseItemInput(item=item, reason="done"))


class TestWorktreeServiceItemBranch(unittest.TestCase):
    def test_none_then_the_runs_branch(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        svc = WorktreeService(s, None, None, None)
        self.assertIsNone(svc.item_branch(sid))
        rid = s.open_run(sid, s.open_pass(sid), None)
        s.set_run_field(rid, branch="feat/x")
        self.assertEqual(svc.item_branch(sid), "feat/x")


class TestWorktreeServiceBranchFor(unittest.TestCase):
    def test_no_branch_artifact_falls_back_to_id_slug(self):
        s = FakeStore()
        sid = s.create_item("Branch name is the entire item title slugified (100+ chars); use the item id " "or a short truncated slug", "a description")
        svc = WorktreeService(s, None, None, FakeConfig())
        branch = svc._branch_for(sid)
        self.assertTrue(branch.startswith("feat/%s-" % sid))
        self.assertLessEqual(len(branch), len("feat/%s-" % sid) + 40)

    def test_the_open_runs_branch_wins(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), None)
        s.set_run_field(rid, branch="feat/custom-branch")
        svc = WorktreeService(s, None, None, FakeConfig())
        self.assertEqual(svc._branch_for(sid), "feat/custom-branch")


class TestWorktreeServiceRemove(unittest.TestCase):
    def test_remove_requests_remote_branch_delete(self):
        s = FakeStore()
        sid = s.create_item("my item", "a description")
        s.add_project("acme/app", local_path="/projects/app")
        s.add_artifact(sid, "repo", "app")
        rid = s.open_run(sid, s.open_pass(sid), None)
        s.set_run_field(rid, branch="feat/my-branch")
        git = FakeGitRemove(repos={"/projects/app"})
        svc = WorktreeService(s, git, FakeFs(), FakeConfig("/projects"))
        svc.remove(sid)
        self.assertIn(("/projects/app", "feat/my-branch"), git.remote_deletes)

    def test_remove_skips_remote_delete_when_not_git_repo(self):
        s = FakeStore()
        sid = s.create_item("my item", "a description")
        s.add_project("acme/app", local_path="/projects/app")
        s.add_artifact(sid, "repo", "app")
        s.add_artifact(sid, "branch", "feat/my-branch")
        git = FakeGitRemove(repos=set())
        svc = WorktreeService(s, git, FakeFs(), FakeConfig("/projects"))
        svc.remove(sid)
        self.assertEqual(git.remote_deletes, [])

    def test_remove_is_a_noop_without_a_repo_artifact(self):
        s = FakeStore()
        sid = s.create_item("my item", "a description")
        svc = WorktreeService(s, git=None, fs=FakeFs(), config=FakeConfig("/projects"))
        svc.remove(sid)


class TestRemoveNode(unittest.TestCase):
    def test_refuses_when_a_claimed_step_is_covered_by_a_live_worker(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkersForRemove(
            workers=[{"spawnid": "live-sp", "pid": 111, "step": step, "started": 100}],
            alive_pids={111},
        )
        wt = FakeWorktreesForRemove()
        git = FakeGitForRemove()
        with self.assertRaises(UseCaseError) as ctx:
            RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id=item))
        self.assertIn(step, str(ctx.exception))
        self.assertEqual(s.get_node(item).id, item)

    def test_refuses_when_worktree_is_dirty(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove()
        path = wt.worktree_path(item)
        git = FakeGitForRemove(registered={path}, dirty={path})
        with self.assertRaises(UseCaseError) as ctx:
            RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id=item))
        self.assertIn(item, str(ctx.exception))
        self.assertEqual(wt.removed, [])
        self.assertEqual(s.get_node(item).id, item)

    def test_refuses_when_worktree_registered_check_is_unreadable(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove()
        git = UnreadableGitForRemove(fails="worktree_registered")
        with self.assertRaises(UseCaseError) as ctx:
            RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id=item))
        self.assertIn(item, str(ctx.exception))
        self.assertEqual(wt.removed, [])
        self.assertEqual(s.get_node(item).id, item)

    def test_refuses_when_has_uncommitted_check_is_unreadable(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove()
        git = UnreadableGitForRemove(fails="has_uncommitted")
        with self.assertRaises(UseCaseError) as ctx:
            RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id=item))
        self.assertIn(item, str(ctx.exception))
        self.assertEqual(wt.removed, [])
        self.assertEqual(s.get_node(item).id, item)

    def test_force_overrides_an_unreadable_worktree(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove()
        git = UnreadableGitForRemove(fails="worktree_registered")
        resp = RemoveNodeUseCase(s, workers, wt, git).execute(
            RemoveNodeInput(id=item, force=True)
        )
        self.assertTrue(resp.worktree_removed)
        self.assertEqual(wt.removed, [item])
        with self.assertRaises(KeyError):
            s.get_node(item)

    def test_stale_claim_does_not_block(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove()
        git = FakeGitForRemove()
        RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id=item))
        with self.assertRaises(KeyError):
            s.get_node(item)
        with self.assertRaises(KeyError):
            s.get_node(step)

    def test_success_path_removes_worktree_and_step_rows(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove()
        git = FakeGitForRemove()
        resp = RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id=item))
        self.assertEqual(resp.steps_removed, 1)
        self.assertTrue(resp.worktree_removed)
        self.assertEqual(wt.removed, [item])
        with self.assertRaises(KeyError):
            s.get_node(item)
        with self.assertRaises(KeyError):
            s.get_node(step)

    def test_force_overrides_dirty_worktree(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove()
        path = wt.worktree_path(item)
        git = FakeGitForRemove(registered={path}, dirty={path})
        resp = RemoveNodeUseCase(s, workers, wt, git).execute(
            RemoveNodeInput(id=item, force=True)
        )
        self.assertTrue(resp.worktree_removed)
        self.assertEqual(wt.removed, [item])
        with self.assertRaises(KeyError):
            s.get_node(item)

    def test_force_still_refuses_a_genuinely_live_worker(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        step = s.create_step("build: feature", step="build", role="agent", parent=item)
        s.update_state(step, "in_progress")
        workers = FakeWorkersForRemove(
            workers=[{"spawnid": "live-sp", "pid": 111, "step": step, "started": 100}],
            alive_pids={111},
        )
        wt = FakeWorktreesForRemove()
        git = FakeGitForRemove()
        with self.assertRaises(UseCaseError):
            RemoveNodeUseCase(s, workers, wt, git).execute(
                RemoveNodeInput(id=item, force=True)
            )

    def test_repo_less_item_is_never_dirty_and_removes_cleanly(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove(has_repo=False)
        git = FakeGitForRemove(registered={wt.worktree_path(item)}, dirty={wt.worktree_path(item)})
        resp = RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id=item))
        self.assertTrue(resp.worktree_removed)
        self.assertEqual(wt.removed, [item])

    def test_missing_node_is_a_clear_error(self):
        s = FakeStore()
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove()
        git = FakeGitForRemove()
        with self.assertRaises(UseCaseError):
            RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id="nope"))

    def test_never_activated_item_is_not_treated_as_dirty(self):
        s = FakeStore()
        item = s.create_item("feature", "a description")
        workers = FakeWorkersForRemove()
        wt = FakeWorktreesForRemove(has_worktree_history=False)
        git = RaisingGitForRemove()
        resp = RemoveNodeUseCase(s, workers, wt, git).execute(RemoveNodeInput(id=item))
        self.assertTrue(resp.worktree_removed)
        with self.assertRaises(KeyError):
            s.get_node(item)


if __name__ == "__main__":
    unittest.main()
