import time
import unittest

from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun, NotYetRead, ReadFailure
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

    def unpinned_workflow(self, node):
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
        ResolveCiUseCase(store, gh, flow, CompleteStepUseCase(store, flow), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0).execute()
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
        uc = ResolveCiUseCase(store, github, flow, CompleteStepUseCase(store, flow), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0)
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
        uc = ResolveCiUseCase(store, github, _FlowAdapter(flow), complete, clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0)
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


class _ScriptedGitHub(FakeGitHub):
    def __init__(self, head, checks):
        super().__init__()
        self.head = head
        self.checks = checks

    def head_sha(self, pr):
        return self.head

    def check_runs(self, pr, sha):
        return self.checks


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


_GREEN = (CheckRun(name="build", status="completed", conclusion="success"),)


class TestCiUnreadDiagnostics(unittest.TestCase):
    def _setup(self, github):
        store = FakeStore()
        item = store.create_item("building a thing", "a description")
        plant_pr(store, item, _URL, branch=_BRANCH)
        step = store.create_step(step="poll-ci", role="engine", parent=item)
        flow = _FlowAdapter(_FLOW)
        clock = _Clock()
        uc = ResolveCiUseCase(
            store, github, flow, CompleteStepUseCase(store, flow),
            clock=clock, poll_seconds=lambda: 60,
            ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0)
        return store, item, step, uc, clock

    def _run(self, uc, clock, at):
        clock.now = at
        return [(u.step, u.reason, u.detail) for u in uc.execute().ci_unread]

    def test_an_unpolled_snapshot_logs_head_not_yet_read_once_past_the_interval(self):
        snapshot = PrSnapshot(FakeGitHub())
        _, _, step, uc, clock = self._setup(snapshot)

        self.assertEqual(self._run(uc, clock, 0.0), [])
        self.assertEqual(self._run(uc, clock, 60.0), [])
        self.assertEqual(
            self._run(uc, clock, 65.0), [(step, "head-not-yet-read", "no snapshot yet")])
        self.assertEqual(self._run(uc, clock, 70.0), [])
        self.assertEqual(self._run(uc, clock, 600.0), [])

    def test_a_published_view_without_checks_logs_checks_not_yet_read(self):
        github = _ScriptedGitHub("sha1", NotYetRead())
        _, _, step, uc, clock = self._setup(github)

        self._run(uc, clock, 0.0)

        self.assertEqual(
            self._run(uc, clock, 61.0), [(step, "checks-not-yet-read", "no snapshot yet")])

    def test_a_head_read_failure_logs_head_read_failed_with_the_stderr(self):
        github = _ScriptedGitHub(ReadFailure(1, "boom"), _GREEN)
        _, _, step, uc, clock = self._setup(github)

        self._run(uc, clock, 0.0)

        self.assertEqual(self._run(uc, clock, 61.0), [(step, "head-read-failed", "boom")])

    def test_a_checks_read_failure_logs_checks_read_failed_with_the_stderr(self):
        github = _ScriptedGitHub("sha1", ReadFailure(1, "boom"))
        _, _, step, uc, clock = self._setup(github)

        self._run(uc, clock, 0.0)

        self.assertEqual(self._run(uc, clock, 61.0), [(step, "checks-read-failed", "boom")])

    def test_each_change_of_reason_logs_one_line(self):
        github = _ScriptedGitHub("sha1", NotYetRead())
        _, _, step, uc, clock = self._setup(github)
        lines = []

        self._run(uc, clock, 0.0)
        lines += self._run(uc, clock, 61.0)
        github.checks = ReadFailure(1, "boom")
        lines += self._run(uc, clock, 66.0)
        lines += self._run(uc, clock, 71.0)
        github.checks = NotYetRead()
        lines += self._run(uc, clock, 76.0)

        self.assertEqual(
            [reason for _, reason, _ in lines],
            ["checks-not-yet-read", "checks-read-failed", "checks-not-yet-read"])

    def test_a_step_that_recovers_and_fails_again_starts_a_new_episode(self):
        github = _ScriptedGitHub("sha1", NotYetRead())
        _, _, step, uc, clock = self._setup(github)

        self._run(uc, clock, 0.0)
        self.assertEqual(len(self._run(uc, clock, 61.0)), 1)
        github.checks = (CheckRun(name="build", status="in_progress", conclusion=None),)
        self.assertEqual(self._run(uc, clock, 66.0), [])
        github.checks = NotYetRead()
        self.assertEqual(self._run(uc, clock, 71.0), [])
        self.assertEqual(self._run(uc, clock, 131.0), [])
        self.assertEqual(
            self._run(uc, clock, 132.0), [(step, "checks-not-yet-read", "no snapshot yet")])

    def test_only_the_unreadable_step_is_reported_and_the_readable_one_still_resolves(self):
        store = FakeStore()
        flow = _FlowAdapter(_FLOW)
        clock = _Clock()
        stuck_item = store.create_item("stuck", "a description")
        plant_pr(store, stuck_item, "https://github.com/acme/widget/pull/9", branch="feat/stuck")
        stuck = store.create_step(step="poll-ci", role="engine", parent=stuck_item)
        ok_item = store.create_item("fine", "a description")
        plant_pr(store, ok_item, _URL, branch=_BRANCH)
        fine = store.create_step(step="poll-ci", role="engine", parent=ok_item)

        class _Split(_ScriptedGitHub):
            def head_sha(self, pr):
                return NotYetRead() if pr.endswith("/9") else "sha1"

        split = _Split("sha1", _GREEN)
        uc = ResolveCiUseCase(
            store, split, flow, CompleteStepUseCase(store, flow),
            clock=clock, poll_seconds=lambda: 60,
            ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0)
        clock.now = 0.0
        first = uc.execute()
        clock.now = 61.0
        second = uc.execute()

        self.assertEqual(first.ci_resolved, [ok_item])
        self.assertEqual(store.get_node(fine).state, State.DONE)
        self.assertEqual([u.step for u in second.ci_unread], [stuck])


