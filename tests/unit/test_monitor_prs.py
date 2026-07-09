import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool import MonitorPrsUseCase, TickInput, TickUseCase
from tests.support.fake_fs import flow_from_metas
from lightcycle.ports.github import Comment, GitHubEventsPort
from tests.support.fake_store import FakeStore


class _FlowAdapter:
    def __init__(self, flow):
        self._flow = flow

    def workflow_for(self, step):
        return None

    def project_for(self, step):
        return None

    def flow_next(self, step, outcome, name=None, project=None):
        return self._flow.next(step, outcome)

    def outcomes_for(self, step, name=None, project=None):
        return self._flow.outcomes_for(step)

    def meta_for_step(self, step, name=None, project=None):
        return {}


_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build"},
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
            "on_pr_rework": "changes",
        }
    }
)

_MERGE_ONLY_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build"},
            "on_pr_merge": "merged",
        }
    }
)

_REWORK_ONLY_FLOW = flow_from_metas(
    {
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
    }
)

_CONFLICT_FLOW = flow_from_metas({
    "watcher": {
        "model": "sonnet",
        "step": "watch-step",
        "routes": {"conflicted": "fix-step", "gave-up": "escalate-step"},
        "on_pr_conflict": "conflicted",
        "on_pr_conflict_cap": 2,
        "on_pr_conflict_escalate": "gave-up",
    },
    "fixer": {
        "model": "sonnet",
        "step": "fix-step",
        "routes": {"resolved": "watch-step"},
    },
})

_READY_MERGE_QUAD_FLOW = flow_from_metas({
    "reviewer": {
        "model": "sonnet",
        "step": "watch-pr",
        "routes": {
            "merged": "done-step",
            "abandoned": "done-step",
            "changes": "build-step",
            "conflicted": "resolve-step",
        },
        "on_pr_merge": "merged",
        "on_pr_close": "abandoned",
        "on_pr_rework": "changes",
        "on_pr_conflict": "conflicted",
    },
    "resolver": {
        "model": "sonnet",
        "step": "resolve-step",
        "routes": {"resolved": "watch-pr", "escalate": "human-step"},
    },
})


class FakeGitHub(GitHubEventsPort):
    def __init__(self, merged_prs=(), closed_prs=(), conflicted_prs=(), push_time=0.0,
                 timed_comments=None):
        self._merged = set(merged_prs)
        self._closed = set(closed_prs)
        self._conflicted = set(conflicted_prs)
        self._push_time = push_time
        self._timed_comments = timed_comments or []

    def is_merged(self, pr):
        return pr in self._merged

    def is_closed_unmerged(self, pr):
        return pr in self._closed

    def is_conflicted(self, pr):
        return pr in self._conflicted

    def last_push_time(self, pr):
        return self._push_time

    def comments_since(self, pr, since):
        return [c for ts, c in self._timed_comments if ts > since]


class FakeWorktrees:
    def __init__(self):
        self.removed = []

    def remove(self, item):
        self.removed.append(item)


