import json
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work import (
    AddItemInput,
    AddItemUseCase,
    CloseThemeInput,
    CloseThemeUseCase,
    CloseItemInput,
    CloseItemUseCase,
    EditNodeInput,
    EditNodeUseCase,
    LinkArtifactInput,
    LinkArtifactUseCase,
)
from lightcycle.application.services.worktree import WorktreeService
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


class FakeWorktrees:
    def __init__(self):
        self.removed = []

    def remove(self, item):
        self.removed.append(item)


class TestAddTask(unittest.TestCase):
    def test_creates_human_task_with_labels(self):
        s = FakeStore()
        resp = AddItemUseCase(s).execute(AddItemInput(title="do a thing", goal="g1", project="p1"))
        t = s.get_node(resp.step)
        self.assertEqual(t.state, "ready")
        self.assertEqual(t.role, "human")
        self.assertEqual(t.goal, "g1")
        self.assertEqual(t.project, "p1")

    def test_creates_task_with_description(self):
        s = FakeStore()
        resp = AddItemUseCase(s).execute(
            AddItemInput(title="my step", description="detailed notes")
        )
        t = s.get_node(resp.step)
        self.assertEqual(t.description, "detailed notes")

    def test_creates_task_without_description(self):
        s = FakeStore()
        resp = AddItemUseCase(s).execute(AddItemInput(title="plain step"))
        t = s.get_node(resp.step)
        self.assertIsNone(t.description)


class TestEditNode(unittest.TestCase):
    def test_edits_title_and_description(self):
        s = FakeStore()
        tid = s.create_step("old title", role="human", description="old")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, title="new title", description="new"))
        t = s.get_node(tid)
        self.assertEqual(t.title, "new title")
        self.assertEqual(t.description, "new")

    def test_edits_goal_and_project(self):
        s = FakeStore()
        tid = s.create_step("t", role="human", goal="g1", project="p1")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, goal="g2", project="p2"))
        t = s.get_node(tid)
        self.assertEqual(t.goal, "g2")
        self.assertEqual(t.project, "p2")

    def test_unspecified_fields_unchanged(self):
        s = FakeStore()
        tid = s.create_step("keep title", role="human", description="keep desc", goal="g1")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, project="p1"))
        t = s.get_node(tid)
        self.assertEqual(t.title, "keep title")
        self.assertEqual(t.description, "keep desc")
        self.assertEqual(t.goal, "g1")
        self.assertEqual(t.project, "p1")

    def test_edits_parent_alone(self):
        s = FakeStore()
        theme = s.create_theme("my theme")
        tid = s.create_step("a step", role="human")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, parent=theme))
        t = s.get_node(tid)
        self.assertEqual(t.parent, theme)

    def test_edits_parent_and_title_together(self):
        s = FakeStore()
        theme = s.create_theme("my theme")
        tid = s.create_step("old title", role="human")
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, title="new title", parent=theme))
        t = s.get_node(tid)
        self.assertEqual(t.title, "new title")
        self.assertEqual(t.parent, theme)

    def test_omitting_parent_leaves_parentage_unchanged(self):
        s = FakeStore()
        theme = s.create_theme("my theme")
        tid = s.create_step("a step", role="human", parent=theme)
        EditNodeUseCase(s).execute(EditNodeInput(step=tid, title="renamed"))
        t = s.get_node(tid)
        self.assertEqual(t.parent, theme)


class TestLinkArtifact(unittest.TestCase):
    def test_appends_artifact(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(item=sid, atype="pr", value="http://x/1", label="PR 1")
        )
        arts = s.item_artifacts(sid)
        self.assertEqual(arts[0].type, "pr")
        self.assertEqual(arts[0].value, "http://x/1")
        self.assertEqual(arts[0].label, "PR 1")


