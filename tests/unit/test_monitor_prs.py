import unittest

from the_grid.application.flow import CompleteTaskUseCase
from the_grid.application.pool import MonitorPrsUseCase, TickInput, TickUseCase
from the_grid.domain.flow import Flow
from the_grid.ports.github import Comment, GitHubEventsPort
from tests.support.fake_store import FakeStore


class _FlowAdapter:
    """Wraps a domain Flow to satisfy CompleteTaskUseCase's duck-typed interface."""

    def __init__(self, flow):
        self._flow = flow

    def flow_next(self, step, outcome):
        return self._flow.next(step, outcome)

    def meta_for_step(self, step):
        return {}

_FLOW = Flow.assemble({
    "reviewer": {
        "step": "ready-merge",
        "routes": {"merged": "cleanup", "changes": "build"},
        "on_pr_merge": "merged",
        "on_pr_close": "abandoned",
        "on_pr_rework": "changes",
    }
})

_MERGE_ONLY_FLOW = Flow.assemble({
    "reviewer": {
        "step": "ready-merge",
        "routes": {"merged": "cleanup", "changes": "build"},
        "on_pr_merge": "merged",
    }
})

_REWORK_ONLY_FLOW = Flow.assemble({
    "coder": {
        "model": "sonnet",
        "step": "build",
        "routes": {"done": "ready-merge"},
    },
    "reviewer": {
        "step": "ready-merge",
        "routes": {"changes": "build"},
        "on_pr_rework": "changes",
    },
})


class FakeGitHub(GitHubEventsPort):
    def __init__(self, merged_prs=(), closed_prs=(), push_time=0.0, timed_comments=None):
        self._merged = set(merged_prs)
        self._closed = set(closed_prs)
        self._push_time = push_time
        self._timed_comments = timed_comments or []

    def is_merged(self, pr):
        return pr in self._merged

    def is_closed_unmerged(self, pr):
        return pr in self._closed

    def last_push_time(self, pr):
        return self._push_time

    def comments_since(self, pr, since):
        return [c for ts, c in self._timed_comments if ts > since]


class FakeWorktrees:
    def __init__(self):
        self.removed = []

    def remove(self, story):
        self.removed.append(story)


class TestMonitorPrsMerged(unittest.TestCase):

    def _setup(self, pr_url, github, flow=None):
        store = FakeStore()
        story = store.create_story("my feature")
        store.add_artifact(story, "pr", pr_url)
        task = store.create_task("ready-merge: my feature", step="ready-merge", role="human",
                                 parent=story)
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, github, worktrees, flow or _FLOW)
        return store, story, task, worktrees, uc

    def test_merged_pr_closes_story_and_children(self):
        url = "https://github.com/x/y/pull/1"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        result = uc.execute()

        self.assertEqual(result.merged, [story])
        self.assertEqual(store.get_task(story).status, "done")
        self.assertEqual(store.get_task(task).status, "done")
        self.assertIn(story, worktrees.removed)

    def test_merged_story_closes_with_declared_merge_reason(self):
        url = "https://github.com/x/y/pull/2"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        uc.execute()

        self.assertEqual(store.get_task(story).outcome, "merged")

    def test_open_pr_does_not_close_story(self):
        url = "https://github.com/x/y/pull/3"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_task(story).status, "ready")
        self.assertNotEqual(store.get_task(task).status, "done")
        self.assertEqual(worktrees.removed, [])

    def test_already_closed_story_task_is_skipped(self):
        url = "https://github.com/x/y/pull/4"
        store = FakeStore()
        story = store.create_story("done feature")
        store.add_artifact(story, "pr", url)
        task = store.create_task("ready-merge: done feature", step="ready-merge", role="human",
                                 parent=story)
        store.close(task, "merged")
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_task_without_pr_artifact_is_skipped(self):
        store = FakeStore()
        story = store.create_story("no-pr feature")
        store.create_task("ready-merge: no-pr feature", step="ready-merge", role="human",
                          parent=story)
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={"anything"})
        uc = MonitorPrsUseCase(store, github, worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_task_without_parent_is_skipped(self):
        store = FakeStore()
        store.create_task("ready-merge: orphan", step="ready-merge", role="human")
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={"x"}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_arbitrary_step_and_outcome_names_monitored_via_merge(self):
        arbitrary_flow = Flow.assemble(
            {"gatekeeper": {"step": "await-ship", "routes": {"shipped": "done-step"},
                            "on_pr_merge": "shipped"}}
        )
        url = "https://github.com/x/y/pull/99"
        store = FakeStore()
        story = store.create_story("ship it")
        store.add_artifact(story, "pr", url)
        store.create_task("await-ship: ship it", step="await-ship", role="human", parent=story)
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, arbitrary_flow)

        result = uc.execute()

        self.assertEqual(result.merged, [story])
        self.assertEqual(store.get_task(story).outcome, "shipped")
        self.assertIn(story, worktrees.removed)


