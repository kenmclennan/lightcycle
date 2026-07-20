import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool import LC_MARKER, MonitorPrsUseCase, TickInput, TickUseCase
from lightcycle.application.services.flow import FlowService
from tests.support.fake_fs import FakeFs, flow_from_metas
from lightcycle.ports.github import Comment, Review
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore

_BOT_LOGIN = "copilot-pull-request-reviewer[bot]"


class _FlowAdapter:
    def __init__(self, flow):
        self._flow = flow

    def workflow_for(self, step):
        return "wf"

    def project_for(self, step):
        return None

    def load_flow(self, name=None, project=None):
        return self._flow

    def flow_for(self, node):
        return self._flow

    def flow_next(self, step, outcome, name=None, project=None):
        return self._flow.next(step, outcome)

    def outcomes_for(self, step, name=None, project=None):
        return self._flow.outcomes_for(step)

    def meta_for_step(self, step, name=None, project=None):
        return {}

    def owner_of(self, step, name=None, project=None):
        return self._flow.owner_of(step)

    def ci_failed_cap_outcome(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_outcome(step)

    def ci_failed_cap_n(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_n(step)

    def ci_failed_cap_target(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_target(step)

    def effective_transition(self, transition, outcome, prior_count, name=None, project=None):
        return self._flow.effective_transition(transition, outcome, prior_count)

    def phase_for(self, node):
        return "code"


_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build"},
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
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

_FEEDBACK_FLOW = flow_from_metas(
    {
        "handle-feedback": {
            "model": "sonnet",
            "step": "handle-feedback",
        },
        "reviewer": {
            "step": "ready-merge",
            "routes": {"changes": "build"},
            "on_pr_feedback": "handle-feedback",
            "on_mention_token": "@lc",
            "on_review_bot_allowlist": [_BOT_LOGIN],
        },
    }
)

_NO_MENTION_TOKEN_FLOW = flow_from_metas(
    {
        "handle-feedback": {
            "model": "sonnet",
            "step": "handle-feedback",
        },
        "reviewer": {
            "step": "ready-merge",
            "routes": {"changes": "build"},
            "on_pr_feedback": "handle-feedback",
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
    "handle-feedback": {
        "model": "sonnet",
        "step": "handle-feedback",
    },
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
        "on_pr_feedback": "handle-feedback",
        "on_pr_conflict": "conflicted",
        "on_mention_token": "@lc",
        "on_review_bot_allowlist": [_BOT_LOGIN],
    },
    "resolver": {
        "model": "sonnet",
        "step": "resolve-step",
        "routes": {"resolved": "watch-pr", "escalate": "human-step"},
    },
})


class FakeWorktrees:
    def __init__(self):
        self.removed = []

    def remove(self, item):
        self.removed.append(item)


class _TripwireFlow:
    def workflow_for(self, node):
        raise AssertionError("resolved the flow for a PR-less item")

    def flow_for(self, node):
        raise AssertionError("resolved the flow for a PR-less item")

    def load_flow(self, name=None):
        raise AssertionError("loaded the flow for a PR-less item")


class TestMonitorPrsSkipsPrlessItems(unittest.TestCase):
    def test_backlogged_item_with_an_inherited_selector_is_never_flow_resolved(self):
        store = FakeStore()
        theme = store.create_theme("t", workflow="lightcycle/spec-driven")
        store.create_item("backlog", theme=theme)
        uc = MonitorPrsUseCase(store, FakeGitHub(), FakeWorktrees(), _TripwireFlow())
        result = uc.execute()
        self.assertEqual(result.merged, [])
        self.assertEqual(result.abandoned, [])


class TestMonitorPrsMultiWorkflow(unittest.TestCase):
    def test_merge_reason_is_resolved_per_item_workflow(self):
        fs = FakeFs(
            metas={},
            workflow={
                "standard": (
                    "entry: write-code\n\n"
                    "edges:\n"
                    "  write-code   done    open-pr\n"
                    "  open-pr      done    await-merge\n"
                    "  await-merge  changes write-code\n\n"
                    "hooks:\n"
                    "  pr_merge   await-merge  merged\n"
                    "  pr_close   await-merge  abandoned\n"
                ),
                "spec": (
                    "entry: spec-writer\n\n"
                    "edges:\n"
                    "  spec-writer  done    open-pr\n"
                    "  open-pr      done    await-merge\n"
                    "  await-merge  changes spec-writer\n\n"
                    "hooks:\n"
                    "  pr_merge   await-merge  spec-merged\n"
                    "  pr_close   await-merge  abandoned\n"
                ),
            },
        )
        store = FakeStore()
        flow_service = FlowService(fs, store)

        code_item = store.create_item(
            "code feature", theme=store.create_theme("theme"), workflow="standard"
        )
        code_url = "https://github.com/x/y/pull/100"
        store.add_artifact(code_item, "pr", code_url)
        store.create_step(
            "await-merge: code feature", step="await-merge", role="human", parent=code_item
        )

        spec_item = store.create_item(
            "a spec", theme=store.create_theme("theme2"), workflow="spec"
        )
        spec_url = "https://github.com/x/y/pull/101"
        store.add_artifact(spec_item, "pr", spec_url)
        store.create_step(
            "await-merge: a spec", step="await-merge", role="human", parent=spec_item
        )

        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={code_url, spec_url})
        uc = MonitorPrsUseCase(store, github, worktrees, flow_service)

        result = uc.execute()

        self.assertEqual(set(result.merged), {code_item, spec_item})
        self.assertEqual(store.get_node(code_item).outcome, "merged")
        self.assertEqual(store.get_node(spec_item).outcome, "spec-merged")


_SPEC_DRIVEN = (
    "entry: spec-writer\n\n"
    "requires: brief repo\n\n"
    "workspace:\n"
    "  spec-await-merge  specs\n\n"
    "phase:\n"
    "  spec-writer       spec\n"
    "  spec-await-merge  spec\n"
    "  write-code        code\n"
    "  code-open-pr      code\n"
    "  code-await-merge  code\n\n"
    "nodes:\n"
    "  write-code        coder\n"
    "  spec-await-merge  await-merge\n"
    "  code-await-merge  await-merge\n\n"
    "edges:\n"
    "  spec-await-merge  spec-merged  write-code\n"
    "  spec-await-merge  changes      spec-writer\n"
    "  write-code        done         code-open-pr\n"
    "  code-await-merge  merged       cleanup\n"
    "  code-await-merge  changes      write-code\n\n"
    "hooks:\n"
    "  pr_merge  spec-await-merge  spec-merged\n"
    "  pr_merge  code-await-merge  merged\n"
    "  pr_close  spec-await-merge  abandoned\n"
    "  pr_close  code-await-merge  abandoned\n"
)


class TestMonitorPrsSpecMergeContinuesToCode(unittest.TestCase):
    def _setup(self):
        fs = FakeFs(
            metas={
                "coder": {"model": "sonnet", "accepts": {"spec": "required"}},
                "await-merge": {"step": "await-merge"},
            },
            workflow={"spec-driven": _SPEC_DRIVEN},
        )
        store = FakeStore()
        flow_service = FlowService(fs, store)
        spec_item = store.create_item(
            "LC-59: phase c1", theme=store.create_theme("theme"),
            workflow="spec-driven", project="lightcycle",
        )
        store.add_artifact(spec_item, "repo", "lightcycle")
        store.add_artifact(spec_item, "spec", "lightcycle/LC-59-phase-c1.md")
        store.add_artifact(spec_item, "branch", "spec/LC-59-phase-c1", label="spec")
        spec_url = "https://github.com/x/y/pull/101"
        store.add_artifact(spec_item, "pr", spec_url, label="spec")
        store.create_step(
            "spec-await-merge: LC-59", step="spec-await-merge", role="human", parent=spec_item
        )
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={spec_url})
        complete = CompleteStepUseCase(store, flow_service)
        uc = MonitorPrsUseCase(store, github, worktrees, flow_service, complete)
        return store, spec_item, uc, spec_url, worktrees, github

    def test_spec_merge_advances_the_same_item_to_write_code(self):
        store, spec_item, uc, spec_url, worktrees, github = self._setup()

        result = uc.execute()

        self.assertEqual(result.merged, [spec_item])
        node = store.get_node(spec_item)
        self.assertEqual(node.id, spec_item)
        self.assertEqual(node.workflow, "spec-driven")
        self.assertEqual(node.state, "in_progress")
        all_items = [n for n in store.all_nodes() if n.type == "item"]
        self.assertEqual([n.id for n in all_items], [spec_item])
        steps = [s for s in store.children(spec_item) if s.state != "done"]
        self.assertEqual([s.step for s in steps], ["write-code"])

    def test_crossing_the_phase_boundary_removes_the_spec_worktree(self):
        store, spec_item, uc, spec_url, worktrees, github = self._setup()

        uc.execute()

        self.assertEqual(worktrees.removed, [spec_item])

    def test_running_twice_does_not_re_advance(self):
        store, spec_item, uc, spec_url, worktrees, github = self._setup()
        uc.execute()
        first_run_steps = {s.id for s in store.children(spec_item)}

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertEqual({s.id for s in store.children(spec_item)}, first_run_steps)

    def test_phase_filtered_pr_lookup_ignores_the_merged_spec_pr_once_a_code_pr_is_open(self):
        store, spec_item, uc, spec_url, worktrees, github = self._setup()
        uc.execute()

        code_url = "https://github.com/x/y/pull/202"
        store.add_artifact(spec_item, "pr", code_url, label="code")

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertEqual(store.get_node(spec_item).state, "in_progress")


_SAME_REPO_TWO_PHASE = (
    "entry: feature-writer\n\n"
    "requires: brief repo\n\n"
    "phase:\n"
    "  feature-writer       feature\n"
    "  feature-await-merge  feature\n"
    "  write-code           code\n"
    "  code-await-merge     code\n\n"
    "nodes:\n"
    "  write-code           coder\n"
    "  feature-await-merge  await-merge\n"
    "  code-await-merge     await-merge\n\n"
    "edges:\n"
    "  feature-await-merge  feature-merged  write-code\n"
    "  feature-await-merge  changes         feature-writer\n"
    "  write-code           done            code-await-merge\n"
    "  code-await-merge     merged          cleanup\n\n"
    "hooks:\n"
    "  pr_merge  feature-await-merge  feature-merged\n"
    "  pr_merge  code-await-merge     merged\n"
    "  pr_close  feature-await-merge  abandoned\n"
    "  pr_close  code-await-merge     abandoned\n"
)


class TestMonitorPrsPhaseBoundarySameRepo(unittest.TestCase):
    def test_crossing_a_phase_boundary_removes_the_worktree_even_within_one_repo(self):
        fs = FakeFs(
            metas={
                "coder": {"model": "sonnet"},
                "await-merge": {"step": "await-merge"},
            },
            workflow={"bdd": _SAME_REPO_TWO_PHASE},
        )
        store = FakeStore()
        flow_service = FlowService(fs, store)
        item = store.create_item(
            "LC-7: login", theme=store.create_theme("theme"),
            workflow="bdd", project="app",
        )
        store.add_artifact(item, "repo", "app")
        store.add_artifact(item, "branch", "feat/LC-7-feature-login", label="feature")
        url = "https://github.com/x/y/pull/7"
        store.add_artifact(item, "pr", url, label="feature")
        store.create_step(
            "feature-await-merge: LC-7", step="feature-await-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        complete = CompleteStepUseCase(store, flow_service)
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, flow_service, complete)

        uc.execute()

        self.assertEqual(worktrees.removed, [item])


class TestMonitorPrsMerged(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        store = FakeStore()
        item = store.create_item("my feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", pr_url)
        step = store.create_step(
            "ready-merge: my feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, github, worktrees, _FlowAdapter(flow or _FLOW))
        return store, item, step, worktrees, uc

    def test_merged_pr_closes_story_and_children(self):
        url = "https://github.com/x/y/pull/1"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(step).state, "done")
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
        self.assertEqual(store.get_node(item).state, "ready")
        self.assertNotEqual(store.get_node(step).state, "done")
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
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FlowAdapter(_FLOW))

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
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FlowAdapter(_FLOW))

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(item).outcome, "merged")
        self.assertEqual(store.get_node(step).state, "done")
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
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FlowAdapter(_FLOW))

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(step).state, "done")

    def test_task_without_pr_artifact_is_skipped(self):
        store = FakeStore()
        item = store.create_item("no-pr feature", theme=store.create_theme("theme"))
        store.create_step(
            "ready-merge: no-pr feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={"anything"})
        uc = MonitorPrsUseCase(store, github, worktrees, _FlowAdapter(_FLOW))

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_task_without_parent_is_skipped(self):
        store = FakeStore()
        store.create_step("ready-merge: orphan", step="ready-merge", role="human")
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={"x"}), worktrees, _FlowAdapter(_FLOW))

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
        uc = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FlowAdapter(arbitrary_flow))

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
        uc = MonitorPrsUseCase(store, github, worktrees, _FlowAdapter(flow or _FLOW))
        return store, item, step, worktrees, uc

    def test_closed_unmerged_pr_closes_story(self):
        url = "https://github.com/x/y/pull/10"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(result.merged, [])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(step).state, "done")
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
        self.assertEqual(store.get_node(item).state, "ready")
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
        uc = MonitorPrsUseCase(store, FakeGitHub(closed_prs={url}), worktrees, _FlowAdapter(arbitrary_flow))

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
        self.assertEqual(store.get_node(item).state, "ready")

    def test_closed_unmerged_pr_closes_story_whose_live_task_is_at_watch_pr(self):
        url = "https://github.com/x/y/pull/22"
        store = FakeStore()
        item = store.create_item("watched feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step(
            "watch-pr: watched feature", step="watch-pr", role="reviewer", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, FakeGitHub(closed_prs={url}), worktrees, _FlowAdapter(_FLOW))

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(step).state, "done")
        self.assertIn(item, worktrees.removed)


