import json
import unittest

from the_grid.application.errors import UseCaseError
from the_grid.application.work import (AddTaskInput, AddTaskUseCase, CloseEpicInput,
                                       CloseEpicUseCase, CloseStoryInput,
                                       CloseStoryUseCase, EditTaskInput, EditTaskUseCase,
                                       FileStoryInput, FileStoryUseCase,
                                       LinkArtifactInput, LinkArtifactUseCase)
from the_grid.application.services.flow import FlowService
from the_grid.application.services.worktree import WorktreeService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

METAS = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}


def _epic_flow(store):
    return FlowService(FakeFs(), store)


def _add_reflection(store, task_id, feedback):
    store.add_artifact(task_id, "reflection",
                       json.dumps({"task": task_id, "feedback": feedback, "spec_hash": "h"}))


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

    def grid_root(self):
        return self._projects


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


class TestCloseEpic(unittest.TestCase):
    def test_closes_epic_when_all_children_closed(self):
        s = FakeStore()
        epic = s.create_story("epic")
        child = s.create_story("story", epic=epic)
        s.close(child, "merged")
        CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertEqual(s.get_task(epic).status, "done")

    def test_refuses_with_open_child_and_names_it(self):
        s = FakeStore()
        epic = s.create_story("epic")
        child = s.create_story("story", epic=epic)
        with self.assertRaises(UseCaseError) as ctx:
            CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertIn(child, str(ctx.exception))
        self.assertEqual(s.get_task(epic).status, "ready")

    def test_refuses_leaves_epic_open_with_mixed_children(self):
        s = FakeStore()
        epic = s.create_story("epic")
        closed = s.create_story("done story", epic=epic)
        open_ = s.create_story("open story", epic=epic)
        s.close(closed, "merged")
        with self.assertRaises(UseCaseError) as ctx:
            CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertIn(open_, str(ctx.exception))
        self.assertNotIn(closed, str(ctx.exception))
        self.assertEqual(s.get_task(epic).status, "ready")


class TestCloseEpicWithRetro(unittest.TestCase):
    def _setup(self, feedback=None):
        s = FakeStore()
        epic = s.create_story("my epic")
        story = s.create_story("child story", epic=epic)
        task = s.create_task("build: x", step="build", role="coder", parent=story)
        if feedback:
            _add_reflection(s, task, feedback)
        s.close(story, "merged")
        return s, epic

    def test_retro_included_in_response(self):
        s, epic = self._setup(feedback="useful feedback")
        resp = CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertEqual(resp.retro.reflection_count, 1)
        self.assertEqual(resp.retro.feedback[0].text, "useful feedback")
        self.assertEqual(len(resp.retro.story_signals), 1)

    def test_retro_digest_recorded_as_artifact_on_epic(self):
        s, epic = self._setup(feedback="spec was thin")
        CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        arts = s.story_artifacts(epic)
        retro_arts = [a for a in arts if a.type == "retro"]
        self.assertEqual(len(retro_arts), 1)
        digest = json.loads(retro_arts[0].value)
        self.assertIn("feedback", digest)
        self.assertIn("story_signals", digest)
        self.assertEqual(digest["feedback"][0]["text"], "spec was thin")

    def test_epic_closed_before_retro_digest_is_stored(self):
        s, epic = self._setup()
        call_order = []
        orig_close = s.close
        orig_add = s.add_artifact

        def tracking_close(tid, reason):
            call_order.append(("close", tid))
            return orig_close(tid, reason)

        def tracking_add(tid, atype, value, label=None):
            call_order.append(("add_artifact", tid, atype))
            return orig_add(tid, atype, value, label)

        s.close = tracking_close
        s.add_artifact = tracking_add
        CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        close_idx = next(i for i, e in enumerate(call_order) if e == ("close", epic))
        retro_idx = next(i for i, e in enumerate(call_order)
                         if len(e) >= 3 and e[1] == epic and e[2] == "retro")
        self.assertLess(close_idx, retro_idx)

    def test_empty_reflections_still_records_artifact(self):
        s, epic = self._setup()
        CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        arts = [a for a in s.story_artifacts(epic) if a.type == "retro"]
        self.assertEqual(len(arts), 1)
        digest = json.loads(arts[0].value)
        self.assertEqual(digest["feedback"], [])

    def test_refusal_skips_retro_and_leaves_no_artifact(self):
        s = FakeStore()
        epic = s.create_story("my epic")
        s.create_story("open story", epic=epic)
        with self.assertRaises(UseCaseError):
            CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertEqual([a for a in s.story_artifacts(epic) if a.type == "retro"], [])


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


class TestWorktreeServiceRemove(unittest.TestCase):
    def test_remove_requests_remote_branch_delete(self):
        s = FakeStore()
        sid = s.create_story("my story")
        s.add_artifact(sid, "repo", "app")
        s.add_artifact(sid, "branch", "feat/my-branch")
        git = FakeGitRemove(repos={"/projects/app"})
        svc = WorktreeService(s, git, FakeFs(), FakeConfig("/projects"))
        svc.remove(sid)
        self.assertIn(("/projects/app", "feat/my-branch"), git.remote_deletes)

    def test_remove_skips_remote_delete_when_not_git_repo(self):
        s = FakeStore()
        sid = s.create_story("my story")
        s.add_artifact(sid, "repo", "app")
        s.add_artifact(sid, "branch", "feat/my-branch")
        git = FakeGitRemove(repos=set())
        svc = WorktreeService(s, git, FakeFs(), FakeConfig("/projects"))
        svc.remove(sid)
        self.assertEqual(git.remote_deletes, [])


if __name__ == "__main__":
    unittest.main()
