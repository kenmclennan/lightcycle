import json
import unittest

from the_grid.application.errors import UseCaseError
from the_grid.application.work import (
    AddTaskInput,
    AddTaskUseCase,
    CloseEpicInput,
    CloseEpicUseCase,
    CloseStoryInput,
    CloseStoryUseCase,
    EditTaskInput,
    EditTaskUseCase,
    FileStoryInput,
    FileStoryUseCase,
    LinkArtifactInput,
    LinkArtifactUseCase,
)
from the_grid.application.services.flow import FlowService
from the_grid.application.services.worktree import WorktreeService
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

METAS = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}


def _epic_flow(store):
    return FlowService(FakeFs(), store)


def _add_reflection(store, task_id, feedback):
    store.add_artifact(
        task_id, "reflection", json.dumps({"task": task_id, "feedback": feedback, "spec_hash": "h"})
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
            AddTaskInput(title="my task", description="detailed notes")
        )
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

    def test_edits_parent_alone(self):
        s = FakeStore()
        epic = s.create_epic("my epic")
        tid = s.create_task("a task", role="human")
        EditTaskUseCase(s).execute(EditTaskInput(task=tid, parent=epic))
        t = s.get_task(tid)
        self.assertEqual(t.parent, epic)

    def test_edits_parent_and_title_together(self):
        s = FakeStore()
        epic = s.create_epic("my epic")
        tid = s.create_task("old title", role="human")
        EditTaskUseCase(s).execute(EditTaskInput(task=tid, title="new title", parent=epic))
        t = s.get_task(tid)
        self.assertEqual(t.title, "new title")
        self.assertEqual(t.parent, epic)

    def test_omitting_parent_leaves_parentage_unchanged(self):
        s = FakeStore()
        epic = s.create_epic("my epic")
        tid = s.create_task("a task", role="human", parent=epic)
        EditTaskUseCase(s).execute(EditTaskInput(task=tid, title="renamed"))
        t = s.get_task(tid)
        self.assertEqual(t.parent, epic)


class TestLinkArtifact(unittest.TestCase):
    def test_appends_artifact(self):
        s = FakeStore()
        sid = s.create_story("st", epic=s.create_epic("epic"))
        LinkArtifactUseCase(s).execute(
            LinkArtifactInput(story=sid, atype="pr", value="http://x/1", label="PR 1")
        )
        arts = s.story_artifacts(sid)
        self.assertEqual(arts[0].type, "pr")
        self.assertEqual(arts[0].value, "http://x/1")
        self.assertEqual(arts[0].label, "PR 1")


class TestCloseStory(unittest.TestCase):
    def test_closes_story_open_children_and_removes_worktree(self):
        s = FakeStore()
        sid = s.create_story("st", epic=s.create_epic("epic"))
        k = s.create_task("build: x", step="build", role="coder", parent=sid)
        wt = FakeWorktrees()
        CloseStoryUseCase(s, wt).execute(CloseStoryInput(story=sid, reason="merged"))
        self.assertEqual(s.get_task(sid).status, "done")
        self.assertEqual(s.get_task(k).status, "done")
        self.assertEqual(wt.removed, [sid])