def _ci_setup(github):
    store = FakeStore()
    item = store.create_item("building a thing", "a description")
    plant_pr(store, item, _URL, branch=_BRANCH)
    step = store.create_step(step="poll-ci", role="engine", parent=item)
    flow = _FlowAdapter(_FLOW)
    uc = ResolveCiUseCase(
        store, github, flow, CompleteStepUseCase(store, flow),
        clock=time.monotonic, poll_seconds=lambda: 60,
        ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0,
    )
    return store, item, step, uc


def _gh(runs, required=None, failing=(), **kw):
    by_base = {"acme/widget@main": required} if required is not None else None
    return FakeGitHub(
        head_shas={_URL: "sha1"}, check_runs_by_sha={(_URL, "sha1"): tuple(runs)},
        required_by_base=by_base, failing_calls=failing, **kw,
    )


def _ok(name):
    return CheckRun(name=name, status="completed", conclusion="success")


def _hung(name, started_at, url=""):
    return CheckRun(name=name, status="in_progress", conclusion=None, url=url, started_at=started_at)


class TestRequiredChecksAndCeiling(unittest.TestCase):
    def test_required_green_with_a_non_required_in_progress_succeeds(self):
        gh = _gh([_ok("build"), _ok("test"), _hung("codacy", 9900.0)], required={"build", "test"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.outcome, "succeeded")
        self.assertEqual([a.value for a in store.item_artifacts(step) if a.type == "ci-judged-sha"], ["sha1"])

    def test_required_in_progress_under_ceiling_keeps_waiting(self):
        gh = _gh([_hung("build", 9900.0), _ok("test")], required={"build", "test"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)

    def test_check_exactly_at_the_ceiling_keeps_waiting(self):
        gh = _gh([_hung("build", 6400.0)], required={"build"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)

    def test_check_past_the_ceiling_fails_naming_check_and_ceiling(self):
        gh = _gh([_hung("build", 6399.0, url="http://x/1")], required={"build"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.outcome, "failed")
        self.assertIn("check 'build' http://x/1", node.report)
        self.assertIn("3601s", node.report)
        self.assertIn("ceiling of 3600s", node.report)
        self.assertEqual([a.value for a in store.item_artifacts(step) if a.type == "ci-judged-sha"], ["sha1"])

    def test_no_required_set_keeps_today_rule_under_ceiling(self):
        gh = _gh([_hung("codacy", 9900.0)])
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)

    def test_no_required_set_green_succeeds(self):
        store, item, step, uc = _ci_setup(_gh([_ok("build")]))

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "succeeded")

    def test_no_required_set_hung_over_ceiling_times_out(self):
        store, item, step, uc = _ci_setup(_gh([_hung("codacy", 1000.0)]))

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "failed")
        self.assertIn("codacy", store.get_node(step).report)

    def test_failed_required_read_judges_all_checks(self):
        gh = _gh([_ok("build"), _hung("codacy", 1000.0)], required={"build"}, failing={"required_checks"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "failed")

    def test_unpublished_sync_state_judges_all_checks(self):
        gh = _gh([_ok("build"), _hung("codacy", 1000.0)], required={"build"}, failing={"pr_sync_state"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "failed")

    def test_failing_non_required_check_is_not_named(self):
        gh = _gh([_ok("build"), CheckRun("codacy", "completed", "failure")], required={"build"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "succeeded")

    def test_failed_required_check_is_named(self):
        gh = _gh([CheckRun("build", "completed", "failure"), _ok("codacy")], required={"build"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertIn("check 'build'", store.get_node(step).report)

    def test_timeout_skips_when_head_moved(self):
        class _Moving(FakeGitHub):
            def __init__(self, **kw):
                super().__init__(**kw)
                self._n = 0

            def head_sha(self, pr):
                self._n += 1
                return "sha1" if self._n == 1 else "sha2"

        gh = _Moving(
            head_shas={_URL: "sha1"},
            check_runs_by_sha={(_URL, "sha1"): (_hung("build", 1000.0),)},
        )
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)

    def test_constructor_fails_naming_a_missing_ceiling(self):
        def _missing():
            raise ValueError("ci-check-ceiling-seconds")

        with self.assertRaises(ValueError):
            ResolveCiUseCase(
                FakeStore(), FakeGitHub(), None, None, clock=time.monotonic, poll_seconds=lambda: 60,
                ci_ceiling_seconds=_missing, wall_clock=lambda: 0.0,
            )