class TestMonitorPrsClosedUnmerged(unittest.TestCase):

    def _setup(self, pr_url, github, flow=None):
        store = FakeStore()
        story = store.create_story("abandoned feature")
        store.add_artifact(story, "pr", pr_url)
        task = store.create_task("ready-merge: abandoned feature", step="ready-merge", role="human",
                                 parent=story)
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, github, worktrees, flow or _FLOW)
        return store, story, task, worktrees, uc

    def test_closed_unmerged_pr_closes_story(self):
        url = "https://github.com/x/y/pull/10"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        result = uc.execute()

        self.assertEqual(result.abandoned, [story])
        self.assertEqual(result.merged, [])
        self.assertEqual(store.get_task(story).status, "done")
        self.assertEqual(store.get_task(task).status, "done")
        self.assertIn(story, worktrees.removed)

    def test_closed_unmerged_story_closes_with_declared_close_reason(self):
        url = "https://github.com/x/y/pull/11"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        uc.execute()

        self.assertEqual(store.get_task(story).outcome, "abandoned")

    def test_open_pr_does_not_take_abandon_path(self):
        url = "https://github.com/x/y/pull/12"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_task(story).status, "ready")
        self.assertEqual(worktrees.removed, [])

    def test_merged_pr_does_not_take_abandon_path(self):
        url = "https://github.com/x/y/pull/13"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(result.merged, [story])

    def test_arbitrary_close_outcome_name_is_used(self):
        arbitrary_flow = Flow.assemble({
            "gatekeeper": {
                "step": "await-ship",
                "routes": {"shipped": "done-step", "cancelled": "done-step"},
                "on_pr_merge": "shipped",
                "on_pr_close": "cancelled",
            }
        })
        url = "https://github.com/x/y/pull/20"
        store = FakeStore()
        story = store.create_story("cancelled work")
        store.add_artifact(story, "pr", url)
        store.create_task("await-ship: cancelled work", step="await-ship", role="human",
                          parent=story)
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(closed_prs={url}), worktrees, arbitrary_flow)

        result = uc.execute()

        self.assertEqual(result.abandoned, [story])
        self.assertEqual(store.get_task(story).outcome, "cancelled")
        self.assertIn(story, worktrees.removed)

    def test_step_without_on_pr_close_not_abandoned_on_close(self):
        url = "https://github.com/x/y/pull/21"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}),
                                                        flow=_MERGE_ONLY_FLOW)

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_task(story).status, "ready")


