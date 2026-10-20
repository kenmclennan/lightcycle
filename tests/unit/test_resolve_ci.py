import unittest

from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun, NotYetRead
from tests.support.fake_fs import flow_from_metas
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

    def review_rounds_cap_outcome(self, step, name=None, project=None):
        cap = self._flow.step_def(step).review_rounds_cap
        return cap.outcome if cap else None

    def review_rounds_transition(self, transition, outcome, prior_count, name=None, project=None):
        return self._flow.review_rounds_transition(transition, outcome, prior_count, None)

    def phase_for(self, node):
        return self._flow.step_def(getattr(node, "stage", None)).phase

    def phase_for_stage(self, stage, name=None):
        return "code"

    def ends_pass(self, stage, outcome, name=None):
        return False


_URL = "https://github.com/x/y/pull/90"
_BRANCH = "feat/thing"

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


class TestResolveCiJudgedSha(unittest.TestCase):
    def _judged(self, conclusion, checks_sha="sha1"):
        store = FakeStore()
        item = store.create_item("building a thing", "a description")
        plant_pr(store, item, _URL, branch=_BRANCH)
        step = store.create_step(step="poll-ci", role="engine", parent=item)

        gh = FakeGitHub(head_shas={_URL: "sha1"}, check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status=conclusion[0], conclusion=conclusion[1]),)
        })
        flow = _FlowAdapter(_FLOW)
        ResolveCiUseCase(store, gh, flow, CompleteStepUseCase(store, flow)).execute()
        return [a.value for a in store.item_artifacts(step) if a.type == "ci-judged-sha"]

    def test_success_writes_the_judged_sha(self):
        self.assertEqual(self._judged(("completed", "success")), ["sha1"])

    def test_failure_writes_the_judged_sha(self):
        self.assertEqual(self._judged(("completed", "failure")), ["sha1"])

    def test_pending_writes_nothing(self):
        self.assertEqual(self._judged(("in_progress", None)), [])


class _SequencedGitHub(FakeGitHub):
    def __init__(self, shas, **kw):
        super().__init__(**kw)
        self._sequence = list(shas)

    def head_sha(self, pr):
        return self._sequence.pop(0) if self._sequence else NotYetRead()


_FAIL_URL = "https://github.com/x/y/actions/runs/7/job/8"


def _failing(sha, url=_FAIL_URL):
    return {(_URL, sha): (CheckRun(name="build", status="completed", conclusion="failure", url=url),)}


class TestResolveCiConfirmsHeadBeforeFailed(unittest.TestCase):
    def _setup(self, github):
        store = FakeStore()
        item = store.create_item("building a thing", "a description")
        plant_pr(store, item, _URL, branch=_BRANCH)
        step = store.create_step(step="poll-ci", role="engine", parent=item)

        flow = _FlowAdapter(_FLOW)
        uc = ResolveCiUseCase(store, github, flow, CompleteStepUseCase(store, flow))
        return store, item, step, uc

    def _judged(self, store, step):
        return [a.value for a in store.item_artifacts(step) if a.type == "ci-judged-sha"]

    def test_unchanged_head_completes_failed_and_names_sha_check_url_and_pr(self):
        store, item, step, uc = self._setup(_SequencedGitHub(["sha1", "sha1"], check_runs_by_sha=_failing("sha1")))

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.outcome, "failed")
        self.assertEqual(self._judged(store, step), ["sha1"])
        self.assertEqual(node.report, "CI failed on sha1: check 'build' %s, PR %s." % (_FAIL_URL, _URL))

    def test_moved_head_routes_nothing_then_repoll_reaches_the_new_head(self):
        passing = {(_URL, "sha2"): (CheckRun(name="build", status="completed", conclusion="success"),)}
        store, item, step, uc = self._setup(_SequencedGitHub(
            ["sha1", "sha2", "sha2", "sha2"], check_runs_by_sha={**_failing("sha1"), **passing},
        ))

        first = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(first.ci_resolved, [])
        self.assertEqual(self._judged(store, step), [])
        self.assertEqual([c for c in store.children(item) if c.stage == "watch-ci"], [])

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "succeeded")

    def test_unreadable_confirm_read_routes_nothing(self):
        store, item, step, uc = self._setup(_SequencedGitHub(["sha1", None], check_runs_by_sha=_failing("sha1")))

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])
        self.assertEqual(self._judged(store, step), [])

    def test_moved_then_settled_head_fails_naming_the_new_sha(self):
        store, item, step, uc = self._setup(_SequencedGitHub(
            ["sha1", "sha2", "sha2", "sha2"],
            check_runs_by_sha={**_failing("sha1"), **_failing("sha2")},
        ))

        uc.execute()
        self.assertEqual(store.get_node(step).state, State.QUEUED)

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.outcome, "failed")
        self.assertIn("sha2", node.report)
        self.assertNotIn("sha1", node.report)

    def test_empty_url_leaves_no_stray_space(self):
        store, item, step, uc = self._setup(_SequencedGitHub(["sha1", "sha1"], check_runs_by_sha=_failing("sha1", url="")))

        uc.execute()

        self.assertEqual(store.get_node(step).report, "CI failed on sha1: check 'build', PR %s." % _URL)

    def test_success_on_a_moved_head_is_unchanged(self):
        gh = _SequencedGitHub(["sha1", "sha2"], check_runs_by_sha={(_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)})
        store, item, step, uc = self._setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "succeeded")


class TestResolveCiUseCase(unittest.TestCase):
    def _setup(self, github, flow=_FLOW):
        store = FakeStore()
        item = store.create_item("building a thing", "a description")
        plant_pr(store, item, _URL, branch=_BRANCH)
        step = store.create_step(step="poll-ci", role="engine", parent=item)

        complete = CompleteStepUseCase(store, _FlowAdapter(flow))
        uc = ResolveCiUseCase(store, github, _FlowAdapter(flow), complete)
        return store, item, step, uc

    def test_ci_still_pending_does_not_complete(self):
        gh = FakeGitHub(head_shas={_URL: "sha1"}, check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="in_progress", conclusion=None),)
        })
        store, item, step, uc = self._setup(gh)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])

    def test_check_runs_read_failure_never_advances(self):
        gh = FakeGitHub(head_shas={_URL: "sha1"}, failing_calls={"check_runs"})
        store, item, step, uc = self._setup(gh)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])

    def test_ci_succeeded_completes_with_the_declared_outcome(self):
        gh = FakeGitHub(head_shas={_URL: "sha1"}, check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)
        })
        store, item, step, uc = self._setup(gh)

        result = uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "succeeded")
        self.assertEqual(result.ci_resolved, [item])

    def test_ci_failed_completes_with_the_declared_outcome_and_names_the_check(self):
        gh = FakeGitHub(head_shas={_URL: "sha1"}, check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="failure"),)
        })
        store, item, step, uc = self._setup(gh)

        result = uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "failed")
        next_step = next(c for c in store.children(item) if c.stage == "watch-ci")
        self.assertIn("build", node.report or "")
        self.assertEqual(next_step.previous_step, step)
        self.assertEqual(result.ci_resolved, [item])

    def test_stage_with_no_ci_hooks_declared_is_skipped(self):
        gh = FakeGitHub(head_shas={_URL: "sha1"}, check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)
        })
        store, item, step, uc = self._setup(gh, flow=_NO_HOOKS_FLOW)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])

    def test_unreadable_head_never_advances(self):
        gh = FakeGitHub(check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status="completed", conclusion="success"),)
        })
        store, item, step, uc = self._setup(gh)

        result = uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual(result.ci_resolved, [])


if __name__ == "__main__":
    unittest.main()
