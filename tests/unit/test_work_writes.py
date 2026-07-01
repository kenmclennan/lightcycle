import unittest

from the_grid.application.errors import UseCaseError
from the_grid.application.work import (AddTaskInput, AddTaskUseCase, CloseStoryInput,
                                       CloseStoryUseCase, EditTaskInput, EditTaskUseCase,
                                       FileStoryInput, FileStoryUseCase,
                                       LinkArtifactInput, LinkArtifactUseCase)
from the_grid.application.services.flow import FlowService
from the_grid.application.services.worktree import WorktreeService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

METAS = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}


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


class FakeWorktrees:
    def __init__(self):
        self.removed = []

    def remove(self, story):
        self.removed.append(story)


class TestAddTask(unittest.TestCase):
    def test_creates_human_task_with_labels(self):
        s = FakeStore()
        resp = AddTaskUseCase(s).execute(AddTaskInput(title="do a thing", goal="g1", project="p1"))
        t = s.get_task(resp.task)
        self.assertEqual(t.status, "needs-human")
        self.assertEqual(t.goal, "g1")
        self.assertEqual(t.project, "p1")

    def test_creates_task_with_description(self):
        s = FakeStore()
        resp = AddTaskUseCase(s).execute(
            AddTaskInput(title="my task", description="detailed notes"))
        t = s.get_task(resp.task)
        self.assertEqual(t.description, "detailed notes")

    def test_creates_task_without_description(self):
        s = FakeStore()
        resp = AddTaskUseCase(s).execute(AddTaskInput(title="plain task"))
        t = s.get_task(resp.task)
        self.assertIsNone(t.description)


class TestEditTask(unittest.TestCase):
    def test_edits_title_and_description(self):
        s = FakeStore()
        tid = s.create_task("old title", role="human", description="old")
        EditTaskUseCase(s).execute(EditTaskInput(task=tid, title="new title", description="new"))
        t = s.get_task(tid)
        self.assertEqual(t.title, "new title")
        self.assertEqual(t.description, "new")

    def test_edits_goal_and_project(self):
        s = FakeStore()
        tid = s.create_task("t", role="human", goal="g1", project="p1")
        EditTaskUseCase(s).execute(EditTaskInput(task=tid, goal="g2", project="p2"))
        t = s.get_task(tid)
        self.assertEqual(t.goal, "g2")
        self.assertEqual(t.project, "p2")

    def test_unspecified_fields_unchanged(self):
        s = FakeStore()
        tid = s.create_task("keep title", role="human", description="keep desc", goal="g1")
        EditTaskUseCase(s).execute(EditTaskInput(task=tid, project="p1"))
        t = s.get_task(tid)
        self.assertEqual(t.title, "keep title")
        self.assertEqual(t.description, "keep desc")
        self.assertEqual(t.goal, "g1")
        self.assertEqual(t.project, "p1")


class TestLinkArtifact(unittest.TestCase):
    def test_appends_artifact(self):
        s = FakeStore()
        sid = s.create_story("st")
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(story=sid, atype="pr", value="http://x/1", label="PR 1"))
        arts = s.story_artifacts(sid)
        self.assertEqual(arts[0].type, "pr")
        self.assertEqual(arts[0].value, "http://x/1")
        self.assertEqual(arts[0].label, "PR 1")


class TestCloseStory(unittest.TestCase):
    def test_closes_story_open_children_and_removes_worktree(self):
        s = FakeStore()
        sid = s.create_story("st")
        k = s.create_task("build: x", step="build", role="coder", parent=sid)
        wt = FakeWorktrees()
        CloseStoryUseCase(s, wt).execute(CloseStoryInput(story=sid, reason="merged"))
        self.assertEqual(s.get_task(sid).status, "done")
        self.assertEqual(s.get_task(k).status, "done")
        self.assertEqual(wt.removed, [sid])


class TestWorktreeServiceStoryBranch(unittest.TestCase):
    def test_none_then_branch_artifact(self):
        s = FakeStore()
        sid = s.create_story("st")
        svc = WorktreeService(s, None, None, None)
        self.assertIsNone(svc.story_branch(sid))
        s.add_artifact(sid, "branch", "feat/x")
        self.assertEqual(svc.story_branch(sid), "feat/x")


class TestFileStory(unittest.TestCase):
    def _file(self, store, repo=None):
        fs = FakeFs(metas=METAS, dirs={"/projects": ["app", "lib"]})
        flow = FlowService(fs, store)
        git = FakeGit(repos={"/projects/app"})
        return FileStoryUseCase(store, flow, git, fs, FakeConfig("/projects")).execute(
            FileStoryInput(spec="specs/x.md", step="build", repo=repo)).story

    def test_creates_story_with_spec_and_task(self):
        s = FakeStore()
        story = self._file(s)
        self.assertIn("spec", [a.type for a in s.story_artifacts(story)])
        self.assertEqual(len(s.children(story)), 1)

    def test_records_repo_artifact_for_known_repo(self):
        s = FakeStore()
        story = self._file(s, repo="app")
        self.assertIn("repo", [a.type for a in s.story_artifacts(story)])

    def test_unknown_step_raises(self):
        s = FakeStore()
        fs = FakeFs(metas=METAS)
        with self.assertRaises(UseCaseError):
            FileStoryUseCase(s, FlowService(fs, s), FakeGit(), fs, FakeConfig()).execute(
                FileStoryInput(spec="specs/x.md", step="nonexistent"))

    def test_unknown_repo_raises_with_available(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            self._file(s, repo="missing")
        self.assertIn("app", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
