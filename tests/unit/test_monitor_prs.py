import unittest

from lightcycle.application.pool import MonitorPrsUseCase, TickInput, TickUseCase
from tests.support.fake_fs import flow_from_metas
from lightcycle.ports.github import Comment
from tests.support.fake_github import FakeGitHub
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_store import FakeStore

_BOT_LOGIN = "copilot-pull-request-reviewer[bot]"


def plant_pr(store, item, url, phase=None, branch=None, n=1, state="open"):
    while store.current_pass(item) is None or store.current_pass(item).n < n:
        current = store.current_pass(item)
        if current is not None:
            store.close_pass(current.id)
        store.open_pass(item)
    rid = store.open_run(item, store.current_pass(item).id, phase)
    store.set_branch(rid, branch)
    store.set_pr(rid, url)
    if state != "open":
        store.close_run(rid, state)
    return rid


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
        return sorted(self._flow.step_def(step).routes.keys())

    def meta_for_step(self, step, name=None, project=None):
        return {}

    def owner_of(self, step, name=None, project=None):
        return self._flow.step_def(step).owner

    def ci_failed_cap_outcome(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.outcome if cap else None

    def ci_failed_cap_n(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.n if cap else None

    def ci_failed_cap_target(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.target if cap else None

    def effective_transition(self, transition, outcome, prior_count, name=None, project=None):
        return self._flow.effective_transition(transition, outcome, prior_count)

    def phase_for(self, node):
        return self._flow.step_def(getattr(node, "step", None)).phase

    def phase_for_stage(self, stage, name=None):
        return "code"

    def ends_pass(self, stage, outcome, name=None):
        return False


_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build"},
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
        }
    },
    disposition={"merged": "completed", "abandoned": "aborted"},
)


class FakeWorktrees:
    def release_run(self, run, delete_remote=True):
        self.released = getattr(self, "released", [])
        self.released.append(run.id)

    def __init__(self):
        self.removed = []

    def remove(self, item):
        self.removed.append(item)


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

    def mark_checked(self, spawnid):
        pass

    def log_mtime(self, path):
        return None


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

    def stall_seconds(self):
        return 1800

    def engine_root(self):
        return "/grid"

    def ci_release_cap(self):
        return 3


class TestTickWithMonitor(unittest.TestCase):
    def test_tick_runs_monitor_and_returns_merged(self):
        url = "https://github.com/x/y/pull/5"
        store = FakeStore()
        item = store.create_item("merge me", "a description")
        plant_pr(store, item, url)
        store.create_step("ready-merge: merge me", step="ready-merge", role="human", parent=item)
        worktrees = FakeWorktrees()
        monitor = MonitorPrsUseCase(
            store, FakeGitHub(merged_prs={url}), worktrees, _FlowAdapter(_FLOW), spin_port=FakeSpinPort()
        )

        result = TickUseCase(
            store, FakeWorkers(), FakeSpawner(), FakeConfig(), monitor=monitor
        ).execute(TickInput(now=1000.0))

        self.assertEqual(result.merged, [item])
        self.assertEqual(result.abandoned, [])

    def test_tick_runs_monitor_and_returns_abandoned(self):
        url = "https://github.com/x/y/pull/6"
        store = FakeStore()
        item = store.create_item("abandoned me", "a description")
        plant_pr(store, item, url)
        store.create_step(
            "ready-merge: abandoned me", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        monitor = MonitorPrsUseCase(
            store, FakeGitHub(closed_prs={url}), worktrees, _FlowAdapter(_FLOW), spin_port=FakeSpinPort()
        )

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


class TestMonitorPrsUseCaseComposesAllThreeJobs(unittest.TestCase):
    def test_execute_reflects_a_merge_a_feedback_dispatch_and_a_ci_release_in_one_call(self):
        flow = flow_from_metas(
            {
                "reviewer": {
                    "step": "ready-merge",
                    "routes": {"merged": "cleanup"},
                    "on_pr_merge": "merged",
                },
                "handle-feedback": {
                    "model": "sonnet",
                    "step": "handle-feedback",
                },
                "watcher": {
                    "model": "sonnet",
                    "step": "watch-pr",
                    "routes": {"changes": "build"},
                    "on_pr_feedback": "handle-feedback",
                },
                "review-features": {
                    "model": "sonnet",
                    "step": "review-features",
                    "routes": {"done": "await-merge"},
                },
            },
            disposition={"merged": "completed"},
        )
        store = FakeStore()

        merge_item = store.create_item("merge me", "a description")
        merge_url = "https://github.com/x/y/pull/500"
        plant_pr(store, merge_item, merge_url)
        store.create_step(
            "ready-merge: merge me", step="ready-merge", role="human", parent=merge_item
        )

        feedback_item = store.create_item("in review", "a description")
        feedback_url = "https://github.com/x/y/pull/501"
        plant_pr(store, feedback_item, feedback_url)
        store.create_step(
            "watch-pr: in review", step="watch-pr", role="agent", parent=feedback_item
        )

        ci_item = store.create_item("ci pending", "a description")
        ci_url = "https://github.com/x/y/pull/502"
        plant_pr(store, ci_item, ci_url)
        ci_step = store.create_step(
            "review-features: ci pending", step="review-features", role="human", parent=ci_item
        )
        store.label_add(ci_step, "ci-pending")

        comment = Comment(
            author="reviewer", body="please rename this", is_top_level=False,
            id="c1", created_at=1500.0,
        )
        gh = FakeGitHub(
            merged_prs={merge_url},
            push_time=1000.0,
            timed_comments=[(1500.0, comment)],
            head_shas={ci_url: "sha1"},
            ci_pending_by_sha={(ci_url, "sha1"): False},
        )

        uc = MonitorPrsUseCase(
            store, gh, FakeWorktrees(), _FlowAdapter(flow), spin_port=FakeSpinPort(),
            config=FakeConfig(),
        )

        result = uc.execute()

        self.assertEqual(result.merged, [merge_item])
        self.assertEqual(result.reworked, [feedback_item])
        self.assertEqual(result.ci_released, [ci_item])