class TestMonitorPrsMerged(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        store = FakeStore()
        item = store.create_item("my feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", pr_url)
        step = store.create_step(
            "ready-merge: my feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, github, worktrees, flow or _FLOW)
        return store, item, step, worktrees, uc

    def test_merged_pr_closes_story_and_children(self):
        url = "https://github.com/x/y/pull/1"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).status, "done")
        self.assertEqual(store.get_node(step).status, "done")
        self.assertIn(item, worktrees.removed)

    def test_merged_story_closes_with_declared_merge_reason(self):
        url = "https://github.com/x/y/pull/2"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        uc.execute()

        self.assertEqual(store.get_node(item).outcome, "merged")

    def test_open_pr_does_not_close_story(self):
        url = "https://github.com/x/y/pull/3"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_node(item).status, "ready")
        self.assertNotEqual(store.get_node(step).status, "done")
        self.assertEqual(worktrees.removed, [])

    def test_already_closed_story_is_skipped(self):
        url = "https://github.com/x/y/pull/4"
        store = FakeStore()
        item = store.create_item("done feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step(
            "ready-merge: done feature", step="ready-merge", role="human", parent=item
        )
        store.close(step, "merged")
        store.close(item, "merged")
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_merged_pr_closes_story_whose_live_task_is_upstream_of_ready_merge(self):
        url = "https://github.com/x/y/pull/40"
        store = FakeStore()
        item = store.create_item("upstream feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step(
            "build: upstream feature", step="build", role="coder", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).status, "done")
        self.assertEqual(store.get_node(item).outcome, "merged")
        self.assertEqual(store.get_node(step).status, "done")
        self.assertIn(item, worktrees.removed)

    def test_merged_pr_closes_story_whose_live_task_regressed_to_review(self):
        url = "https://github.com/x/y/pull/41"
        store = FakeStore()
        item = store.create_item("regressed feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step(
            "review: regressed feature", step="review", role="reviewer", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(step).status, "done")

    def test_task_without_pr_artifact_is_skipped(self):
        store = FakeStore()
        item = store.create_item("no-pr feature", theme=store.create_theme("theme"))
        store.create_step(
            "ready-merge: no-pr feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={"anything"})
        uc = MonitorPrsUseCase(store, github, worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_task_without_parent_is_skipped(self):
        store = FakeStore()
        store.create_step("ready-merge: orphan", step="ready-merge", role="human")
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={"x"}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_arbitrary_step_and_outcome_names_monitored_via_merge(self):
        arbitrary_flow = flow_from_metas(
            {
                "gatekeeper": {
                    "step": "await-ship",
                    "routes": {"shipped": "done-step"},
                    "on_pr_merge": "shipped",
                }
            }
        )
        url = "https://github.com/x/y/pull/99"
        store = FakeStore()
        item = store.create_item("ship it", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        store.create_step("await-ship: ship it", step="await-ship", role="human", parent=item)
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, arbitrary_flow)

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).outcome, "shipped")
        self.assertIn(item, worktrees.removed)


class TestMonitorPrsClosedUnmerged(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        store = FakeStore()
        item = store.create_item("abandoned feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", pr_url)
        step = store.create_step(
            "ready-merge: abandoned feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, github, worktrees, flow or _FLOW)
        return store, item, step, worktrees, uc

    def test_closed_unmerged_pr_closes_story(self):
        url = "https://github.com/x/y/pull/10"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(result.merged, [])
        self.assertEqual(store.get_node(item).status, "done")
        self.assertEqual(store.get_node(step).status, "done")
        self.assertIn(item, worktrees.removed)

    def test_closed_unmerged_story_closes_with_declared_outcome(self):
        url = "https://github.com/x/y/pull/11"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        uc.execute()

        self.assertEqual(store.get_node(item).outcome, "abandoned")

    def test_open_pr_does_not_take_abandon_path(self):
        url = "https://github.com/x/y/pull/12"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_node(item).status, "ready")
        self.assertEqual(worktrees.removed, [])

    def test_merged_pr_does_not_take_abandon_path(self):
        url = "https://github.com/x/y/pull/13"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(result.merged, [item])

    def test_arbitrary_close_outcome_name_is_used(self):
        arbitrary_flow = flow_from_metas(
            {
                "gatekeeper": {
                    "step": "await-ship",
                    "routes": {"shipped": "done-step", "cancelled": "done-step"},
                    "on_pr_merge": "shipped",
                    "on_pr_close": "cancelled",
                }
            }
        )
        url = "https://github.com/x/y/pull/20"
        store = FakeStore()
        item = store.create_item("cancelled work", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        store.create_step(
            "await-ship: cancelled work", step="await-ship", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(closed_prs={url}), worktrees, arbitrary_flow)

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).outcome, "cancelled")
        self.assertIn(item, worktrees.removed)

    def test_step_without_on_pr_close_not_abandoned_on_close(self):
        url = "https://github.com/x/y/pull/21"
        store, item, step, worktrees, uc = self._setup(
            url, FakeGitHub(closed_prs={url}), flow=_MERGE_ONLY_FLOW
        )

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_node(item).status, "ready")

    def test_closed_unmerged_pr_closes_story_whose_live_task_is_at_watch_pr(self):
        url = "https://github.com/x/y/pull/22"
        store = FakeStore()
        item = store.create_item("watched feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step(
            "watch-pr: watched feature", step="watch-pr", role="reviewer", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(closed_prs={url}), worktrees, _FLOW)

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).status, "done")
        self.assertEqual(store.get_node(step).status, "done")
        self.assertIn(item, worktrees.removed)