class TestMonitorPrsRework(unittest.TestCase):

    def _setup(self, pr_url, github, flow=None):
        f = flow or _REWORK_ONLY_FLOW
        store = FakeStore()
        story = store.create_story("in-review feature")
        store.add_artifact(story, "pr", pr_url)
        task = store.create_task("ready-merge: in-review feature", step="ready-merge",
                                 role="human", parent=story)
        worktrees = FakeWorktrees()
        complete = CompleteTaskUseCase(store, _FlowAdapter(f))
        uc = MonitorPrsUseCase(store, github, worktrees, f, complete)
        return store, story, task, worktrees, uc

    def _rework_comment(self, ts):
        return (ts, Comment(author="reviewer", body="/rework fix the tests", is_top_level=True))

    def _inline_comment(self, ts):
        return (ts, Comment(author="reviewer", body="nit: rename this", is_top_level=False,
                            path="src/foo.py", line=42))

    def test_rework_comment_after_push_advances_task(self):
        url = "https://github.com/x/y/pull/30"
        gh = FakeGitHub(push_time=1000.0,
                        timed_comments=[self._rework_comment(1500.0)])
        store, story, task, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [story])
        self.assertEqual(store.get_task(task).status, "done")
        self.assertEqual(store.get_task(task).outcome, "changes")

    def test_rework_creates_new_build_task(self):
        url = "https://github.com/x/y/pull/31"
        gh = FakeGitHub(push_time=1000.0,
                        timed_comments=[self._rework_comment(1500.0)])
        store, story, task, _, uc = self._setup(url, gh)

        uc.execute()

        tasks = [t for t in store.all_tasks() if t.id != task and t.type == "task"]
        self.assertEqual(len(tasks), 1)
        new_task = tasks[0]
        self.assertEqual(new_task.step, "build")
        self.assertEqual(new_task.status, "ready")

    def test_rework_note_forwards_guidance_including_inline_context(self):
        url = "https://github.com/x/y/pull/32"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            self._inline_comment(1200.0),
            self._rework_comment(1500.0),
        ])
        store, story, task, _, uc = self._setup(url, gh)

        uc.execute()

        tasks = [t for t in store.all_tasks() if t.id != task and t.type == "task"]
        note = store.get_task(tasks[0].id).notes
        self.assertIn("[src/foo.py:42]", note)
        self.assertIn("nit: rename this", note)

    def test_rework_note_excludes_marker_comment_body(self):
        url = "https://github.com/x/y/pull/33"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            self._rework_comment(1500.0),
        ])
        store, story, task, _, uc = self._setup(url, gh)

        uc.execute()

        tasks = [t for t in store.all_tasks() if t.id != task and t.type == "task"]
        note = store.get_task(tasks[0].id).notes or ""
        self.assertNotIn("/rework fix the tests", note)

    def test_inline_only_does_not_trigger_rework(self):
        url = "https://github.com/x/y/pull/34"
        gh = FakeGitHub(push_time=1000.0,
                        timed_comments=[self._inline_comment(1500.0)])
        store, story, task, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertNotEqual(store.get_task(task).status, "done")
        self.assertEqual(worktrees.removed, [])

    def test_rework_comment_before_push_does_not_refire(self):
        url = "https://github.com/x/y/pull/35"
        gh = FakeGitHub(push_time=1000.0,
                        timed_comments=[self._rework_comment(500.0)])
        store, story, task, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertNotEqual(store.get_task(task).status, "done")

    def test_bot_comment_with_rework_marker_does_not_trigger(self):
        url = "https://github.com/x/y/pull/36"
        bot_comment = (1500.0, Comment(author="some-ci[bot]", body="/rework", is_top_level=True))
        gh = FakeGitHub(push_time=1000.0, timed_comments=[bot_comment])
        store, story, task, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_bot_comment_excluded_from_guidance(self):
        url = "https://github.com/x/y/pull/37"
        bot_inline = (1200.0, Comment(author="lint-bot[bot]", body="linting issue", is_top_level=False,
                                      path="src/x.py", line=1))
        gh = FakeGitHub(push_time=1000.0, timed_comments=[
            bot_inline,
            self._rework_comment(1500.0),
        ])
        store, story, task, _, uc = self._setup(url, gh)

        uc.execute()

        tasks = [t for t in store.all_tasks() if t.id != task and t.type == "task"]
        note = store.get_task(tasks[0].id).notes or ""
        self.assertNotIn("linting issue", note)

    def test_arbitrary_rework_outcome_name_is_used(self):
        arbitrary_flow = Flow.assemble({
            "gatekeeper": {
                "step": "await-ship",
                "routes": {"revise": "build-step"},
                "on_pr_rework": "revise",
            }
        })
        url = "https://github.com/x/y/pull/38"
        store = FakeStore()
        story = store.create_story("arbitrary rework")
        store.add_artifact(story, "pr", url)
        task = store.create_task("await-ship: arbitrary rework", step="await-ship", role="human",
                                 parent=story)
        gh = FakeGitHub(push_time=1000.0,
                        timed_comments=[self._rework_comment(1500.0)])
        worktrees = FakeWorktrees()
        complete = CompleteTaskUseCase(store, _FlowAdapter(arbitrary_flow))
        uc = MonitorPrsUseCase(store, gh, worktrees, arbitrary_flow, complete)

        result = uc.execute()

        self.assertEqual(result.reworked, [story])
        self.assertEqual(store.get_task(task).outcome, "revise")

    def test_merged_pr_takes_merge_path_not_rework(self):
        url = "https://github.com/x/y/pull/39"
        gh = FakeGitHub(merged_prs={url}, push_time=1000.0,
                        timed_comments=[self._rework_comment(1500.0)])
        store, story, task, worktrees, uc = self._setup(url, gh, flow=_FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [story])
        self.assertEqual(result.reworked, [])
        self.assertEqual(store.get_task(story).status, "done")