class TestCloseEpic(unittest.TestCase):
    def test_closes_epic_when_all_children_closed(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        child = s.create_story("story", epic=epic)
        s.close(child, "merged")
        CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertEqual(s.get_task(epic).status, "done")

    def test_refuses_with_open_child_and_names_it(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        child = s.create_story("story", epic=epic)
        with self.assertRaises(UseCaseError) as ctx:
            CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertIn(child, str(ctx.exception))
        self.assertEqual(s.get_task(epic).status, "ready")

    def test_refuses_leaves_epic_open_with_mixed_children(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        closed = s.create_story("done story", epic=epic)
        open_ = s.create_story("open story", epic=epic)
        s.close(closed, "merged")
        with self.assertRaises(UseCaseError) as ctx:
            CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertIn(open_, str(ctx.exception))
        self.assertNotIn(closed, str(ctx.exception))
        self.assertEqual(s.get_task(epic).status, "ready")


class TestCloseEpicBacklogResolution(unittest.TestCase):
    def test_closes_linked_backlog_item_on_epic_close(self):
        s = FakeStore()
        backlog = s.create_task("a backlog item", role="human")
        epic = s.create_epic("my epic")
        s.add_artifact(epic, "backlog", backlog)
        child = s.create_story("story", epic=epic)
        s.close(child, "merged")
        CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertEqual(s.get_task(backlog).status, "done")

    def test_no_backlog_link_is_a_no_op(self):
        s = FakeStore()
        epic = s.create_epic("my epic")
        child = s.create_story("story", epic=epic)
        s.close(child, "merged")
        CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertEqual(s.get_task(epic).status, "done")


class TestCloseEpicWithRetro(unittest.TestCase):
    def _setup(self, feedback=None):
        s = FakeStore()
        epic = s.create_epic("my epic")
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
        retro_idx = next(
            i for i, e in enumerate(call_order) if len(e) >= 3 and e[1] == epic and e[2] == "retro"
        )
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
        epic = s.create_epic("my epic")
        s.create_story("open story", epic=epic)
        with self.assertRaises(UseCaseError):
            CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        self.assertEqual([a for a in s.story_artifacts(epic) if a.type == "retro"], [])


class TestCloseEpicOnEpicClose(unittest.TestCase):
    def _setup(self):
        s = FakeStore()
        epic = s.create_epic("my epic")
        child = s.create_story("child story", epic=epic)
        s.close(child, "merged")
        return s, epic

    def _flow_with_on_epic_close(self, store, step="process-check", role="checker"):
        metas = {role: {"model": "sonnet", "step": step, "on_epic_close": True}}
        return FlowService(FakeFs(metas), store)

    def test_creates_task_at_on_epic_close_step(self):
        s, epic = self._setup()
        flow = self._flow_with_on_epic_close(s)
        CloseEpicUseCase(s, flow).execute(CloseEpicInput(epic=epic, reason="done"))
        tasks = [t for t in s.all_tasks() if t.type == "task" and t.epic == epic]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].step, "process-check")
        self.assertEqual(tasks[0].role, "checker")

    def test_epic_id_in_metadata_not_parent(self):
        s, epic = self._setup()
        flow = self._flow_with_on_epic_close(s)
        CloseEpicUseCase(s, flow).execute(CloseEpicInput(epic=epic, reason="done"))
        tasks = [t for t in s.all_tasks() if t.type == "task" and t.epic == epic]
        self.assertEqual(len(tasks), 1)
        self.assertIsNone(tasks[0].parent)

    def test_task_title_contains_step_and_epic_title(self):
        s, epic = self._setup()
        flow = self._flow_with_on_epic_close(s)
        CloseEpicUseCase(s, flow).execute(CloseEpicInput(epic=epic, reason="done"))
        tasks = [t for t in s.all_tasks() if t.type == "task" and t.epic == epic]
        self.assertEqual(tasks[0].title, "process-check: my epic")

    def test_agnostic_arbitrary_step_name_not_audit(self):
        s, epic = self._setup()
        flow = self._flow_with_on_epic_close(s, step="scrutinise", role="scrutiniser")
        CloseEpicUseCase(s, flow).execute(CloseEpicInput(epic=epic, reason="done"))
        tasks = [t for t in s.all_tasks() if t.type == "task" and t.epic == epic]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].step, "scrutinise")

    def test_no_on_epic_close_step_no_task_created(self):
        s, epic = self._setup()
        CloseEpicUseCase(s, _epic_flow(s)).execute(CloseEpicInput(epic=epic, reason="done"))
        tasks = [t for t in s.all_tasks() if t.type == "task" and t.epic == epic]
        self.assertEqual(tasks, [])

    def test_closed_epic_is_not_a_close_candidate(self):
        s, epic = self._setup()
        flow = self._flow_with_on_epic_close(s)
        CloseEpicUseCase(s, flow).execute(CloseEpicInput(epic=epic, reason="done"))
        open_tasks = [
            t for t in s.all_tasks() if t.type == "task" and t.epic == epic and t.status != "done"
        ]
        self.assertEqual(len(open_tasks), 1)
        self.assertEqual(s.get_task(epic).status, "done")


class TestWorktreeServiceStoryBranch(unittest.TestCase):
    def test_none_then_branch_artifact(self):
        s = FakeStore()
        sid = s.create_story("st", epic=s.create_epic("epic"))
        svc = WorktreeService(s, None, None, None)
        self.assertIsNone(svc.story_branch(sid))
        s.add_artifact(sid, "branch", "feat/x")
        self.assertEqual(svc.story_branch(sid), "feat/x")