class TestMonitorPrsRework(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        f = flow or _REWORK_ONLY_FLOW
        store = FakeStore()
        item = store.create_item("in-review feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", pr_url)
        step = store.create_step(
            "ready-merge: in-review feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        complete = CompleteStepUseCase(store, _FlowAdapter(f))
        uc = MonitorPrsUseCase(store, github, worktrees, f, complete)
        return store, item, step, worktrees, uc

    def _rework_comment(self, ts):
        return (ts, Comment(author="reviewer", body="/rework fix the tests", is_top_level=True))

    def _inline_comment(self, ts):
        return (
            ts,
            Comment(
                author="reviewer",
                body="nit: rename this",
                is_top_level=False,
                path="src/foo.py",
                line=42,
            ),
        )

    def test_rework_comment_after_push_advances_task(self):
        url = "https://github.com/x/y/pull/30"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._rework_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        self.assertEqual(store.get_node(step).status, "done")
        self.assertEqual(store.get_node(step).outcome, "changes")

    def test_rework_creates_new_build_task(self):
        url = "https://github.com/x/y/pull/31"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._rework_comment(1500.0)])
        store, item, step, _, uc = self._setup(url, gh)

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"]
        self.assertEqual(len(steps), 1)
        new_task = steps[0]
        self.assertEqual(new_task.step, "build")
        self.assertEqual(new_task.status, "ready")

    def test_rework_note_forwards_guidance_including_inline_context(self):
        url = "https://github.com/x/y/pull/32"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_comments=[
                self._inline_comment(1200.0),
                self._rework_comment(1500.0),
            ],
        )
        store, item, step, _, uc = self._setup(url, gh)

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"]
        note = store.get_node(steps[0].id).notes
        self.assertIn("[src/foo.py:42]", note)
        self.assertIn("nit: rename this", note)

    def test_rework_note_excludes_marker_comment_body(self):
        url = "https://github.com/x/y/pull/33"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_comments=[
                self._rework_comment(1500.0),
            ],
        )
        store, item, step, _, uc = self._setup(url, gh)

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"]
        note = store.get_node(steps[0].id).notes or ""
        self.assertNotIn("/rework fix the tests", note)

    def test_inline_only_does_not_trigger_rework(self):
        url = "https://github.com/x/y/pull/34"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._inline_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertNotEqual(store.get_node(step).status, "done")
        self.assertEqual(worktrees.removed, [])

    def test_rework_comment_before_push_does_not_refire(self):
        url = "https://github.com/x/y/pull/35"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._rework_comment(500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertNotEqual(store.get_node(step).status, "done")

    def test_bot_comment_with_rework_marker_does_not_trigger(self):
        url = "https://github.com/x/y/pull/36"
        bot_comment = (1500.0, Comment(author="some-ci[bot]", body="/rework", is_top_level=True))
        gh = FakeGitHub(push_time=1000.0, timed_comments=[bot_comment])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_bot_comment_excluded_from_guidance(self):
        url = "https://github.com/x/y/pull/37"
        bot_inline = (
            1200.0,
            Comment(
                author="lint-bot[bot]",
                body="linting issue",
                is_top_level=False,
                path="src/x.py",
                line=1,
            ),
        )
        gh = FakeGitHub(
            push_time=1000.0,
            timed_comments=[
                bot_inline,
                self._rework_comment(1500.0),
            ],
        )
        store, item, step, _, uc = self._setup(url, gh)

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"]
        note = store.get_node(steps[0].id).notes or ""
        self.assertNotIn("linting issue", note)

    def test_arbitrary_rework_outcome_name_is_used(self):
        arbitrary_flow = flow_from_metas(
            {
                "gatekeeper": {
                    "step": "await-ship",
                    "routes": {"revise": "build-step"},
                    "on_pr_rework": "revise",
                }
            }
        )
        url = "https://github.com/x/y/pull/38"
        store = FakeStore()
        item = store.create_item("arbitrary rework", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step(
            "await-ship: arbitrary rework", step="await-ship", role="human", parent=item
        )
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._rework_comment(1500.0)])
        worktrees = FakeWorktrees()
        complete = CompleteStepUseCase(store, _FlowAdapter(arbitrary_flow))
        uc = MonitorPrsUseCase(store, gh, worktrees, arbitrary_flow, complete)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        self.assertEqual(store.get_node(step).outcome, "revise")

    def test_merged_pr_takes_merge_path_not_rework(self):
        url = "https://github.com/x/y/pull/39"
        gh = FakeGitHub(
            merged_prs={url}, push_time=1000.0, timed_comments=[self._rework_comment(1500.0)]
        )
        store, item, step, worktrees, uc = self._setup(url, gh, flow=_FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(result.reworked, [])
        self.assertEqual(store.get_node(item).status, "done")


class TestMonitorPrsConflict(unittest.TestCase):

    def _setup(self, pr_url, github, flow=None, prior_conflicts=0):
        f = flow or _CONFLICT_FLOW
        store = FakeStore()
        item = store.create_item("conflicting feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", pr_url)
        for _ in range(prior_conflicts):
            old = store.create_step("watch-step: conflicting feature", step="watch-step",
                                    role="watcher", parent=item)
            store.close(old, "conflicted")
        step = store.create_step("watch-step: conflicting feature", step="watch-step",
                                 role="watcher", parent=item)
        worktrees = FakeWorktrees()
        complete = CompleteStepUseCase(store, _FlowAdapter(f))
        uc = MonitorPrsUseCase(store, github, worktrees, f, complete)
        return store, item, step, worktrees, uc

    def test_conflicting_pr_advances_task_via_conflict_outcome(self):
        url = "https://github.com/x/y/pull/50"
        store, item, step, _, uc = self._setup(url, FakeGitHub(conflicted_prs={url}))

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).status, "done")
        self.assertEqual(store.get_node(step).outcome, "conflicted")

    def test_conflicting_pr_creates_fix_task(self):
        url = "https://github.com/x/y/pull/51"
        store, item, step, _, uc = self._setup(url, FakeGitHub(conflicted_prs={url}))

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"
                 and t.status != "done"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].step, "fix-step")

    def test_unknown_mergeable_state_does_not_trigger_conflict(self):
        url = "https://github.com/x/y/pull/52"
        store, item, step, _, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.conflicted, [])
        self.assertNotEqual(store.get_node(step).status, "done")

    def test_merged_pr_does_not_take_conflict_path(self):
        url = "https://github.com/x/y/pull/53"
        store, item, step, worktrees, uc = self._setup(
            url, FakeGitHub(merged_prs={url}, conflicted_prs={url}),
            flow=flow_from_metas({
                "watcher": {
                    "model": "sonnet",
                    "step": "watch-step",
                    "routes": {"merged": "done-step", "conflicted": "fix-step"},
                    "on_pr_merge": "merged",
                    "on_pr_conflict": "conflicted",
                },
            })
        )

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(result.conflicted, [])

    def test_arbitrary_step_names_work_for_conflict(self):
        url = "https://github.com/x/y/pull/54"
        arbitrary_flow = flow_from_metas({
            "sentinel": {
                "model": "claude",
                "step": "await-green",
                "routes": {"stuck": "untangle-step"},
                "on_pr_conflict": "stuck",
            }
        })
        store = FakeStore()
        item = store.create_item("arbitrary", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step("await-green: arbitrary", step="await-green",
                                 role="sentinel", parent=item)
        worktrees = FakeWorktrees()
        complete = CompleteStepUseCase(store, _FlowAdapter(arbitrary_flow))
        uc = MonitorPrsUseCase(store, FakeGitHub(conflicted_prs={url}), worktrees,
                               arbitrary_flow, complete)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "stuck")

    def test_escalates_after_cap_reached(self):
        url = "https://github.com/x/y/pull/55"
        store, item, step, _, uc = self._setup(
            url, FakeGitHub(conflicted_prs={url}), prior_conflicts=2)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "gave-up")

    def test_under_cap_uses_conflict_outcome(self):
        url = "https://github.com/x/y/pull/56"
        store, item, step, _, uc = self._setup(
            url, FakeGitHub(conflicted_prs={url}), prior_conflicts=1)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "conflicted")

    def test_escalated_task_surfaces_for_human(self):
        url = "https://github.com/x/y/pull/57"
        store, item, step, _, uc = self._setup(
            url, FakeGitHub(conflicted_prs={url}), prior_conflicts=2)

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"
                 and t.status != "done"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].role, "human")
        self.assertEqual(steps[0].step, "escalate-step")

    def test_conflict_fires_when_step_also_declares_rework(self):
        url = "https://github.com/x/y/pull/59"
        store = FakeStore()
        item = store.create_item("quad feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step("watch-pr: quad feature", step="watch-pr", role="reviewer",
                                 parent=item)
        complete = CompleteStepUseCase(store, _FlowAdapter(_READY_MERGE_QUAD_FLOW))
        uc = MonitorPrsUseCase(store, FakeGitHub(conflicted_prs={url}), FakeWorktrees(),
                               _READY_MERGE_QUAD_FLOW, complete)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(result.reworked, [])
        self.assertEqual(store.get_node(step).outcome, "conflicted")

    def test_rework_wins_over_conflict_when_both_conditions_true(self):
        url = "https://github.com/x/y/pull/60"
        store = FakeStore()
        item = store.create_item("both quad feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step("watch-pr: both quad feature", step="watch-pr", role="reviewer",
                                 parent=item)
        rework_comment = (1500.0, Comment(author="reviewer", body="/rework fix it",
                                          is_top_level=True))
        gh = FakeGitHub(conflicted_prs={url}, push_time=1000.0, timed_comments=[rework_comment])
        complete = CompleteStepUseCase(store, _FlowAdapter(_READY_MERGE_QUAD_FLOW))
        uc = MonitorPrsUseCase(store, gh, FakeWorktrees(), _READY_MERGE_QUAD_FLOW, complete)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        self.assertEqual(result.conflicted, [])
        self.assertEqual(store.get_node(step).outcome, "changes")

    def test_no_cap_declared_never_escalates(self):
        url = "https://github.com/x/y/pull/58"
        no_cap_flow = flow_from_metas({
            "watcher": {
                "model": "sonnet",
                "step": "watch-step",
                "routes": {"conflicted": "fix-step"},
                "on_pr_conflict": "conflicted",
            },
            "fixer": {
                "model": "sonnet",
                "step": "fix-step",
                "routes": {"resolved": "watch-step"},
            },
        })
        store = FakeStore()
        item = store.create_item("no-cap feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        for _ in range(5):
            old = store.create_step("watch-step: no-cap feature", step="watch-step",
                                    role="watcher", parent=item)
            store.close(old, "conflicted")
        step = store.create_step("watch-step: no-cap feature", step="watch-step",
                                 role="watcher", parent=item)
        complete = CompleteStepUseCase(store, _FlowAdapter(no_cap_flow))
        uc = MonitorPrsUseCase(store, FakeGitHub(conflicted_prs={url}), FakeWorktrees(),
                               no_cap_flow, complete)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "conflicted")


