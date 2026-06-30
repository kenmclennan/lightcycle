import unittest

from the_grid.application.errors import UseCaseError
from the_grid.application.intake import AddTask, CloseStory, FileStory, LinkArtifact
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
        tid = AddTask(s).execute("do a thing", goal="g1", project="p1")
        t = s.get_task(tid)
        self.assertEqual(t.status, "needs-human")
        self.assertEqual(t.goal, "g1")
        self.assertEqual(t.project, "p1")


class TestLinkArtifact(unittest.TestCase):
    def test_appends_artifact(self):
        s = FakeStore()
        sid = s.create_story("st")
        LinkArtifact(s).execute(sid, "pr", "http://x/1", "PR 1")
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
        CloseStory(s, wt).execute(sid, "merged")
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
        return FileStory(store, flow, git, fs, FakeConfig("/projects")).execute(
            "specs/x.md", "build", repo=repo)

    def test_creates_story_with_spec_and_task(self):
        s = FakeStore()
        story = self._file(s)
        types = [a.type for a in s.story_artifacts(story)]
        self.assertIn("spec", types)
        kids = s.children(story)
        self.assertEqual(len(kids), 1)

    def test_records_repo_artifact_for_known_repo(self):
        s = FakeStore()
        story = self._file(s, repo="app")
        self.assertIn("repo", [a.type for a in s.story_artifacts(story)])

    def test_unknown_step_raises(self):
        s = FakeStore()
        fs = FakeFs(metas=METAS)
        with self.assertRaises(UseCaseError):
            FileStory(s, FlowService(fs, s), FakeGit(), fs, FakeConfig()).execute(
                "specs/x.md", "nonexistent")

    def test_unknown_repo_raises_with_available(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            self._file(s, repo="missing")
        self.assertIn("app", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