class FakeWorkers:
    def __init__(self):
        pass

    def workers_state(self):
        return []

    def pid_alive(self, pid):
        return False

    def prune_workers(self):
        return 0


class FakeSpawner:
    def __init__(self):
        self.spawned = []

    def spawn_worker(self, role):
        self.spawned.append(role)


class FakeConfig:
    def max_agents(self):
        return 4

    def max_boot_seconds(self):
        return 120

    def grid_root(self):
        return "/grid"


class TestTickWithMonitor(unittest.TestCase):

    def test_tick_runs_monitor_and_returns_merged(self):
        url = "https://github.com/x/y/pull/5"
        store = FakeStore()
        story = store.create_story("merge me")
        store.add_artifact(story, "pr", url)
        store.create_task("ready-merge: merge me", step="ready-merge", role="human", parent=story)
        worktrees = FakeWorktrees()
        monitor = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FLOW)

        result = TickUseCase(store, FakeWorkers(), FakeSpawner(), FakeConfig(),
                             monitor=monitor).execute(TickInput(now=1000.0))

        self.assertEqual(result.merged, [story])
        self.assertEqual(result.abandoned, [])

    def test_tick_runs_monitor_and_returns_abandoned(self):
        url = "https://github.com/x/y/pull/6"
        store = FakeStore()
        story = store.create_story("abandoned me")
        store.add_artifact(story, "pr", url)
        store.create_task("ready-merge: abandoned me", step="ready-merge", role="human", parent=story)
        worktrees = FakeWorktrees()
        monitor = MonitorPrsUseCase(store, FakeGitHub(closed_prs={url}), worktrees, _FLOW)

        result = TickUseCase(store, FakeWorkers(), FakeSpawner(), FakeConfig(),
                             monitor=monitor).execute(TickInput(now=1000.0))

        self.assertEqual(result.abandoned, [story])
        self.assertEqual(result.merged, [])

    def test_tick_without_monitor_has_empty_merged_and_abandoned(self):
        store = FakeStore()
        result = TickUseCase(store, FakeWorkers(), FakeSpawner(), FakeConfig()).execute(
            TickInput(now=1000.0))
        self.assertEqual(result.merged, [])
        self.assertEqual(result.abandoned, [])
        self.assertEqual(result.reworked, [])


if __name__ == "__main__":
    unittest.main()