class FakeWorkers:
    def __init__(self):
        pass

    def workers_state(self):
        return []

    def pid_alive(self, pid, started=None):
        return False

    def reap(self):
        pass

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

    def engine_root(self):
        return "/grid"


class TestTickWithMonitor(unittest.TestCase):
    def test_tick_runs_monitor_and_returns_merged(self):
        url = "https://github.com/x/y/pull/5"
        store = FakeStore()
        item = store.create_item("merge me", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        store.create_step("ready-merge: merge me", step="ready-merge", role="human", parent=item)
        worktrees = FakeWorktrees()
        monitor = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FLOW)

        result = TickUseCase(
            store, FakeWorkers(), FakeSpawner(), FakeConfig(), monitor=monitor
        ).execute(TickInput(now=1000.0))

        self.assertEqual(result.merged, [item])
        self.assertEqual(result.abandoned, [])

    def test_tick_runs_monitor_and_returns_abandoned(self):
        url = "https://github.com/x/y/pull/6"
        store = FakeStore()
        item = store.create_item("abandoned me", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        store.create_step(
            "ready-merge: abandoned me", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        monitor = MonitorPrsUseCase(store, FakeGitHub(closed_prs={url}), worktrees, _FLOW)

        result = TickUseCase(
            store, FakeWorkers(), FakeSpawner(), FakeConfig(), monitor=monitor
        ).execute(TickInput(now=1000.0))

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(result.merged, [])

    def test_tick_without_monitor_has_empty_merged_and_abandoned(self):
        store = FakeStore()
        result = TickUseCase(store, FakeWorkers(), FakeSpawner(), FakeConfig()).execute(
            TickInput(now=1000.0)
        )
        self.assertEqual(result.merged, [])
        self.assertEqual(result.abandoned, [])
        self.assertEqual(result.reworked, [])


if __name__ == "__main__":
    unittest.main()