class TestMonitorPrsFeedback(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        f = flow or _FEEDBACK_FLOW
        store = FakeStore()
        item = store.create_item("in-review feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", pr_url)
        step = store.create_step(
            "ready-merge: in-review feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        uc = MonitorPrsUseCase(store, github, worktrees, _FlowAdapter(f))
        return store, item, step, worktrees, uc

    def _spawned_feedback_steps(self, store, watched_step):
        return [
            t for t in store.all_nodes()
            if t.id != watched_step and t.type == "step" and t.step == "handle-feedback"
        ]

    def _mention_comment(self, ts, body="@lc fix the tests", author="reviewer", cid=None):
        return (
            ts,
            Comment(author=author, body=body, is_top_level=True,
                    id=cid or str(ts), created_at=ts),
        )

    def _inline_comment(self, ts, body="nit: rename this", author="reviewer",
                         cid=None, in_reply_to=None):
        return (
            ts,
            Comment(
                author=author,
                body=body,
                is_top_level=False,
                path="src/foo.py",
                line=42,
                id=cid or str(ts),
                in_reply_to_id=in_reply_to,
                created_at=ts,
            ),
        )

    def _bot_review(self, ts, author=_BOT_LOGIN, body="looks like a bug on line 12"):
        return (ts, Review(author=author, body=body, created_at=ts))

    def test_mention_comment_after_push_spawns_handle_feedback(self):
        url = "https://github.com/x/y/pull/30"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        spawned = self._spawned_feedback_steps(store, step)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0].role, "handle-feedback")
        self.assertEqual(spawned[0].parent, item)
        self.assertEqual(spawned[0].state, "ready")
        self.assertNotEqual(store.get_node(step).state, "done")
        watched = [a for a in store.item_artifacts(spawned[0].id) if a.type == "watched-step"]
        self.assertEqual([a.value for a in watched], [step])

    def test_inline_comment_without_mention_token_still_spawns(self):
        url = "https://github.com/x/y/pull/30-inline"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_comments=[self._inline_comment(1500.0, body="please rename this")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])

    def test_threaded_comment_with_lc_reply_does_not_spawn(self):
        url = "https://github.com/x/y/pull/30-threaded"
        root = self._inline_comment(1200.0, cid="c1")
        reply = self._inline_comment(
            1300.0, body="answered %s" % LC_MARKER, cid="c2", in_reply_to="c1"
        )
        gh = FakeGitHub(push_time=1000.0, timed_comments=[root, reply])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_allowlisted_bot_review_spawns(self):
        url = "https://github.com/x/y/pull/30-bot"
        gh = FakeGitHub(push_time=1000.0, timed_reviews=[self._bot_review(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])

    def test_non_allowlisted_bot_review_does_not_trigger(self):
        url = "https://github.com/x/y/pull/30-other-bot"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_reviews=[self._bot_review(1500.0, author="some-other[bot]")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertNotEqual(store.get_node(step).state, "done")

    def test_plain_comment_without_mention_token_does_not_trigger(self):
        url = "https://github.com/x/y/pull/34"
        gh = FakeGitHub(
            push_time=1000.0,
            timed_comments=[self._mention_comment(1500.0, body="just a plain comment")],
        )
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(worktrees.removed, [])

    def test_mention_comment_before_push_does_not_fire(self):
        url = "https://github.com/x/y/pull/35"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_bot_comment_with_mention_token_does_not_trigger(self):
        url = "https://github.com/x/y/pull/36"
        bot_comment = self._mention_comment(1500.0, body="@lc", author="some-ci[bot]")
        gh = FakeGitHub(push_time=1000.0, timed_comments=[bot_comment])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_lc_marked_comment_does_not_trigger(self):
        url = "https://github.com/x/y/pull/37"
        marked = self._mention_comment(
            1200.0, body="@lc already handled this %s" % LC_MARKER, author="lc"
        )
        gh = FakeGitHub(push_time=1000.0, timed_comments=[marked])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_lc_marked_review_does_not_trigger(self):
        url = "https://github.com/x/y/pull/37-review"
        marked = (
            1200.0,
            Review(author=_BOT_LOGIN, body="already replied %s" % LC_MARKER, created_at=1200.0),
        )
        gh = FakeGitHub(push_time=1000.0, timed_reviews=[marked])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_marked_reply_after_review_clears_it(self):
        url = "https://github.com/x/y/pull/37-review-replied"
        review = self._bot_review(1200.0)
        reply = self._mention_comment(
            1300.0, body="handled, ignoring %s" % LC_MARKER, author="lc"
        )
        gh = FakeGitHub(push_time=1000.0, timed_reviews=[review], timed_comments=[reply])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_no_mention_token_configured_never_fires_on_top_level(self):
        url = "https://github.com/x/y/pull/37-no-config"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh, flow=_NO_MENTION_TOKEN_FLOW)

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_no_double_spawn_when_one_already_open(self):
        url = "https://github.com/x/y/pull/40"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        uc.execute()
        uc.execute()

        self.assertEqual(len(self._spawned_feedback_steps(store, step)), 1)

    def test_watermark_advance_stops_the_same_mention_from_refiring(self):
        url = "https://github.com/x/y/pull/41"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        uc.execute()
        spawned = self._spawned_feedback_steps(store, step)
        store.close(spawned[0].id, "done")
        store.replace_artifact(step, "feedback-watermark", "1500.0")

        result = uc.execute()

        self.assertEqual(result.reworked, [])

    def test_closed_without_watermark_advance_does_not_duplicate_spawn(self):
        url = "https://github.com/x/y/pull/41-closed-early"
        gh = FakeGitHub(push_time=1000.0, timed_comments=[self._mention_comment(1500.0)])
        store, item, step, worktrees, uc = self._setup(url, gh)

        uc.execute()
        spawned = self._spawned_feedback_steps(store, step)
        store.close(spawned[0].id, "done")

        result = uc.execute()

        self.assertEqual(result.reworked, [])
        self.assertEqual(len(self._spawned_feedback_steps(store, step)), 0)

    def test_multi_round_new_comments_are_outstanding_independent_of_timestamp(self):
        url = "https://github.com/x/y/pull/42"
        round1 = self._inline_comment(1200.0, cid="c1")
        gh = FakeGitHub(push_time=1000.0, timed_comments=[round1])
        store, item, step, worktrees, uc = self._setup(url, gh)

        result1 = uc.execute()
        self.assertEqual(result1.reworked, [item])
        spawned1 = self._spawned_feedback_steps(store, step)
        self.assertEqual(len(spawned1), 1)

        reply1 = self._inline_comment(
            1250.0, body="queued %s" % LC_MARKER, cid="c1-reply", in_reply_to="c1"
        )
        store.close(spawned1[0].id, "done")
        gh._timed_comments = [round1, reply1]

        result2 = uc.execute()
        self.assertEqual(result2.reworked, [])

        round2 = self._inline_comment(1400.0, cid="c2", body="another nit")
        gh._timed_comments = [round1, reply1, round2]

        result3 = uc.execute()
        self.assertEqual(result3.reworked, [item])
        spawned3 = self._spawned_feedback_steps(store, step)
        self.assertEqual(len(spawned3), 1)

    def test_merged_pr_takes_merge_path_not_feedback(self):
        url = "https://github.com/x/y/pull/39"
        gh = FakeGitHub(
            merged_prs={url}, push_time=1000.0, timed_comments=[self._mention_comment(1500.0)]
        )
        store, item, step, worktrees, uc = self._setup(url, gh, flow=_FLOW)

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(result.reworked, [])
        self.assertEqual(store.get_node(item).state, "done")


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
        uc = MonitorPrsUseCase(store, github, worktrees, _FlowAdapter(f), complete)
        return store, item, step, worktrees, uc

    def test_conflicting_pr_advances_task_via_conflict_outcome(self):
        url = "https://github.com/x/y/pull/50"
        store, item, step, _, uc = self._setup(url, FakeGitHub(conflicted_prs={url}))

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).state, "done")
        self.assertEqual(store.get_node(step).outcome, "conflicted")

    def test_conflicting_pr_creates_fix_task(self):
        url = "https://github.com/x/y/pull/51"
        store, item, step, _, uc = self._setup(url, FakeGitHub(conflicted_prs={url}))

        uc.execute()

        steps = [t for t in store.all_nodes() if t.id != step and t.type == "step"
                 and t.state != "done"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].step, "fix-step")

    def test_unknown_mergeable_state_does_not_trigger_conflict(self):
        url = "https://github.com/x/y/pull/52"
        store, item, step, _, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.conflicted, [])
        self.assertNotEqual(store.get_node(step).state, "done")

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
                               _FlowAdapter(arbitrary_flow), complete)

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
                 and t.state != "done"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].role, "human")
        self.assertEqual(steps[0].step, "escalate-step")

    def test_conflict_fires_when_step_also_declares_feedback(self):
        url = "https://github.com/x/y/pull/59"
        store = FakeStore()
        item = store.create_item("quad feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step("watch-pr: quad feature", step="watch-pr", role="reviewer",
                                 parent=item)
        complete = CompleteStepUseCase(store, _FlowAdapter(_READY_MERGE_QUAD_FLOW))
        uc = MonitorPrsUseCase(store, FakeGitHub(conflicted_prs={url}), FakeWorktrees(),
                               _FlowAdapter(_READY_MERGE_QUAD_FLOW), complete)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(result.reworked, [])
        self.assertEqual(store.get_node(step).outcome, "conflicted")

    def test_feedback_wins_over_conflict_when_both_conditions_true(self):
        url = "https://github.com/x/y/pull/60"
        store = FakeStore()
        item = store.create_item("both quad feature", theme=store.create_theme("theme"))
        store.add_artifact(item, "pr", url)
        step = store.create_step("watch-pr: both quad feature", step="watch-pr", role="reviewer",
                                 parent=item)
        feedback_comment = (
            1500.0,
            Comment(author="reviewer", body="@lc fix it", is_top_level=True,
                    id="c1", created_at=1500.0),
        )
        gh = FakeGitHub(conflicted_prs={url}, push_time=1000.0, timed_comments=[feedback_comment])
        complete = CompleteStepUseCase(store, _FlowAdapter(_READY_MERGE_QUAD_FLOW))
        uc = MonitorPrsUseCase(store, gh, FakeWorktrees(), _FlowAdapter(_READY_MERGE_QUAD_FLOW), complete)

        result = uc.execute()

        self.assertEqual(result.reworked, [item])
        self.assertEqual(result.conflicted, [])
        self.assertNotEqual(store.get_node(step).state, "done")
        spawned = [
            t for t in store.all_nodes()
            if t.id != step and t.type == "step" and t.step == "handle-feedback"
        ]
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0].parent, item)

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
                               _FlowAdapter(no_cap_flow), complete)

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
        monitor = MonitorPrsUseCase(store, FakeGitHub(merged_prs={url}), worktrees, _FlowAdapter(_FLOW))

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
        monitor = MonitorPrsUseCase(store, FakeGitHub(closed_prs={url}), worktrees, _FlowAdapter(_FLOW))

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