class TestFileStory(unittest.TestCase):
    def _file(self, store, repo=None):
        fs = FakeFs(metas=METAS, dirs={"/projects": ["app", "lib"]})
        flow = FlowService(fs, store)
        git = FakeGit(repos={"/projects/app"})
        epic = store.create_epic("epic")
        return (
            FileStoryUseCase(store, flow, git, fs, FakeConfig("/projects"))
            .execute(FileStoryInput(spec="specs/x.md", step="build", epic=epic, repo=repo))
            .story
        )

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
                FileStoryInput(spec="specs/x.md", step="nonexistent", epic=s.create_epic("epic"))
            )

    def test_unknown_repo_raises_with_available(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError) as ctx:
            self._file(s, repo="missing")
        self.assertIn("app", str(ctx.exception))

    def _use_case(self, store):
        fs = FakeFs(metas=METAS, dirs={"/projects": ["app", "lib"]})
        return FileStoryUseCase(store, FlowService(fs, store), FakeGit(), fs, FakeConfig("/projects"))

    def test_missing_epic_raises(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError):
            self._use_case(s).execute(FileStoryInput(spec="specs/x.md", step="build", epic=None))

    def test_unknown_epic_raises(self):
        s = FakeStore()
        with self.assertRaises(UseCaseError):
            self._use_case(s).execute(
                FileStoryInput(spec="specs/x.md", step="build", epic="does-not-exist")
            )

    def test_non_epic_parent_raises(self):
        s = FakeStore()
        not_an_epic = s.create_task("just a task", role="human")
        with self.assertRaises(UseCaseError):
            self._use_case(s).execute(
                FileStoryInput(spec="specs/x.md", step="build", epic=not_an_epic)
            )

    def test_closed_epic_raises(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        s.close(epic, "done")
        with self.assertRaises(UseCaseError):
            self._use_case(s).execute(FileStoryInput(spec="specs/x.md", step="build", epic=epic))

    def test_available_repos_includes_nested_repo(self):
        fs = FakeFs(
            metas=METAS,
            dirs={
                "/projects": ["app", "group", "plain"],
                "/projects/group": ["svc"],
            },
        )
        git = FakeGit(repos={"/projects/app", "/projects/group/svc"})
        use_case = FileStoryUseCase(
            FakeStore(), FlowService(fs, FakeStore()), git, fs, FakeConfig("/projects")
        )
        self.assertEqual(use_case._available_repos(), ["app", "group/svc"])

    def test_nested_repo_accepted_by_validation_is_also_discoverable(self):
        fs = FakeFs(
            metas=METAS,
            dirs={
                "/projects": ["app", "group", "plain"],
                "/projects/group": ["svc"],
            },
        )
        s = FakeStore()
        git = FakeGit(repos={"/projects/app", "/projects/group/svc"})
        epic = s.create_epic("epic")
        story = (
            FileStoryUseCase(s, FlowService(fs, s), git, fs, FakeConfig("/projects"))
            .execute(FileStoryInput(spec="specs/x.md", step="build", epic=epic, repo="group/svc"))
            .story
        )
        self.assertIn("repo", [a.type for a in s.story_artifacts(story)])


class TestFileStoryAtomicity(unittest.TestCase):
    def _file(self, store, epic, repo=None, blocked_by=None):
        fs = FakeFs(metas=METAS, dirs={"/projects": ["app", "lib"]})
        flow = FlowService(fs, store)
        git = FakeGit(repos={"/projects/app"})
        return FileStoryUseCase(store, flow, git, fs, FakeConfig("/projects")).execute(
            FileStoryInput(spec="specs/x.md", step="build", epic=epic, repo=repo, blocked_by=blocked_by)
        )

    def test_spec_artifact_failure_leaves_no_story(self):
        s = FakeStore()
        epic = s.create_epic("epic")

        def boom(story_id, atype, value, label=None):
            raise RuntimeError("boom")

        s.add_artifact = boom
        with self.assertRaises(RuntimeError):
            self._file(s, epic)
        remaining = {k: v for k, v in s._records.items() if k != epic}
        self.assertEqual(remaining, {})

    def test_repo_artifact_failure_leaves_no_story(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        orig_add_artifact = s.add_artifact

        def maybe_boom(story_id, atype, value, label=None):
            if atype == "repo":
                raise RuntimeError("boom")
            return orig_add_artifact(story_id, atype, value, label)

        s.add_artifact = maybe_boom
        with self.assertRaises(RuntimeError):
            self._file(s, epic, repo="app")
        remaining = {k: v for k, v in s._records.items() if k != epic}
        self.assertEqual(remaining, {})

    def test_task_creation_failure_leaves_no_story(self):
        s = FakeStore()
        epic = s.create_epic("epic")

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        s.create_task = boom
        with self.assertRaises(RuntimeError):
            self._file(s, epic)
        remaining = {k: v for k, v in s._records.items() if k != epic}
        self.assertEqual(remaining, {})

    def test_dep_add_failure_leaves_no_story_or_task(self):
        s = FakeStore()
        epic = s.create_epic("epic")
        blocker = s.create_task("blocker task", role="coder")

        def boom(task_id, blocked_by):
            raise RuntimeError("boom")

        s.dep_add = boom
        with self.assertRaises(RuntimeError):
            self._file(s, epic, blocked_by=[blocker])
        remaining = {k: v for k, v in s._records.items() if k not in (blocker, epic)}
        self.assertEqual(remaining, {})


class TestWorktreeServiceRemove(unittest.TestCase):
    def test_remove_requests_remote_branch_delete(self):
        s = FakeStore()
        sid = s.create_story("my story", epic=s.create_epic("epic"))
        s.add_artifact(sid, "repo", "app")
        s.add_artifact(sid, "branch", "feat/my-branch")
        git = FakeGitRemove(repos={"/projects/app"})
        svc = WorktreeService(s, git, FakeFs(), FakeConfig("/projects"))
        svc.remove(sid)
        self.assertIn(("/projects/app", "feat/my-branch"), git.remote_deletes)

    def test_remove_skips_remote_delete_when_not_git_repo(self):
        s = FakeStore()
        sid = s.create_story("my story", epic=s.create_epic("epic"))
        s.add_artifact(sid, "repo", "app")
        s.add_artifact(sid, "branch", "feat/my-branch")
        git = FakeGitRemove(repos=set())
        svc = WorktreeService(s, git, FakeFs(), FakeConfig("/projects"))
        svc.remove(sid)
        self.assertEqual(git.remote_deletes, [])


if __name__ == "__main__":
    unittest.main()