class TestCloseItem(unittest.TestCase):
    def test_closes_story_open_children_and_removes_worktree(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        k = s.create_step("build: x", step="build", role="coder", parent=sid)
        wt = FakeWorktrees()
        CloseItemUseCase(s, wt).execute(CloseItemInput(item=sid, reason="merged"))
        self.assertEqual(s.get_node(sid).state, "done")
        self.assertEqual(s.get_node(k).state, "done")
        self.assertEqual(wt.removed, [sid])


class TestCloseEpic(unittest.TestCase):
    def test_closes_epic_when_all_children_closed(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        child = s.create_item("item", theme=theme)
        s.close(child, "merged")
        CloseThemeUseCase(s).execute(CloseThemeInput(theme=theme, reason="done"))
        self.assertEqual(s.get_node(theme).state, "done")

    def test_refuses_with_open_child_and_names_it(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        child = s.create_item("item", theme=theme)
        with self.assertRaises(UseCaseError) as ctx:
            CloseThemeUseCase(s).execute(CloseThemeInput(theme=theme, reason="done"))
        self.assertIn(child, str(ctx.exception))
        self.assertEqual(s.get_node(theme).state, "ready")

    def test_refuses_leaves_epic_open_with_mixed_children(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        closed = s.create_item("done item", theme=theme)
        open_ = s.create_item("open item", theme=theme)
        s.close(closed, "merged")
        with self.assertRaises(UseCaseError) as ctx:
            CloseThemeUseCase(s).execute(CloseThemeInput(theme=theme, reason="done"))
        self.assertIn(open_, str(ctx.exception))
        self.assertNotIn(closed, str(ctx.exception))
        self.assertEqual(s.get_node(theme).state, "in_progress")

    def test_closing_theme_attaches_no_retro_artifact(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        item = s.create_item("child item", theme=theme)
        step = s.create_step("build: x", step="build", role="coder", parent=item)
        _add_reflection(s, step, "useful feedback")
        s.close(item, "merged")
        CloseThemeUseCase(s).execute(CloseThemeInput(theme=theme, reason="done"))
        self.assertEqual([a for a in s.item_artifacts(theme) if a.type == "retro"], [])


class TestCloseEpicBacklogResolution(unittest.TestCase):
    def test_closes_linked_backlog_item_on_theme_close(self):
        s = FakeStore()
        backlog = s.create_step("a backlog item", role="human")
        theme = s.create_theme("my theme")
        s.add_artifact(theme, "backlog", backlog)
        child = s.create_item("item", theme=theme)
        s.close(child, "merged")
        CloseThemeUseCase(s).execute(CloseThemeInput(theme=theme, reason="done"))
        self.assertEqual(s.get_node(backlog).state, "done")

    def test_no_backlog_link_is_a_no_op(self):
        s = FakeStore()
        theme = s.create_theme("my theme")
        child = s.create_item("item", theme=theme)
        s.close(child, "merged")
        CloseThemeUseCase(s).execute(CloseThemeInput(theme=theme, reason="done"))
        self.assertEqual(s.get_node(theme).state, "done")


class TestWorktreeServiceItemBranch(unittest.TestCase):
    def test_none_then_branch_artifact(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        svc = WorktreeService(s, None, None, None)
        self.assertIsNone(svc.item_branch(sid))
        s.add_artifact(sid, "branch", "feat/x")
        self.assertEqual(svc.item_branch(sid), "feat/x")


class TestWorktreeServiceBranchFor(unittest.TestCase):
    def test_no_branch_artifact_falls_back_to_id_slug(self):
        s = FakeStore()
        sid = s.create_item(
            "Branch name is the entire item title slugified (100+ chars); use the item id "
            "or a short truncated slug",
            theme=s.create_theme("theme"),
        )
        svc = WorktreeService(s, None, None, FakeConfig())
        branch = svc._branch_for(sid)
        self.assertTrue(branch.startswith("feat/%s-" % sid))
        self.assertLessEqual(len(branch), len("feat/%s-" % sid) + 40)

    def test_existing_branch_artifact_wins(self):
        s = FakeStore()
        sid = s.create_item("st", theme=s.create_theme("theme"))
        s.add_artifact(sid, "branch", "feat/custom-branch")
        svc = WorktreeService(s, None, None, FakeConfig())
        self.assertEqual(svc._branch_for(sid), "feat/custom-branch")


class TestWorktreeServiceRemove(unittest.TestCase):
    def test_remove_requests_remote_branch_delete(self):
        s = FakeStore()
        sid = s.create_item("my item", theme=s.create_theme("theme"))
        s.add_artifact(sid, "repo", "app")
        s.add_artifact(sid, "branch", "feat/my-branch")
        git = FakeGitRemove(repos={"/projects/app"})
        svc = WorktreeService(s, git, FakeFs(), FakeConfig("/projects"))
        svc.remove(sid)
        self.assertIn(("/projects/app", "feat/my-branch"), git.remote_deletes)

    def test_remove_skips_remote_delete_when_not_git_repo(self):
        s = FakeStore()
        sid = s.create_item("my item", theme=s.create_theme("theme"))
        s.add_artifact(sid, "repo", "app")
        s.add_artifact(sid, "branch", "feat/my-branch")
        git = FakeGitRemove(repos=set())
        svc = WorktreeService(s, git, FakeFs(), FakeConfig("/projects"))
        svc.remove(sid)
        self.assertEqual(git.remote_deletes, [])


if __name__ == "__main__":
    unittest.main()
