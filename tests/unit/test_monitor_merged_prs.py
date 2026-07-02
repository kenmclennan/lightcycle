import unittest

from the_grid.application.pool import MonitorMergedPrsUseCase, TickInput, TickUseCase
from the_grid.domain.flow import Flow
from the_grid.ports.github import GitHubEventsPort
from tests.support.fake_store import FakeStore

_FLOW = Flow.assemble({"reviewer": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}, "on_pr_merge": "merged"}})


class FakeGitHub(GitHubEventsPort):
    def __init__(self, merged_prs=()):
        self._merged = set(merged_prs)

    def is_merged(self, pr):
        return pr in self._merged


class FakeWorktrees:
    def __init__(self):
        self.removed = []

    def remove(self, story):
        self.removed.append(story)


class TestMonitorMergedPrs(unittest.TestCase):

    def _setup(self, pr_url, github):
        store = FakeStore()
        story = store.create_story("my feature")
        store.add_artifact(story, "pr", pr_url)
        task = store.create_task("ready-merge: my feature", step="ready-merge", role="human",
                                 parent=story)
        worktrees = FakeWorktrees()
        uc = MonitorMergedPrsUseCase(store, github, worktrees, _FLOW)
        return store, story, task, worktrees, uc

    def test_merged_pr_closes_story_and_children(self):
        url = "https://github.com/x/y/pull/1"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        result = uc.execute()

        self.assertEqual(result.merged, [story])
        self.assertEqual(store.get_task(story).status, "done")
        self.assertEqual(store.get_task(task).status, "done")
        self.assertIn(story, worktrees.removed)

    def test_merged_story_closes_with_reason_merged(self):
        url = "https://github.com/x/y/pull/2"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        uc.execute()

        self.assertEqual(store.get_task(story).outcome, "merged")

    def test_unmerged_pr_does_not_close_story(self):
        url = "https://github.com/x/y/pull/3"
        store, story, task, worktrees, uc = self._setup(url, FakeGitHub(merged_prs=set()))

        result = uc.execute()

        self.assertEqual(result.merged, [])
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
        uc = MonitorMergedPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_task_without_pr_artifact_is_skipped(self):
        store = FakeStore()
        story = store.create_story("no-pr feature")
        store.create_task("ready-merge: no-pr feature", step="ready-merge", role="human",
                          parent=story)
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={"anything"})
        uc = MonitorMergedPrsUseCase(store, github, worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_task_without_parent_is_skipped(self):
        store = FakeStore()
        store.create_task("ready-merge: orphan", step="ready-merge", role="human")
        worktrees = FakeWorktrees()
        uc = MonitorMergedPrsUseCase(store, FakeGitHub(merged_prs={"x"}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_arbitrary_step_and_outcome_names_are_monitored_and_close_with_declared_outcome(self):
        arbitrary_flow = Flow.assemble(
            {"gatekeeper": {"step": "await-ship", "routes": {"shipped": "done-step"}, "on_pr_merge": "shipped"}}
        )
        url = "https://github.com/x/y/pull/99"
        store = FakeStore()
        story = store.create_story("ship it")
        store.add_artifact(story, "pr", url)
        store.create_task("await-ship: ship it", step="await-ship", role="human", parent=story)
        worktrees = FakeWorktrees()
        uc = MonitorMergedPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, arbitrary_flow)

        result = uc.execute()

        self.assertEqual(result.merged, [story])
        self.assertEqual(store.get_task(story).outcome, "shipped")
        self.assertIn(story, worktrees.removed)


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
        monitor = MonitorMergedPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FLOW)

        result = TickUseCase(store, FakeWorkers(), FakeSpawner(), FakeConfig(),
                             monitor=monitor).execute(TickInput(now=1000.0))

        self.assertEqual(result.merged, [story])

    def test_tick_without_monitor_has_empty_merged(self):
        store = FakeStore()
        result = TickUseCase(store, FakeWorkers(), FakeSpawner(), FakeConfig()).execute(
            TickInput(now=1000.0))
        self.assertEqual(result.merged, [])


if __name__ == "__main__":
    unittest.main()
