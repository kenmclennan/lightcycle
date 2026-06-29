import unittest

from the_grid.application.intake import AddTask, CloseStory, LinkArtifact
from the_grid.application.services.worktree import WorktreeService
from tests.fake_store import FakeStore


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
        self.assertEqual(t["status"], "needs-human")
        self.assertEqual(t["goal"], "g1")
        self.assertEqual(t["project"], "p1")


class TestLinkArtifact(unittest.TestCase):
    def test_appends_artifact(self):
        s = FakeStore()
        sid = s.create_story("st")
        LinkArtifact(s).execute(sid, "pr", "http://x/1", "PR 1")
        arts = s.story_artifacts(sid)
        self.assertEqual(arts[0]["type"], "pr")
        self.assertEqual(arts[0]["value"], "http://x/1")
        self.assertEqual(arts[0]["label"], "PR 1")


class TestCloseStory(unittest.TestCase):
    def test_closes_story_open_children_and_removes_worktree(self):
        s = FakeStore()
        sid = s.create_story("st")
        k = s.create_task("build: x", step="build", role="coder", parent=sid)
        wt = FakeWorktrees()
        CloseStory(s, wt).execute(sid, "merged")
        self.assertEqual(s.get_task(sid)["status"], "done")
        self.assertEqual(s.get_task(k)["status"], "done")
        self.assertEqual(wt.removed, [sid])


class TestWorktreeServiceStoryBranch(unittest.TestCase):
    def test_none_then_branch_artifact(self):
        s = FakeStore()
        sid = s.create_story("st")
        svc = WorktreeService(s, None, None, None)
        self.assertIsNone(svc.story_branch(sid))
        s.add_artifact(sid, "branch", "feat/x")
        self.assertEqual(svc.story_branch(sid), "feat/x")


if __name__ == "__main__":
    unittest.main()
