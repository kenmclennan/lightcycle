import unittest

from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_git import FakeGit
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore


def plant_pr(store, item, url, phase=None, branch=None):
    current = store.current_pass(item) or store.get_pass(store.open_pass(item))
    rid = store.open_run(item, current.id, phase)
    store.set_branch(rid, branch)
    store.set_pr(rid, url)
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
        return self._flow.step_def(getattr(node, "stage", None)).phase

    def phase_for_stage(self, stage, name=None):
        return "code"

    def ends_pass(self, stage, outcome, name=None):
        return False


_URL = "https://github.com/x/y/pull/90"
_BRANCH = "feat/thing"
_ROOT = "/repo/thing"

_FLOW = flow_from_metas({
    "poller": {
        "engine": True,
        "step": "poll-ci",
        "routes": {"succeeded": "watch-ci", "failed": "watch-ci"},
        "on_ci_success": "succeeded",
        "on_ci_failure": "failed",
    },
    "watcher": {
        "model": "sonnet",
        "step": "watch-ci",
    },
})

_NO_HOOKS_FLOW = flow_from_metas({
    "poller": {
        "engine": True,
        "step": "poll-ci",
        "routes": {"succeeded": "watch-ci"},
    },
    "watcher": {
        "model": "sonnet",
        "step": "watch-ci",
    },
})


class TestResolveCiUseCase(unittest.TestCase):
    def _setup(self, github, git, flow=_FLOW, worktree_path=_ROOT):
        store = FakeStore()
        item = store.create_item("building a thing", "a description")
        plant_pr(store, item, _URL, branch=_BRANCH)
        step = store.create_step(step="poll-ci", role="engine", parent=item)

        class _Worktrees:
            def worktree_path(self, item_id):
                return worktree_path

        complete = CompleteStepUseCase(store, _FlowAdapter(flow))
        uc = ResolveCiUseCase(store, github, git, _Worktrees(), _FlowAdapter(flow), complete)
        return store, item, step, uc

    def test_ci_still_pending_does_not_complete(self):
        gh = FakeGitHub(check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="in_progress", conclusion=None),)
        })
        git = FakeGit(head_shas={(_ROOT, _BRANCH): "sha1"})
        store, item, step, uc = self._setup(gh, git)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])

    def test_check_runs_read_failure_never_advances(self):
        gh = FakeGitHub(failing_calls={"check_runs"})
        git = FakeGit(head_shas={(_ROOT, _BRANCH): "sha1"})
        store, item, step, uc = self._setup(gh, git)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])

    def test_ci_succeeded_completes_with_the_declared_outcome(self):
        gh = FakeGitHub(check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)
        })
        git = FakeGit(head_shas={(_ROOT, _BRANCH): "sha1"})
        store, item, step, uc = self._setup(gh, git)

        result = uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "succeeded")
        self.assertEqual(result.ci_resolved, [item])

    def test_ci_failed_completes_with_the_declared_outcome_and_names_the_check(self):
        gh = FakeGitHub(check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="failure"),)
        })
        git = FakeGit(head_shas={(_ROOT, _BRANCH): "sha1"})
        store, item, step, uc = self._setup(gh, git)

        result = uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "failed")
        next_step = next(c for c in store.children(item) if c.stage == "watch-ci")
        self.assertIn("build", next_step.notes or "")
        self.assertEqual(result.ci_resolved, [item])

    def test_stage_with_no_ci_hooks_declared_is_skipped(self):
        gh = FakeGitHub(check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)
        })
        git = FakeGit(head_shas={(_ROOT, _BRANCH): "sha1"})
        store, item, step, uc = self._setup(gh, git, flow=_NO_HOOKS_FLOW)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])

    def test_no_worktree_path_never_advances(self):
        gh = FakeGitHub(check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)
        })
        git = FakeGit(head_shas={(_ROOT, _BRANCH): "sha1"})
        store, item, step, uc = self._setup(gh, git, worktree_path=None)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])

    def test_no_remote_head_sha_never_advances(self):
        gh = FakeGitHub(check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)
        })
        git = FakeGit(head_shas={})
        store, item, step, uc = self._setup(gh, git)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])


if __name__ == "__main__":
    unittest.main()
