import time
import unittest
from tests.support.null_collaborators import NoopWorktrees

from lightcycle.application.flow.complete_step import CompleteInput, CompleteStepUseCase
from lightcycle.application.pool.pr_snapshot import PrSnapshot
from lightcycle.application.work.close_item import CloseItemUseCase
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun, NotYetRead, ReadFailure, WorkflowFile
from tests.support.fake_view_freshness import AlwaysConfirmed, NeverConfirmed
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

    def escalated_transition(self, transition, outcome, history, name=None, project=None):
        return self._flow.escalated_transition(transition, outcome, history, lambda key: None)

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
        step = store.create_step(stage="poll-ci", role="engine", item=item)

        gh = FakeGitHub(head_shas={_URL: "sha1"}, check_runs_by_sha={
            (_URL, "sha1"): (CheckRun(name="build", status=conclusion[0], conclusion=conclusion[1]),)
        })
        flow = _FlowAdapter(_FLOW)
        ResolveCiUseCase(store, gh, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None), close_item=CloseItemUseCase(store, NoopWorktrees()), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset()).execute()
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
        step = store.create_step(stage="poll-ci", role="engine", item=item)

        flow = _FlowAdapter(_FLOW)
        uc = ResolveCiUseCase(store, github, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None), close_item=CloseItemUseCase(store, NoopWorktrees()), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())
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
        step = store.create_step(stage="poll-ci", role="engine", item=item)

        complete = CompleteStepUseCase(store, _FlowAdapter(flow), worktrees=NoopWorktrees(), config=None)
        uc = ResolveCiUseCase(store, github, _FlowAdapter(flow), complete, close_item=CloseItemUseCase(store, NoopWorktrees()), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())
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

    def test_a_cancelled_check_parks_with_the_run_url_and_is_not_a_ci_failure(self):
        run_url = "https://github.com/x/y/actions/runs/9/job/3"
        gh = FakeGitHub(head_shas={_URL: "sha1"}, check_runs_by_sha={
            (_URL, "sha1"): (
                CheckRun(name="build", status="completed", conclusion="cancelled", url=run_url),
            )
        })
        store, item, step, uc = self._setup(gh)

        result = uc.execute()

        node = store.get_node(step)
        self.assertEqual((node.state, node.role), (State.WAITING, "human"))
        self.assertIn(run_url, node.park.reason)
        self.assertIn("build", node.park.reason)
        self.assertIn("Rerun the cancelled job", node.park.needs)
        self.assertIsNone(node.outcome)
        self.assertEqual(result.ci_resolved, [])
        self.assertFalse([c for c in store.children(item) if c.stage == "watch-ci"])
        self.assertEqual([a for a in store.item_artifacts(step) if a.type == "ci-judged-sha"], [])

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
        step = store.create_step(stage="poll-ci", role="engine", item=item)
        flow = _FlowAdapter(_FLOW)
        clock = _Clock()
        uc = ResolveCiUseCase(
            store, github, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None),
            close_item=CloseItemUseCase(store, NoopWorktrees()), clock=clock, poll_seconds=lambda: 60,
            ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())
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

    def test_a_completed_check_with_no_conclusion_is_held_pending_and_noted_once(self):
        odd = (CheckRun(name="build", status="completed", conclusion=None),)
        github = _ScriptedGitHub("sha1", odd)
        store, _, step, uc, clock = self._setup(github)

        self._run(uc, clock, 0.0)
        self._run(uc, clock, 10.0)

        node = store.get_node(step)
        self.assertEqual((node.notes or "").count("completed with no conclusion"), 1)
        self.assertNotEqual(node.state, State.DONE)

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
        stuck = store.create_step(stage="poll-ci", role="engine", item=stuck_item)
        ok_item = store.create_item("fine", "a description")
        plant_pr(store, ok_item, _URL, branch=_BRANCH)
        fine = store.create_step(stage="poll-ci", role="engine", item=ok_item)

        class _Split(_ScriptedGitHub):
            def head_sha(self, pr):
                return NotYetRead() if pr.endswith("/9") else "sha1"

        split = _Split("sha1", _GREEN)
        uc = ResolveCiUseCase(
            store, split, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None),
            close_item=CloseItemUseCase(store, NoopWorktrees()), clock=clock, poll_seconds=lambda: 60,
            ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())
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
    step = store.create_step(stage="poll-ci", role="engine", item=item)
    flow = _FlowAdapter(_FLOW)
    uc = ResolveCiUseCase(
        store, github, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None),
        close_item=CloseItemUseCase(store, NoopWorktrees()), clock=time.monotonic, poll_seconds=lambda: 60,
        ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset(),
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

    def test_the_timeout_note_reports_awake_elapsed(self):
        gh = _gh([_hung("build", 1000.0, url="http://x/1")], required={"build"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute(((1500.0, 5000.0),))

        node = store.get_node(step)
        self.assertEqual(node.outcome, "failed")
        self.assertIn("5500s", node.report)
        self.assertNotIn("9000s", node.report)

    def test_a_sleep_keeps_a_wall_clock_overdue_check_waiting(self):
        gh = _gh([_hung("build", 1000.0)], required={"build"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute(((1000.0, 9000.0),))

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

    def test_timeout_note_names_the_queued_check_by_its_own_workflow(self):
        done = CheckRun(name="test (3.13)", status="completed", conclusion="success", workflow="scanner-python")
        hung = CheckRun(name="test (3.13)", status="queued", conclusion=None, started_at=6399.0, workflow="scanner-kotlin")
        store, item, step, uc = _ci_setup(_gh([done, hung]))

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.outcome, "failed")
        self.assertIn("check 'scanner-kotlin / test (3.13)'", node.report)
        self.assertNotIn("scanner-python", node.report)

    def test_failure_note_names_the_failing_check_by_workflow(self):
        bad = CheckRun(name="test", status="completed", conclusion="failure", workflow="sensors")
        store, item, step, uc = _ci_setup(_gh([bad]))

        uc.execute()

        self.assertIn("check 'sensors / test'", store.get_node(step).report)

    def test_a_failed_check_beside_a_queued_one_fails_naming_the_failed_check(self):
        bad = CheckRun(name="lint", status="completed", conclusion="failure", workflow="ruff")
        queued = CheckRun(name="test", status="queued", conclusion=None, started_at=9999.0, workflow="macos")
        store, item, step, uc = _ci_setup(_gh([queued, bad]))

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.outcome, "failed")
        self.assertIn("check 'ruff / lint'", node.report)
        self.assertNotIn("macos", node.report)

    def test_cancelled_park_names_the_check_by_workflow(self):
        cancelled = CheckRun(name="test", status="completed", conclusion="cancelled", workflow="sensors")
        store, item, step, uc = _ci_setup(_gh([cancelled]))

        uc.execute()

        self.assertIn("sensors / test", store.get_node(step).park.reason)

    def test_completed_with_no_conclusion_condition_names_the_check_by_workflow(self):
        odd = CheckRun(name="test", status="completed", conclusion=None, workflow="sensors")
        store, item, step, uc = _ci_setup(_gh([odd]))

        uc.execute()

        self.assertIn("check 'sensors / test'", store.get_node(step).notes or "")

    def test_required_set_with_one_absent_keeps_waiting(self):
        gh = _gh([_ok("a")], required={"a", "b"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).state, State.QUEUED)

    def test_required_set_all_reported_green_succeeds(self):
        gh = _gh([_ok("a"), _ok("b")], required={"a", "b"})
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "succeeded")

    def test_required_check_absent_past_the_ceiling_times_out_naming_it(self):
        gh = _gh([_ok("b")], required={"a", "b"})
        store, item, step, uc = _ci_setup(gh)
        clock = [10000.0]
        uc._wall_clock = lambda: clock[0]

        uc.execute()
        self.assertEqual(store.get_node(step).state, State.QUEUED)
        clock[0] = 13600.0
        uc.execute()
        self.assertEqual(store.get_node(step).state, State.QUEUED)
        clock[0] = 13601.0
        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.outcome, "failed")
        self.assertIn("required check 'a' never appeared", node.report)
        self.assertIn("ceiling of 3600s", node.report)

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
                FakeStore(), FakeGitHub(), None, None, close_item=None, clock=time.monotonic, poll_seconds=lambda: 60,
                ci_ceiling_seconds=_missing, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 0.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset(),
            )


class _ConfirmsOnly:
    def __init__(self, confirmed):
        self._confirmed = confirmed

    def poll_epoch(self):
        return 0

    def confirmed_after(self, pr, epoch):
        return pr in self._confirmed

    def hold_prs(self, prs):
        return None


class TestViewConfirmationHold(unittest.TestCase):
    def _uc(self, store, github, views, clock, note_polls=3):
        flow = _FlowAdapter(_FLOW)
        return ResolveCiUseCase(
            store, github, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None), close_item=CloseItemUseCase(store, NoopWorktrees()), clock=clock,
            poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: note_polls,
            wall_clock=lambda: 10000.0, views=views, trusted_authors=lambda: frozenset())

    def test_an_unconfirmed_view_holds_the_step_and_judges_nothing(self):
        store, item, step, _ = _ci_setup(_gh([_ok("build")]))
        uc = self._uc(store, _gh([_ok("build")]), NeverConfirmed(), time.monotonic)

        response = uc.execute()

        self.assertEqual(response.ci_resolved, [])
        self.assertEqual(store.get_node(step).state, State.QUEUED)
        self.assertEqual([a for a in store.item_artifacts(step) if a.type == "ci-judged-sha"], [])

    def test_a_confirmed_view_is_judged_as_before(self):
        store, item, step, _ = _ci_setup(_gh([_ok("build")]))
        uc = self._uc(store, _gh([_ok("build")]), AlwaysConfirmed(), time.monotonic)

        uc.execute()

        self.assertEqual(store.get_node(step).state, State.DONE)

    def test_a_step_unconfirmed_past_the_interval_logs_view_not_confirmed_once(self):
        clock = _Clock()
        store, item, step, _ = _ci_setup(_gh([_ok("build")]))
        uc = self._uc(store, _gh([_ok("build")]), NeverConfirmed(), clock)

        clock.now = 0.0
        first = uc.execute()
        clock.now = 61.0
        second = uc.execute()
        clock.now = 70.0
        third = uc.execute()

        self.assertEqual(first.ci_unread, [])
        self.assertEqual([(u.step, u.reason) for u in second.ci_unread], [(step, "view-not-confirmed")])
        self.assertEqual(third.ci_unread, [])
        self.assertEqual(store.get_node(step).state, State.QUEUED)

    def test_only_the_step_on_the_confirmed_pr_completes(self):
        other = "https://github.com/acme/widget/pull/9"
        store = FakeStore()
        item_a = store.create_item("a", "d")
        item_b = store.create_item("b", "d")
        plant_pr(store, item_a, _URL, branch=_BRANCH)
        plant_pr(store, item_b, other, branch="feat/other")
        step_a = store.create_step(stage="poll-ci", role="engine", item=item_a)
        step_b = store.create_step(stage="poll-ci", role="engine", item=item_b)
        github = FakeGitHub(
            head_shas={_URL: "sha1", other: "sha1"},
            check_runs_by_sha={(_URL, "sha1"): (_ok("build"),), (other, "sha1"): (_ok("build"),)})
        clock = _Clock()
        uc = self._uc(store, github, _ConfirmsOnly({_URL}), clock)

        clock.now = 0.0
        uc.execute()
        clock.now = 61.0
        response = uc.execute()

        self.assertEqual(store.get_node(step_a).state, State.DONE)
        self.assertEqual(store.get_node(step_b).state, State.QUEUED)
        self.assertEqual([(u.step, u.reason) for u in response.ci_unread], [(step_b, "view-not-confirmed")])


class _RecordingConfirmsOnly(_ConfirmsOnly):
    def __init__(self, confirmed):
        super().__init__(confirmed)
        self.held = []

    def hold_prs(self, prs):
        self.held.append(set(prs))


def _condition_notes(store, step):
    return [line for line in (store.get_node(step).notes or "").splitlines() if "ci-unconfirmed-note-polls" in line]


class TestUnconfirmedNote(unittest.TestCase):
    def _run(self, note_polls, times):
        clock = _Clock()
        store, item, step, _ = _ci_setup(_gh([_ok("build")]))
        uc = TestViewConfirmationHold()._uc(store, _gh([_ok("build")]), NeverConfirmed(), clock, note_polls)
        counts = []
        for t in times:
            clock.now = t
            uc.execute()
            counts.append(len(_condition_notes(store, step)))
        return store, step, counts

    def test_a_note_appears_past_three_poll_intervals_and_repeats_every_three(self):
        store, step, counts = self._run(3, [0.0, 179.0, 181.0, 200.0, 361.0, 362.0])

        self.assertEqual([0, 0, 1, 1, 1, 1], counts)
        self.assertIn("no poll has confirmed it for more than 3 poll intervals", store.get_node(step).notes)
        self.assertIn("x2", store.get_node(step).notes)

    def test_the_bound_is_read_from_the_callable(self):
        _, _, counts = self._run(1, [0.0, 59.0, 61.0])

        self.assertEqual([0, 0, 1], counts)

    def test_only_the_unconfirmed_step_is_noted_and_both_prs_are_held(self):
        other = "https://github.com/acme/widget/pull/9"
        store = FakeStore()
        item_a = store.create_item("a", "d")
        item_b = store.create_item("b", "d")
        plant_pr(store, item_a, _URL, branch=_BRANCH)
        plant_pr(store, item_b, other, branch="feat/other")
        step_a = store.create_step(stage="poll-ci", role="engine", item=item_a)
        step_b = store.create_step(stage="poll-ci", role="engine", item=item_b)
        github = FakeGitHub(
            head_shas={_URL: "sha1", other: "sha1"},
            check_runs_by_sha={(_URL, "sha1"): (_ok("build"),), (other, "sha1"): (_ok("build"),)})
        views = _RecordingConfirmsOnly({_URL})
        clock = _Clock()
        uc = TestViewConfirmationHold()._uc(store, github, views, clock)

        for t in (0.0, 181.0):
            clock.now = t
            uc.execute()

        self.assertEqual(_condition_notes(store, step_a), [])
        self.assertEqual(len(_condition_notes(store, step_b)), 1)
        self.assertEqual(views.held, [{_URL, other}, {other}])


class _Log:
    def append_run_log(self, text):
        pass


class TestHeldPrResolvesWithinOnePoll(unittest.TestCase):
    def test_a_step_whose_pr_no_reader_touches_resolves_after_one_poll(self):
        from lightcycle.application.pool.pr_poll import PrPoll
        from lightcycle.application.pool.pr_writes import PrWrites

        other = "https://github.com/acme/widget/pull/9"
        store = FakeStore()
        item_a = store.create_item("a", "d")
        item_b = store.create_item("b", "d")
        plant_pr(store, item_a, other, branch="feat/other")
        plant_pr(store, item_b, _URL, branch=_BRANCH)
        store.create_step(stage="poll-ci", role="engine", item=item_a)
        step_b = store.create_step(stage="poll-ci", role="engine", item=item_b)
        github = FakeGitHub(
            updated_ats={_URL: 1.0, other: 1.0},
            head_shas={_URL: "sha1", other: "sha1"},
            check_runs_by_sha={(_URL, "sha1"): (_ok("build"),), (other, "sha1"): (_ok("build"),)})
        snapshot = PrSnapshot(github)
        poll = PrPoll(github, snapshot, PrWrites(time.monotonic), _Log())
        uc = TestViewConfirmationHold()._uc(store, snapshot, snapshot, time.monotonic)

        for now in (0.0, 60.0, 120.0):
            uc.execute()
            poll.run(snapshot.take_wanted(), now, 10)
        uc.execute()

        self.assertEqual(store.get_node(step_b).state, State.DONE)


class _ClosesStepOnCheckRead(FakeGitHub):
    def __init__(self, close, **kw):
        super().__init__(**kw)
        self._close = close

    def check_runs(self, pr, sha):
        self._close()
        return super().check_runs(pr, sha)


class TestResolveCiSkipsAStepAnotherPathClosed(unittest.TestCase):
    def test_a_step_closed_during_the_checks_read_is_not_closed_again(self):
        store = FakeStore()
        item = store.create_item("building a thing", "a description")
        plant_pr(store, item, _URL, branch=_BRANCH)
        step = store.create_step(stage="poll-ci", role="engine", item=item)
        flow = _FlowAdapter(_FLOW)
        complete = CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None)
        real = complete.execute
        calls = []
        closes = []

        def close_elsewhere():
            if not closes:
                closes.append(real(CompleteInput(step=step, outcome="succeeded")))

        gh = _ClosesStepOnCheckRead(
            close_elsewhere, head_shas={_URL: "sha1"},
            check_runs_by_sha={(_URL, "sha1"): (
                CheckRun(name="build", status="completed", conclusion="success"),)})
        complete.execute = lambda i: calls.append(i) or real(i)
        uc = ResolveCiUseCase(
            store, gh, flow, complete, close_item=CloseItemUseCase(store, NoopWorktrees()), clock=time.monotonic, poll_seconds=lambda: 60,
            ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600,
            ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3,
            wall_clock=lambda: 10000.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())

        result = uc.execute()

        self.assertEqual(calls, [])
        self.assertEqual(result.ci_resolved, [])
        successors = [c for c in store.children(item) if c.previous_step == step]
        self.assertEqual(len(successors), 1)


def _check(name, conclusion, status="completed"):
    return CheckRun(name=name, status=status, conclusion=conclusion, url="https://x/%s" % name)


class _StackedCiRig:
    def __init__(self, count=3, checks=None, required=None, views=None, state_by_layer=None,
                 flow=None, close_item=None):
        from tests.support.stacked import (
            STACK_URL, base_keys_for, build_stack, head_shas_for,
        )

        self.layers = build_stack(count, states=state_by_layer)
        self.store = FakeStore()
        item = self.store.create_item("stacked", "a description")
        self.item = item
        rid = plant_pr(self.store, item, self.layers[-1].url, branch=_BRANCH)
        self.store.set_stack(rid, STACK_URL)
        self.step = self.store.create_step(stage="poll-ci", role="engine", item=item)
        runs = {}
        for layer in self.layers:
            runs[(layer.url, layer.head_sha)] = tuple((checks or {}).get(layer.number, ()))
        bottom = next((l for l in self.layers if l.state == "open"), self.layers[0])
        self.github = FakeGitHub(
            stacks={STACK_URL: self.layers}, head_shas=head_shas_for(self.layers),
            base_keys=base_keys_for(self.layers), check_runs_by_sha=runs,
            required_by_base={"acme/widget@%s" % bottom.base_ref: required} if required else None)
        flow = _FlowAdapter(flow or _FLOW)
        self.uc = ResolveCiUseCase(
            self.store, self.github, flow, CompleteStepUseCase(self.store, flow, worktrees=NoopWorktrees(), config=None),
            close_item=close_item or CloseItemUseCase(self.store, NoopWorktrees()), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600,
            ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60,
            ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0,
            views=views or AlwaysConfirmed(), trusted_authors=lambda: frozenset())

    def node(self):
        return self.store.get_node(self.step)

    def artifacts(self, atype):
        return [a.value for a in self.store.item_artifacts(self.step) if a.type == atype]


def _wf(name, workflow="ci", conclusion="success"):
    return CheckRun(
        name=name, status="completed", conclusion=conclusion, url="https://x/%s" % name,
        workflow=workflow)


class TestResolveCiNotRunLayers(unittest.TestCase):
    def _rig(self, checks, required=None):
        rig = _StackedCiRig(checks=checks, required=required)
        rig.clock = [10000.0]
        rig.uc._wall_clock = lambda: rig.clock[0]
        rig.uc._ci_ceiling_seconds = lambda: 10 ** 9
        return rig

    def test_every_layer_running_the_same_checks_has_no_clause_and_no_artifact(self):
        rig = self._rig({n: [_wf("build"), _wf("lint", "lint")] for n in (1, 2, 3)})

        rig.uc.execute()
        rig.clock[0] += 601
        rig.uc.execute()

        node = rig.node()
        self.assertEqual(node.outcome, "succeeded")
        self.assertNotIn("not run", node.report)
        self.assertEqual(rig.artifacts("ci-not-run"), [])

    def test_a_layer_lacking_the_build_is_held_inside_the_window_then_reported_not_run(self):
        checks = {1: [_wf("build"), _wf("lint", "lint")], 2: [_wf("lint", "lint")],
                  3: [_wf("build"), _wf("lint", "lint")]}
        rig = self._rig(checks)

        rig.uc.execute()
        self.assertNotEqual(rig.node().state, State.DONE)
        rig.clock[0] += 601
        rig.uc.execute()

        node = rig.node()
        self.assertEqual(node.outcome, "succeeded")
        self.assertIn("CI not run on layer 2 of 3 (https://github.com/acme/widget/pull/2): ci / build.", node.report)
        self.assertEqual(
            rig.artifacts("ci-not-run"), ["layer 2 of 3 https://github.com/acme/widget/pull/2: ci / build"])

    def test_exactly_at_the_window_the_layer_is_pending_and_one_second_past_it_is_not_run(self):
        checks = {1: [_wf("build")], 2: [_wf("lint", "lint")], 3: [_wf("build")]}
        rig = self._rig(checks)

        rig.uc.execute()
        rig.clock[0] += 600
        rig.uc.execute()
        self.assertNotEqual(rig.node().state, State.DONE)
        rig.clock[0] += 1
        rig.uc.execute()

        self.assertEqual(rig.node().outcome, "succeeded")
        self.assertIn("layer 2 of 3", rig.node().report)

    def test_each_affected_layer_is_named_with_exactly_its_own_labels(self):
        checks = {
            1: [_wf("build"), _wf("test"), _wf("lint", "lint")],
            2: [_wf("build"), _wf("lint", "lint")],
            3: [_wf("lint", "lint")],
        }
        rig = self._rig(checks)

        rig.uc.execute()
        rig.clock[0] += 601
        rig.uc.execute()

        self.assertEqual(rig.artifacts("ci-not-run"), [
            "layer 2 of 3 https://github.com/acme/widget/pull/2: ci / test\n"
            "layer 3 of 3 https://github.com/acme/widget/pull/3: ci / build, ci / test"])
        self.assertIn("(https://github.com/acme/widget/pull/2): ci / test.", rig.node().report)
        self.assertIn("(https://github.com/acme/widget/pull/3): ci / build, ci / test.", rig.node().report)

    def test_a_ran_everything_layer_is_not_named(self):
        checks = {1: [_wf("build")], 2: [_wf("build")], 3: [_wf("lint", "lint")]}
        rig = self._rig(checks)

        rig.uc.execute()
        rig.clock[0] += 601
        rig.uc.execute()

        self.assertEqual(
            rig.artifacts("ci-not-run"), ["layer 3 of 3 https://github.com/acme/widget/pull/3: ci / build"])

    def test_a_layer_lacking_a_bottom_required_check_is_held_then_reported_not_run_as_required(self):
        checks = {1: [_wf("build")], 2: [_wf("lint", "lint")], 3: [_wf("build")]}
        rig = self._rig(checks, required={"build"})

        rig.uc.execute()
        self.assertNotEqual(rig.node().state, State.DONE)
        rig.clock[0] += 600
        rig.uc.execute()
        self.assertNotEqual(rig.node().state, State.DONE)
        rig.clock[0] += 1
        rig.uc.execute()

        self.assertEqual(rig.node().outcome, "succeeded")
        self.assertEqual(
            rig.artifacts("ci-not-run"),
            ["layer 2 of 3 https://github.com/acme/widget/pull/2: ci / build (required by the base branch)"])
        self.assertIn(
            "CI not run on layer 2 of 3 (https://github.com/acme/widget/pull/2): "
            "ci / build (required by the base branch).", rig.node().report)

    def test_a_two_layer_stack_lacking_a_trunk_required_check_lists_layer_two(self):
        otk = _wf("Build - OTK V2", workflow="")
        rig = _StackedCiRig(
            count=2,
            checks={1: [_wf("build"), _wf("lint", "lint"), otk], 2: [_wf("build"), _wf("lint", "lint")]},
            required={"build", "Build - OTK V2"})
        rig.clock = [10000.0]
        rig.uc._wall_clock = lambda: rig.clock[0]
        rig.uc._ci_ceiling_seconds = lambda: 10 ** 9

        rig.uc.execute()
        rig.clock[0] += 601
        rig.uc.execute()

        self.assertEqual(rig.node().outcome, "succeeded")
        self.assertEqual(
            rig.artifacts("ci-not-run"),
            ["layer 2 of 2 https://github.com/acme/widget/pull/2: Build - OTK V2 (required by the base branch)"])
        self.assertIn("CI not run on layer 2 of 2", rig.node().report)

    def test_a_failing_layer_routes_failed_with_no_not_run_clause(self):
        checks = {1: [_wf("build"), _wf("lint", "lint")],
                  2: [_wf("lint", "lint", conclusion="failure")], 3: [_wf("lint", "lint")]}
        rig = self._rig(checks)

        rig.uc.execute()
        rig.clock[0] += 601
        rig.uc.execute()

        self.assertEqual(rig.node().outcome, "failed")
        self.assertNotIn("not run", rig.node().report)
        self.assertEqual(rig.artifacts("ci-not-run"), [])

    def test_a_layer_with_no_checks_is_reported_with_every_expected_label(self):
        checks = {1: [_wf("build")], 2: [_wf("build")], 3: []}
        rig = self._rig(checks)

        rig.uc.execute()
        rig.clock[0] += 601
        rig.uc.execute()

        self.assertEqual(rig.node().outcome, "succeeded")
        self.assertEqual(
            rig.artifacts("ci-not-run"), ["layer 3 of 3 https://github.com/acme/widget/pull/3: ci / build"])

    def test_the_bottom_layer_is_never_judged_against_the_expected_set(self):
        rig = self._rig({1: [_wf("build")], 2: [_wf("build")], 3: [_wf("build")]})

        rig.uc.execute()
        rig.clock[0] += 601
        rig.uc.execute()

        self.assertEqual(rig.artifacts("ci-not-run"), [])


class TestResolveCiOverAStack(unittest.TestCase):
    def test_every_layer_green_completes_success_listing_each_layer(self):
        rig = _StackedCiRig(checks={n: [_check("build", "success")] for n in (1, 2, 3)})

        result = rig.uc.execute()

        self.assertEqual(result.ci_resolved, [rig.item])
        node = rig.node()
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "succeeded")
        for n in (1, 2, 3):
            self.assertIn("layer %d of 3" % n, node.report)
            self.assertIn("sha-%d" % n, node.report)
        self.assertEqual(rig.artifacts("ci-judged-sha"), ["sha-3"])
        import json
        self.assertEqual(len(json.loads(rig.artifacts("ci-judged-layers")[0])), 3)

    def test_a_trunk_required_check_only_on_layer_one_never_fails_or_times_out_the_upper_layers(self):
        rig = _StackedCiRig(
            checks={
                1: [_check("build", "success"), _check("codacy", "success")],
                2: [_check("build", "success")],
                3: [_check("build", "success")],
            },
            required={"codacy"})
        rig.clock = [10000.0]
        rig.uc._wall_clock = lambda: rig.clock[0]

        rig.uc.execute()
        self.assertNotEqual(rig.node().state, State.DONE)
        self.assertIsNone(rig.node().outcome)
        rig.clock[0] += 601
        rig.uc.execute()

        node = rig.node()
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "succeeded")
        self.assertEqual(len(rig.artifacts("ci-not-run")[0].splitlines()), 2)

    def test_an_upper_layer_whose_base_requires_a_check_still_waits_for_it(self):
        rig = _StackedCiRig(checks={n: [_check("build", "success")] for n in (1, 2, 3)})
        rig.github._required_by_base["acme/widget@layer-1"] = {"lint"}

        rig.uc.execute()

        self.assertNotEqual(rig.node().state, State.DONE)
        self.assertIsNone(rig.node().outcome)

    def test_a_red_layer_two_with_layer_one_pending_fails_naming_layer_two(self):
        rig = _StackedCiRig(checks={
            1: [_check("build", None, status="in_progress")],
            2: [_check("build", "failure")],
            3: [_check("build", "success")],
        })

        rig.uc.execute()

        node = rig.node()
        self.assertEqual(node.outcome, "failed")
        self.assertIn("layer 2 of 3 (PR https://github.com/acme/widget/pull/2)", node.report)
        self.assertTrue(node.report.startswith("CI failed on sha-2: check 'build'"))

    def test_a_red_layer_one_names_layer_one(self):
        rig = _StackedCiRig(checks={
            1: [_check("build", "failure")],
            2: [_check("build", "failure")],
            3: [_check("build", "success")],
        })

        rig.uc.execute()

        self.assertIn("layer 1 of 3", rig.node().report)

    def test_a_timed_out_layer_fails_the_stack_naming_the_layer(self):
        rig = _StackedCiRig(checks={
            1: [_check("build", "success")],
            2: [_check("build", None, status="in_progress")],
            3: [_check("build", "success")],
        })
        rig.uc._ci_ceiling_seconds = lambda: 1
        rig.uc._wall_clock = iter([1000.0, 1000.0, 1000.0, 9000.0, 9000.0, 9000.0]).__next__

        rig.uc.execute()
        rig.uc.execute()

        self.assertEqual(rig.node().outcome, "failed")
        self.assertIn("CI timed out on sha-2", rig.node().report)
        self.assertIn("layer 2 of 3", rig.node().report)

    def test_one_unread_layer_continues_without_an_outcome(self):
        rig = _StackedCiRig(checks={n: [_check("build", "success")] for n in (1, 2, 3)})
        rig.github._failing_calls = set()
        original = rig.github.check_runs

        def reading(pr, sha):
            if pr.endswith("/2"):
                return NotYetRead()
            return original(pr, sha)

        rig.github.check_runs = reading

        result = rig.uc.execute()

        self.assertEqual(result.ci_resolved, [])
        self.assertNotEqual(rig.node().state, State.DONE)

    def test_a_mixed_green_unread_and_pending_stack_has_no_outcome_and_counts_the_unread(self):
        rig = _StackedCiRig(checks={
            1: [_check("build", "success")],
            3: [_check("build", None, status="in_progress")],
        })
        original = rig.github.check_runs

        def reading(pr, sha):
            if pr.endswith("/2"):
                return NotYetRead()
            return original(pr, sha)

        rig.github.check_runs = reading
        clock = iter([0.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0]).__next__
        rig.uc._clock = clock

        first = rig.uc.execute()
        second = rig.uc.execute()

        self.assertEqual(first.ci_resolved + second.ci_resolved, [])
        self.assertNotEqual(rig.node().state, State.DONE)
        reasons = [u.reason for u in first.ci_unread + second.ci_unread]
        self.assertEqual(reasons, ["checks-not-yet-read"])

    def test_required_checks_are_read_once_per_open_layer_from_its_own_base(self):
        rig = _StackedCiRig(
            required=["build"], checks={n: [_check("build", "success")] for n in (1, 2, 3)})

        rig.uc.execute()

        required_calls = [c for c in rig.github.calls if c[0] == "required_checks"]
        self.assertEqual(required_calls, [
            ("required_checks", "acme/widget@main"),
            ("required_checks", "acme/widget@layer-1"),
            ("required_checks", "acme/widget@layer-2"),
        ])

    def test_a_merged_lower_layer_is_not_judged(self):
        rig = _StackedCiRig(
            state_by_layer={1: "merged"}, required=["build"],
            checks={2: [_check("build", "success")], 3: [_check("build", "success")]})

        rig.uc.execute()

        judged = [c for c in rig.github.calls if c[0] == "check_runs"]
        self.assertTrue(all(not c[1].endswith("/1") for c in judged))
        self.assertEqual(rig.node().outcome, "succeeded")

    def test_the_skip_idle_check_does_not_run_for_a_stacked_run(self):
        rig = _StackedCiRig(checks={n: [_check("build", "success")] for n in (1, 2, 3)})
        called = []
        rig.uc._skip_idle.execute = lambda *a, **k: called.append(a)

        rig.uc.execute()

        self.assertEqual(called, [])

    def test_an_unread_stack_has_no_outcome(self):
        rig = _StackedCiRig(checks={n: [_check("build", "failure")] for n in (1, 2, 3)})
        rig.github._failing_calls = {"stack_view"}

        rig.uc.execute()

        self.assertNotEqual(rig.node().state, State.DONE)

    def test_a_stack_with_a_closed_layer_has_no_outcome(self):
        rig = _StackedCiRig(
            state_by_layer={2: "closed"}, checks={n: [_check("build", "failure")] for n in (1, 3)})

        rig.uc.execute()

        self.assertNotEqual(rig.node().state, State.DONE)


def _wff(name, workflow, workflow_file, conclusion="success"):
    return CheckRun(
        name=name, status="completed", conclusion=conclusion, url="https://x/%s" % name,
        workflow=workflow, workflow_file=workflow_file)


def _paths_workflow(file, paths=None, ignore=None, branches=None):
    lines = ["on:", "  pull_request:"]
    if branches:
        lines.append("    branches: [%s]" % ", ".join(branches))
    if paths:
        lines.append("    paths: [%s]" % ", ".join("'%s'" % x for x in paths))
    if ignore:
        lines.append("    paths-ignore: [%s]" % ", ".join("'%s'" % x for x in ignore))
    lines += ["jobs:", "  j:", "    runs-on: x", "    steps: []"]
    return WorkflowFile(file, "\n".join(lines) + "\n")


class TestResolveCiPathFilteredLayers(unittest.TestCase):
    def _rig(self, workflows, files, bottom=None, layer2=None, layer3=None, required=None):
        bottom = bottom if bottom is not None else [_wff("build", "app", "app.yml"), _wff("lint", "lint", "lint.yml")]
        layer2 = layer2 if layer2 is not None else [_wff("lint", "lint", "lint.yml")]
        rig = _StackedCiRig(checks={1: bottom, 2: layer2, 3: layer3 if layer3 is not None else bottom}, required=required)
        rig.clock = [10000.0]
        rig.uc._wall_clock = lambda: rig.clock[0]
        rig.uc._ci_ceiling_seconds = lambda: 10 ** 9
        for layer in rig.layers:
            key = (layer.url, layer.head_sha)
            rig.github._workflows_by_sha[key] = tuple(workflows)
            rig.github._files_by_sha[key] = frozenset(files.get(layer.number, ()))
        return rig

    def _run(self, rig):
        rig.uc.execute()
        rig.clock[0] += 601
        rig.uc.execute()
        return rig.node()

    def _flat(self, files):
        return {1: files, 2: files, 3: files}

    def test_a_layer_whose_diff_misses_the_paths_filter_is_not_reported_unrun(self):
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {2: {"sensors/a"}})

        node = self._run(rig)

        self.assertEqual(node.outcome, "succeeded")
        self.assertNotIn("not run", node.report)
        self.assertEqual(rig.artifacts("ci-not-run"), [])

    def test_a_layer_not_owing_a_check_is_not_held_for_the_window(self):
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {2: {"sensors/a"}})

        rig.uc.execute()

        self.assertEqual(rig.node().outcome, "succeeded")

    def test_a_layer_whose_diff_hits_the_filter_and_lacks_the_check_is_still_reported(self):
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {2: {"app/main.rs"}})

        node = self._run(rig)

        self.assertEqual(rig.artifacts("ci-not-run"), ["layer 2 of 3 https://github.com/acme/widget/pull/2: app / build"])
        self.assertIn("layer 2 of 3", node.report)

    def test_a_single_matching_path_is_enough_to_expect_the_workflow(self):
        rig = self._rig([_paths_workflow("app.yml", paths=["sensors/**"])], {2: {"sensors/a"}})

        self._run(rig)

        self.assertEqual(len(rig.artifacts("ci-not-run")), 1)

    def test_paths_ignore_matching_every_file_drops_the_expectation(self):
        rig = self._rig([_paths_workflow("app.yml", ignore=["docs/**"])], {2: {"docs/a"}})

        self._run(rig)

        self.assertEqual(rig.artifacts("ci-not-run"), [])

    def test_paths_ignore_matching_only_some_files_keeps_the_expectation(self):
        rig = self._rig([_paths_workflow("app.yml", ignore=["docs/**"])], {2: {"docs/a", "src/b"}})

        self._run(rig)

        self.assertEqual(len(rig.artifacts("ci-not-run")), 1)

    def test_a_mixed_layer_lists_only_the_check_its_diff_triggers(self):
        bottom = [_wff("build", "app", "app.yml"), _wff("test", "svc", "svc.yml"), _wff("lint", "lint", "lint.yml")]
        rig = self._rig(
            [_paths_workflow("app.yml", paths=["app/**"]), _paths_workflow("svc.yml", paths=["svc/**"])],
            {2: {"svc/a"}}, bottom=bottom)

        self._run(rig)

        self.assertEqual(rig.artifacts("ci-not-run"), ["layer 2 of 3 https://github.com/acme/widget/pull/2: svc / test"])

    def test_a_mixed_required_and_path_filtered_layer_lists_only_what_it_owes(self):
        bottom = [
            _wff("build", "ci", "ci.yml"), _wff("compile", "app", "app.yml"), _wff("lint", "lint", "lint.yml")]
        lint = [_wff("lint", "lint", "lint.yml")]
        rig = self._rig(
            [_paths_workflow("app.yml", paths=["app/**"]), _paths_workflow("ci.yml")],
            {2: {"sensors/a"}, 3: {"app/main.rs"}}, bottom=bottom, layer2=lint, layer3=lint,
            required={"build"})

        self._run(rig)

        self.assertEqual(rig.artifacts("ci-not-run"), [
            "layer 2 of 3 https://github.com/acme/widget/pull/2: ci / build (required by the base branch)\n"
            "layer 3 of 3 https://github.com/acme/widget/pull/3: "
            "app / compile, ci / build (required by the base branch)"])

    def test_a_required_label_bypasses_the_trigger_filter(self):
        bottom = [_wff("build", "ci", "other.yml"), _wff("lint", "lint", "lint.yml")]
        rig = self._rig(
            [_paths_workflow("lint.yml")], {2: {"sensors/a"}}, bottom=bottom,
            layer2=[_wff("lint", "lint", "lint.yml")], required={"build"})
        self._run(rig)

        self.assertEqual(rig.artifacts("ci-not-run"), [
            "layer 2 of 3 https://github.com/acme/widget/pull/2: ci / build (required by the base branch)"])
        self.assertEqual([c for c in rig.github.calls if c[0] in ("workflow_sources", "changed_files")], [])

    def test_a_check_with_no_workflow_file_is_always_expected(self):
        rig = self._rig(
            [_paths_workflow("app.yml", paths=["app/**"])], {2: {"sensors/a"}},
            bottom=[_wff("build", "app", ""), _wff("lint", "lint", "lint.yml")])

        self._run(rig)

        self.assertEqual(len(rig.artifacts("ci-not-run")), 1)

    def test_a_branches_filter_is_evaluated_against_the_bottom_base(self):
        rig = self._rig([_paths_workflow("app.yml", branches=["main"])], {2: {"sensors/a"}})

        self._run(rig)

        self.assertEqual(len(rig.artifacts("ci-not-run")), 1)

    def test_an_unparseable_workflow_stays_expected(self):
        rig = self._rig([WorkflowFile("app.yml", "on: [unclosed\n  - : :")], {2: {"sensors/a"}})

        self._run(rig)

        self.assertEqual(len(rig.artifacts("ci-not-run")), 1)

    def test_a_diff_of_300_files_stays_expected(self):
        files = {"sensors/f%d" % i for i in range(300)}
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {2: files})

        self._run(rig)

        self.assertEqual(len(rig.artifacts("ci-not-run")), 1)

    def test_a_workflow_sources_read_failure_leaves_the_step_unresolved(self):
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {2: {"sensors/a"}})
        rig.github._failing_calls = {"workflow_sources"}

        time_now = [0.0]
        rig.uc._clock = lambda: time_now[0]

        rig.uc.execute()
        time_now[0] += 1000
        response = rig.uc.execute()

        self.assertNotEqual(rig.node().state, State.DONE)
        self.assertIn("workflow-sources-read-failed", [u.reason for u in response.ci_unread])

    def test_a_changed_files_read_failure_leaves_the_step_unresolved(self):
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {2: {"sensors/a"}})
        rig.github._failing_calls = {"changed_files"}
        time_now = [0.0]
        rig.uc._clock = lambda: time_now[0]

        rig.uc.execute()
        time_now[0] += 1000
        response = rig.uc.execute()

        self.assertNotEqual(rig.node().state, State.DONE)
        self.assertIn("changed-files-read-failed", [u.reason for u in response.ci_unread])

    def test_the_expectation_is_read_once_per_layer_sha(self):
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {2: {"sensors/a"}}, layer3=[CheckRun(name="slow", status="in_progress", conclusion=None, workflow="lint", workflow_file="lint.yml")])
        rig.uc._ci_start_window_seconds = lambda: None

        rig.uc.execute()
        rig.uc.execute()

        layer2 = rig.layers[1]
        reads = [c for c in rig.github.calls if c == ("workflow_sources", layer2.url, layer2.head_sha)]
        self.assertEqual(len(reads), 1)

    def test_a_new_layer_sha_reads_the_expectation_again(self):
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {2: {"sensors/a"}}, layer3=[CheckRun(name="slow", status="in_progress", conclusion=None, workflow="lint", workflow_file="lint.yml")])
        layer2 = rig.layers[1]
        rig.uc._ci_start_window_seconds = lambda: None
        rig.uc.execute()
        key = "%s@%s" % (rig.step, layer2.url)
        sha, base, expectation = rig.uc._stack_expected[key]
        rig.uc._stack_expected[key] = ("old-sha", base, expectation)

        rig.uc.execute()

        reads = [c for c in rig.github.calls if c == ("workflow_sources", layer2.url, layer2.head_sha)]
        self.assertEqual(len(reads), 2)

    def test_a_layer_reporting_every_bottom_check_makes_no_expectation_reads(self):
        both = [_wff("build", "app", "app.yml"), _wff("lint", "lint", "lint.yml")]
        rig = self._rig([_paths_workflow("app.yml", paths=["app/**"])], {}, layer2=both)

        self._run(rig)

        self.assertEqual([c for c in rig.github.calls if c[0] == "workflow_sources"], [])


class TestResolveCiHeadLagsBranch(unittest.TestCase):
    OLD = "1e0f3f52"
    NEW = "df95de90"

    def _rig(self, window=lambda: 600, github=None):
        store = FakeStore()
        item = store.create_item("lagging", "a description")
        plant_pr(store, item, _URL, branch=_BRANCH)
        step = store.create_step(stage="poll-ci", role="engine", item=item)
        github = github or FakeGitHub(
            lagging_prs={_URL}, head_shas={_URL: self.OLD}, branch_shas={_URL: self.NEW},
            check_runs_by_sha={
                (_URL, self.OLD): (CheckRun(name="build", status="completed", conclusion="failure"),),
                (_URL, self.NEW): (),
            })
        flow = _FlowAdapter(_FLOW)
        clock = _Clock()
        uc = ResolveCiUseCase(
            store, github, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None),
            close_item=CloseItemUseCase(store, NoopWorktrees()), clock=clock, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600,
            ci_start_window_seconds=window, ci_no_workflows_wait_seconds=lambda: 60,
            ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0,
            views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())
        return store, step, github, clock, uc

    def _judged(self, store, step):
        return [a.value for a in store.item_artifacts(step) if a.type == "ci-judged-sha"]

    def test_rec_480_sequence_waits_then_judges_the_new_commit(self):
        store, step, github, clock, uc = self._rig()
        self.assertTrue(any(
            c.conclusion == "failure" for c in github.check_runs(_URL, self.OLD)))

        first = uc.execute()

        self.assertEqual(first.ci_resolved, [])
        self.assertNotEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(self._judged(store, step), [])
        self.assertEqual([n for n in store.all_nodes() if n.type == "step" and n.stage == "watch-ci"], [])

        github._check_runs_by_sha[(_URL, self.NEW)] = (
            CheckRun(name="build", status="completed", conclusion="success"),)
        github.end_lag(_URL, self.NEW)
        second = uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "succeeded")
        self.assertIn(self.NEW, node.report)
        self.assertEqual(second.ci_resolved, [node.item])

    def test_the_lag_is_noted_once_on_the_step(self):
        store, step, _, _, uc = self._rig()

        uc.execute()
        uc.execute()

        notes = store.get_node(step).notes or ""
        self.assertEqual(notes.count("holding CI"), 1)
        self.assertIn(self.OLD, notes)
        self.assertIn(self.NEW, notes)

    def test_a_lag_past_the_window_parks_once_naming_both_shas(self):
        store, step, _, clock, uc = self._rig()

        uc.execute()
        clock.now = 601
        uc.execute()

        node = store.get_node(step)
        self.assertEqual((node.state, node.role), (State.WAITING, "human"))
        self.assertIn(self.OLD, node.park.reason)
        self.assertIn(self.NEW, node.park.reason)
        reason = node.park.reason
        clock.now = 2000
        uc.execute()
        self.assertEqual(store.get_node(step).park.reason, reason)

    def test_a_disabled_window_waits_without_parking(self):
        store, step, _, clock, uc = self._rig(window=lambda: None)

        uc.execute()
        clock.now = 100000
        uc.execute()

        node = store.get_node(step)
        self.assertNotEqual(node.state, State.WAITING)
        self.assertEqual(node.role, "engine")

    def test_an_unreadable_lag_leaves_the_step_unclosed_and_reports_it(self):
        gh = FakeGitHub(
            head_shas={_URL: self.OLD}, failing_calls={"head_lags_branch"},
            check_runs_by_sha={(_URL, self.OLD): (
                CheckRun(name="build", status="completed", conclusion="failure"),)})
        store, step, _, clock, uc = self._rig(github=gh)

        uc.execute()
        clock.now = 61
        result = uc.execute()

        self.assertNotEqual(store.get_node(step).state, State.DONE)
        self.assertEqual([u.reason for u in result.ci_unread], ["head-lag-read-failed"])


class TestResolveCiStackLagHolds(unittest.TestCase):
    def test_only_the_upper_layer_lagging_closes_nothing_until_it_clears(self):
        rig = _StackedCiRig(count=2, checks={1: _GREEN, 2: _GREEN})
        top = rig.layers[-1]
        rig.github._lagging.add(top.url)

        first = rig.uc.execute()

        self.assertEqual(first.ci_resolved, [])
        self.assertNotEqual(rig.node().state, State.DONE)

        rig.github._lagging.discard(top.url)
        second = rig.uc.execute()

        self.assertEqual(second.ci_resolved, [rig.item])
        self.assertEqual(rig.node().state, State.DONE)


class _RulesFailingGitHub(FakeGitHub):
    def __init__(self, *args, failing_bases=(), **kw):
        super().__init__(*args, **kw)
        self.failing_bases = set(failing_bases)

    def required_checks(self, base_key):
        if base_key in self.failing_bases:
            return ReadFailure(1, "boom")
        return super().required_checks(base_key)


class _NotYetRulesGitHub(_ScriptedGitHub):
    def required_checks(self, base_key):
        return NotYetRead()


class _PublishedRulesFailureGitHub(_ScriptedGitHub):
    def __init__(self, *args, stderr, **kw):
        super().__init__(*args, **kw)
        self._snapshot = PrSnapshot(self)
        self._snapshot.publish_required_failure("acme/widget@main", ReadFailure(1, stderr))

    def required_checks(self, base_key):
        return self._snapshot.required_checks(base_key)


class TestResolveCiRulesRead(unittest.TestCase):
    def test_a_published_rules_failure_reports_its_stderr(self):
        stderr = "HTTP 403: Resource not accessible by personal access token"
        gh = _PublishedRulesFailureGitHub("sha1", _GREEN, stderr=stderr)
        store, item, step, uc, clock = TestCiUnreadDiagnostics()._setup(gh)

        self.assertEqual(TestCiUnreadDiagnostics._run(None, uc, clock, 0.0), [])
        self.assertEqual(
            TestCiUnreadDiagnostics._run(None, uc, clock, 61.0), [(step, "rules-read-failed", stderr)])
        self.assertNotEqual(store.get_node(step).state, State.DONE)

    def test_a_rules_read_that_fails_once_holds_then_judges_against_required(self):
        gh = _gh([_ok("build"), _hung("codacy", 1000.0)], required={"build"}, failing={"required_checks"})
        store, item, step, uc = _ci_setup(gh)

        first = uc.execute()

        self.assertNotEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(first.ci_resolved, [])

        gh._failing_calls = set()
        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "succeeded")

    def test_a_rules_read_that_keeps_failing_reports_one_ci_unread_line(self):
        gh = _gh([_ok("build")], required={"build"}, failing={"required_checks"})
        store, item, step, uc, clock = TestCiUnreadDiagnostics()._setup(gh)

        self.assertEqual(TestCiUnreadDiagnostics._run(None, uc, clock, 0.0), [])
        self.assertEqual(
            TestCiUnreadDiagnostics._run(None, uc, clock, 61.0), [(step, "rules-read-failed", "boom")])
        self.assertEqual(TestCiUnreadDiagnostics._run(None, uc, clock, 70.0), [])
        self.assertNotEqual(store.get_node(step).state, State.DONE)

    def test_a_snapshot_without_rules_reports_rules_not_yet_read(self):
        gh = _NotYetRulesGitHub("sha1", _GREEN)
        store, item, step, uc, clock = TestCiUnreadDiagnostics()._setup(gh)

        TestCiUnreadDiagnostics._run(None, uc, clock, 0.0)

        self.assertEqual(
            TestCiUnreadDiagnostics._run(None, uc, clock, 61.0),
            [(step, "rules-not-yet-read", "no snapshot yet")])
        self.assertNotEqual(store.get_node(step).state, State.DONE)

    def test_an_unreadable_sync_state_holds_the_pr_instead_of_judging_all_checks(self):
        gh = _gh([_ok("build"), _hung("codacy", 1000.0)], required={"build"}, failing={"pr_sync_state"})
        store, item, step, uc, clock = TestCiUnreadDiagnostics()._setup(gh)

        TestCiUnreadDiagnostics._run(None, uc, clock, 0.0)

        self.assertEqual(
            TestCiUnreadDiagnostics._run(None, uc, clock, 61.0),
            [(step, "sync-read-failed", "boom")])
        self.assertNotEqual(store.get_node(step).state, State.DONE)

    def test_only_the_step_whose_base_rules_fail_is_reported_and_the_other_resolves(self):
        store = FakeStore()
        flow = _FlowAdapter(_FLOW)
        stuck_url = "https://github.com/acme/widget/pull/9"
        stuck_item = store.create_item("stuck", "a description")
        plant_pr(store, stuck_item, stuck_url, branch="feat/stuck")
        stuck = store.create_step(stage="poll-ci", role="engine", item=stuck_item)
        ok_item = store.create_item("fine", "a description")
        plant_pr(store, ok_item, _URL, branch=_BRANCH)
        fine = store.create_step(stage="poll-ci", role="engine", item=ok_item)
        gh = _RulesFailingGitHub(
            head_shas={_URL: "sha1", stuck_url: "sha1"},
            check_runs_by_sha={(_URL, "sha1"): (_ok("build"),), (stuck_url, "sha1"): (_ok("build"),)},
            required_by_base={"acme/widget@main": {"build"}, "acme/widget@broken": {"build"}},
            failing_bases={"acme/widget@broken"},
        )
        gh._base_keys[stuck_url] = "acme/widget@broken"
        clock = _Clock()
        uc = ResolveCiUseCase(
            store, gh, flow, CompleteStepUseCase(store, flow, worktrees=NoopWorktrees(), config=None),
            close_item=CloseItemUseCase(store, NoopWorktrees()), clock=clock, poll_seconds=lambda: 60,
            ci_ceiling_seconds=lambda: 3600, ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60, ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())
        clock.now = 0.0
        first = uc.execute()
        clock.now = 61.0
        second = uc.execute()

        self.assertEqual(first.ci_resolved, [ok_item])
        self.assertEqual(store.get_node(fine).state, State.DONE)
        self.assertNotEqual(store.get_node(stuck).state, State.DONE)
        self.assertEqual([u.step for u in second.ci_unread], [stuck])
        self.assertEqual([u.reason for u in second.ci_unread], ["rules-read-failed"])

    def test_a_base_with_no_rules_still_resolves(self):
        gh = _gh([_ok("build")])
        store, item, step, uc = _ci_setup(gh)

        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "succeeded")

    def _stack_rig(self, failing_layer):
        rig = _StackedCiRig(
            checks={n: [_wf("build")] for n in (1, 2, 3)}, required={"build"})
        rig.github.__class__ = _RulesFailingGitHub
        rig.github.failing_bases = {"acme/widget@%s" % rig.layers[failing_layer - 1].base_ref}
        rig.clock = [10000.0]
        rig.uc._wall_clock = lambda: rig.clock[0]
        rig.uc._ci_ceiling_seconds = lambda: 10 ** 9
        return rig

    def test_a_stack_layer_whose_rules_read_fails_holds_the_step(self):
        for layer in (1, 2):
            rig = self._stack_rig(layer)

            rig.uc.execute()
            rig.clock[0] += 601
            rig.uc.execute()

            self.assertNotEqual(rig.node().state, State.DONE)
            self.assertEqual(rig.artifacts("ci-not-run"), [])

            rig.github.failing_bases = set()
            rig.uc.execute()
            rig.clock[0] += 601
            rig.uc.execute()

            self.assertEqual(rig.node().outcome, "succeeded")


_MERGE_FLOW = flow_from_metas(
    {
        "poller": {
            "engine": True, "step": "poll-ci", "routes": {"succeeded": "watch-ci"},
            "on_ci_success": "succeeded", "on_ci_failure": "succeeded",
        },
        "watcher": {"model": "sonnet", "step": "watch-ci"},
        "gate": {"step": "ready-merge", "routes": {"merged": "watch-ci"}, "on_pr_merge": "merged"},
    },
    disposition={"merged": "completed"},
)

_REPO = "/elsewhere/app"


def _merge_rig(states):
    from tests.support.fake_git import FakeGit
    from tests.support.null_collaborators import NoFlow
    from tests.unit.test_close_item_teardown_guard import _Cfg
    from lightcycle.application.services.worktree import WorktreeService

    branches = {(_REPO, b) for b in (_BRANCH, "layer-1", "layer-2", "layer-3")}
    git = FakeGit(
        branches=branches, ref="origin/main",
        beyond={key: ["a1"] for key in branches},
    )
    holder = {}

    class _Late:
        def execute(self, input):
            return holder["close"].execute(input)

    rig = _StackedCiRig(state_by_layer=states, flow=_MERGE_FLOW, close_item=_Late())
    rig.store.add_artifact(rig.item, "repo", _REPO)
    rig.git = git
    svc = WorktreeService(rig.store, git, fs=None, config=_Cfg(), flow=NoFlow())
    holder["close"] = CloseItemUseCase(rig.store, svc)
    return rig


class TestResolveCiStackWithNoOpenLayer(unittest.TestCase):
    def test_a_stack_with_every_layer_merged_closes_the_item_as_merged(self):
        rig = _merge_rig({1: "merged", 2: "merged", 3: "merged"})

        rig.uc.execute()

        node = rig.store.get_node(rig.item)
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "merged")
        self.assertEqual(rig.node().state, State.DONE)
        deleted = sorted(c[2] for c in rig.git.calls if c[0] == "delete_branch")
        self.assertEqual(deleted, sorted([_BRANCH, "layer-1", "layer-2", "layer-3"]))
        self.assertEqual(rig.store.open_runs_of(rig.item), [])

    def test_a_stack_with_no_open_layer_and_one_closed_parks_naming_the_layer(self):
        rig = _merge_rig({1: "merged", 2: "closed", 3: "merged"})

        rig.uc.execute()

        park = rig.node().park
        self.assertIn("layer 2 of 3", park.reason)
        self.assertIn("https://github.com/acme/widget/pull/2", park.reason)
        self.assertNotEqual(rig.store.get_node(rig.item).state, State.DONE)

    def test_a_stack_with_a_merged_layer_and_an_open_one_does_not_close(self):
        rig = _merge_rig({1: "merged", 2: "merged", 3: "open"})

        rig.uc.execute()

        self.assertNotEqual(rig.store.get_node(rig.item).state, State.DONE)

    def test_an_unreadable_stack_closes_nothing_and_parks_nothing(self):
        rig = _merge_rig({1: "merged", 2: "merged", 3: "merged"})
        rig.github._failing_calls = {"stack_view"}

        rig.uc.execute()

        self.assertNotEqual(rig.store.get_node(rig.item).state, State.DONE)
        self.assertIsNone(rig.node().park.reason)

    def test_a_refused_teardown_parks_the_step_and_the_item_stays_open(self):
        rig = _merge_rig({1: "merged", 2: "merged", 3: "merged"})
        path = "%s/.worktrees/%s" % (_REPO, rig.item)
        rig.git._registered = {path}
        rig.git._uncommitted = {path: ["a.py"]}

        rig.uc.execute()

        self.assertNotEqual(rig.store.get_node(rig.item).state, State.DONE)
        self.assertIn("a.py", rig.node().park.reason)


def _stale_cancel(completed_at=5000.0, url="https://x/runs/1"):
    return CheckRun(
        name="build", status="completed", conclusion="cancelled", url=url, completed_at=completed_at)


def _unblock(store, step):
    from lightcycle.application.flow.route_step import RouteStepService

    RouteStepService(store).route(step, "engine")


class TestCancelledRerun(unittest.TestCase):
    def _rig(self, runs):
        gh = _gh(runs)
        store, item, step, uc = _ci_setup(gh)
        clock = [10000.0]
        uc._wall_clock = lambda: clock[0]
        return gh, store, step, uc, clock

    def test_an_unblocked_cancel_is_held_until_a_newer_result(self):
        gh, store, step, uc, clock = self._rig([_stale_cancel()])

        uc.execute()
        self.assertEqual(store.get_node(step).state, State.WAITING)
        _unblock(store, step)
        result = uc.execute()

        node = store.get_node(step)
        self.assertEqual((node.state, node.role), (State.QUEUED, "engine"))
        self.assertEqual(result.ci_resolved, [])
        gh._check_runs_by_sha[(_URL, "sha1")] = (_hung("build", 10100.0),)
        uc.execute()
        self.assertEqual(store.get_node(step).state, State.QUEUED)
        gh._check_runs_by_sha[(_URL, "sha1")] = (_ok("build"),)
        uc.execute()
        self.assertEqual(store.get_node(step).outcome, "succeeded")

    def test_a_new_cancel_after_a_rerun_parks_again(self):
        gh, store, step, uc, clock = self._rig([_stale_cancel()])

        uc.execute()
        _unblock(store, step)
        uc.execute()
        self.assertEqual(store.get_node(step).state, State.QUEUED)
        gh._check_runs_by_sha[(_URL, "sha1")] = (_stale_cancel(9000.0, "https://x/runs/2"),)
        uc.execute()

        self.assertEqual(store.get_node(step).state, State.WAITING)

    def test_the_hold_expires_at_the_ceiling(self):
        gh, store, step, uc, clock = self._rig([_stale_cancel()])

        uc.execute()
        _unblock(store, step)
        uc.execute()
        clock[0] += 3600
        uc.execute()
        self.assertEqual(store.get_node(step).state, State.QUEUED)
        clock[0] += 1
        uc.execute()

        self.assertEqual(store.get_node(step).state, State.WAITING)

    def test_a_stack_layer_cancel_is_held_after_an_unblock(self):
        rig = _StackedCiRig(count=2, checks={
            1: [_check("build", "success")], 2: [_stale_cancel()]})
        rig.clock = [10000.0]
        rig.uc._wall_clock = lambda: rig.clock[0]

        rig.uc.execute()
        self.assertEqual(rig.node().state, State.WAITING)
        _unblock(rig.store, rig.step)
        rig.uc.execute()
        self.assertEqual(rig.node().state, State.QUEUED)
        runs = rig.github._check_runs_by_sha
        key = next(k for k in runs if runs[k] and runs[k][0].conclusion == "cancelled")
        runs[key] = (_check("build", "success"),)
        rig.uc.execute()

        self.assertEqual(rig.node().outcome, "succeeded")

    def test_a_failure_beats_a_remembered_cancel(self):
        gh, store, step, uc, clock = self._rig([_stale_cancel()])

        uc.execute()
        _unblock(store, step)
        gh._check_runs_by_sha[(_URL, "sha1")] = (
            _stale_cancel(), CheckRun(name="test", status="completed", conclusion="failure"))
        uc.execute()

        self.assertEqual(store.get_node(step).outcome, "failed")

    def test_the_remembered_cancel_is_pruned(self):
        gh, store, step, uc, clock = self._rig([_stale_cancel()])

        uc.execute()
        self.assertIn(step, uc._cancel_parked)
        _unblock(store, step)
        gh._head_shas[_URL] = "sha2"
        gh._check_runs_by_sha[(_URL, "sha2")] = (_hung("build", 10100.0),)
        uc.execute()
        self.assertNotIn(step, uc._cancel_parked)

        gh._head_shas[_URL] = "sha1"
        gh._check_runs_by_sha[(_URL, "sha1")] = (_stale_cancel(),)
        uc.execute()
        self.assertEqual(store.get_node(step).state, State.WAITING)
        self.assertIn(step, uc._cancel_parked)
        store.update_state(step, State.DONE)
        uc.execute()
        self.assertNotIn(step, uc._cancel_parked)


_GATE_META = {
    "step": "code-await-merge",
    "routes": {"merged": "finish", "head-moved": "poll-ci"},
    "on_pr_merge": "merged",
    "on_pr_head_moved": "head-moved",
}

_GATE_FLOW = flow_from_metas({
    "poller": {
        "engine": True, "step": "poll-ci",
        "routes": {"succeeded": "code-await-merge", "failed": "watch-ci"},
        "on_ci_success": "succeeded", "on_ci_failure": "failed",
    },
    "watcher": {"model": "sonnet", "step": "watch-ci"},
    "gate": _GATE_META,
})

_GATE_FLOW_NO_HOOK = flow_from_metas({
    "poller": {
        "engine": True, "step": "poll-ci",
        "routes": {"succeeded": "code-await-merge", "failed": "watch-ci"},
        "on_ci_success": "succeeded", "on_ci_failure": "failed",
    },
    "watcher": {"model": "sonnet", "step": "watch-ci"},
    "gate": {
        "step": "code-await-merge", "routes": {"merged": "finish"}, "on_pr_merge": "merged",
    },
})


class _GateRig(_StackedCiRig):
    def __init__(self, count=2, merged=(), checks=None, required=None, flow=None, judged=None):
        super().__init__(
            count=count, checks=checks, required=required,
            state_by_layer={n: "merged" for n in merged}, flow=flow or _GATE_FLOW)
        import json

        open_layers = [l for l in self.layers if l.state == "open"]
        seeded = open_layers if judged is None else self.layers[: judged]
        if judged is not False:
            self.store.add_artifact(
                self.step, "ci-judged-layers",
                json.dumps({l.url: l.head_sha for l in seeded}, sort_keys=True), internal=True)
        self.store.complete_node(self.step, "succeeded")
        self.gate = self.store.create_step(stage="code-await-merge", role="human", item=self.item)
        self.clock = [0.0]
        self.uc._clock = lambda: self.clock[0]

    def gate_node(self):
        return self.store.get_node(self.gate)

    def gate_values(self, atype):
        return [a.value for a in self.store.item_artifacts(self.gate) if a.type == atype]

    def set_checks(self, number, runs):
        layer = next(l for l in self.layers if l.number == number)
        self.github._check_runs_by_sha[(layer.url, layer.head_sha)] = tuple(runs)

    def inbox_ids(self):
        from lightcycle.application.work import InboxInput, InboxUseCase

        flow = _FlowAdapter(_GATE_FLOW)
        rows = InboxUseCase(self.store, flow).execute(InboxInput()).rows
        return [r.step.id for r in rows]


class TestResolveCiStackGate(unittest.TestCase):
    def test_a_two_layer_stack_whose_bottom_layer_merges_waits_on_layer_two_and_reopens_when_its_required_checks_pass(self):
        rig = _GateRig(count=2, merged=(1,), checks={2: ()}, required={"build"}, judged=2)
        rig.github._required_by_base["acme/widget@main"] = {"build"}

        rig.uc.execute()

        self.assertEqual(len(rig.gate_values("layer-ci-wait")), 1)
        self.assertNotEqual(rig.gate_node().state, State.DONE)
        self.assertNotIn(rig.gate, rig.inbox_ids())

        rig.set_checks(2, [_check("build", "success")])
        rig.uc.execute()

        self.assertEqual(rig.gate_values("layer-ci-wait"), [])
        self.assertEqual(rig.gate_values("layer-ci-merged"), ["1"])
        self.assertIn(rig.gate, rig.inbox_ids())

    def test_layer_two_failing_after_the_retarget_completes_the_gate_with_head_moved(self):
        rig = _GateRig(count=2, merged=(1,), checks={2: [_check("build", "failure")]}, judged=2)

        rig.uc.execute()

        node = rig.gate_node()
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "head-moved")
        self.assertIn("layer 2 of 2", node.report)

    def test_layer_two_failing_with_no_head_moved_hook_parks_the_gate(self):
        rig = _GateRig(
            count=2, merged=(1,), checks={2: [_check("build", "failure")]}, judged=2,
            flow=_GATE_FLOW_NO_HOOK)

        rig.uc.execute()

        node = rig.gate_node()
        self.assertNotEqual(node.state, State.DONE)
        self.assertIn("layer 2 of 2", node.park.reason)
        self.assertIn(rig.gate, rig.inbox_ids())

    def test_a_layer_head_moved_with_an_unchanged_diff_waits_on_its_ci_and_reopens_when_it_passes(self):
        import json

        rig = _GateRig(count=2, checks={1: [_check("build", "success")], 2: [_check("build", None, status="in_progress")]})
        layer2 = rig.layers[1]
        rig.store.replace_artifact(
            rig.gate, "layer-ci-moved", json.dumps({layer2.url: layer2.head_sha}), internal=True)

        rig.uc.execute()

        self.assertEqual(len(rig.gate_values("layer-ci-wait")), 1)
        self.assertNotIn(rig.gate, rig.inbox_ids())

        rig.set_checks(2, [_check("build", "success")])
        rig.uc.execute()

        self.assertEqual(rig.gate_values("layer-ci-wait"), [])
        self.assertEqual(rig.gate_values("layer-ci-moved"), [])
        self.assertEqual(len(rig.gate_values("merge-next")), 1)
        self.assertIn(rig.gate, rig.inbox_ids())

    def test_a_moved_layer_failing_completes_the_gate_naming_its_moved_head(self):
        import json

        rig = _GateRig(count=2, checks={2: [_check("build", "failure")]})
        layer2 = rig.layers[1]
        rig.store.replace_artifact(
            rig.gate, "layer-ci-moved", json.dumps({layer2.url: layer2.head_sha}), internal=True)

        rig.uc.execute()

        node = rig.gate_node()
        self.assertEqual(node.outcome, "head-moved")
        self.assertIn("after its head moved", node.report)

    def test_a_layer_not_yet_retargeted_is_not_judged_and_is_parked_past_the_start_window(self):
        from tests.support.stacked import layer_url

        rig = _GateRig(count=2, merged=(1,), checks={2: [_check("build", "success")]}, judged=2)
        rig.github._base_keys[layer_url(2)] = "acme/widget@layer-1"

        rig.uc.execute()
        self.assertEqual(len(rig.gate_values("layer-ci-wait")), 1)
        self.assertNotIn(
            ("check_runs", layer_url(2), "sha-2"), rig.github.calls)

        rig.clock[0] = 600
        rig.uc.execute()
        self.assertIsNone(rig.gate_node().park.needs)

        rig.clock[0] = 601
        rig.uc.execute()
        self.assertIn("still based on layer-1", rig.gate_node().park.reason)
        self.assertIn(rig.gate, rig.inbox_ids())

    def test_the_layer_to_merge_next_is_named_before_any_merge_and_after_the_wait(self):
        rig = _GateRig(count=2, checks={1: [_check("build", "success")]})

        rig.uc.execute()
        first = rig.gate_values("merge-next")
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0], "layer 1 of 2 (https://github.com/acme/widget/pull/1)")

        merged = _GateRig(count=2, merged=(1,), checks={2: ()}, judged=2)
        merged.github._required_by_base["acme/widget@main"] = {"build"}
        merged.uc.execute()
        self.assertEqual(merged.gate_values("merge-next"), [])
        merged.set_checks(2, [_check("build", "success")])
        merged.uc.execute()
        after = merged.gate_values("merge-next")
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0], "layer 2 of 2 (https://github.com/acme/widget/pull/2)")

    def test_two_layers_merging_before_one_tick_make_one_wait_on_the_third_layer(self):
        rig = _GateRig(count=6, merged=(1, 2), checks={3: ()}, judged=6)
        rig.github._required_by_base["acme/widget@main"] = {"build"}

        rig.uc.execute()

        self.assertEqual(
            rig.gate_values("layer-ci-wait"),
            ["layer 3 of 6 (https://github.com/acme/widget/pull/3)"])

    def test_a_gate_with_no_open_layer_clears_the_wait_and_parks_nothing(self):
        rig = _GateRig(count=2, merged=(1, 2), judged=2)
        rig.store.replace_artifact(rig.gate, "layer-ci-wait", "layer 2 of 2 (x)", internal=True)

        rig.uc.execute()

        self.assertEqual(rig.gate_values("layer-ci-wait"), [])
        self.assertIsNone(rig.gate_node().park.needs)

    def test_merged_now_equal_to_the_recorded_baseline_does_not_wait(self):
        rig = _GateRig(count=2, merged=(1,), checks={2: ()}, judged=2)
        rig.store.replace_artifact(rig.gate, "layer-ci-merged", "1", internal=True)

        rig.uc.execute()

        self.assertEqual(rig.gate_values("layer-ci-wait"), [])
        self.assertEqual(len(rig.gate_values("merge-next")), 1)

    def test_a_gate_in_flight_with_no_record_and_a_merge_already_counted_in_the_judged_layers_does_not_wait(self):
        rig = _GateRig(count=3, merged=(1,), checks={2: ()}, judged=2)

        rig.uc.execute()

        self.assertEqual(rig.gate_values("layer-ci-wait"), [])

    def test_a_gate_with_neither_record_nor_judged_layers_records_the_merged_count_and_does_not_wait(self):
        rig = _GateRig(count=2, merged=(1,), checks={2: ()}, judged=False)

        rig.uc.execute()

        self.assertEqual(rig.gate_values("layer-ci-merged"), ["1"])
        self.assertEqual(rig.gate_values("layer-ci-wait"), [])

    def test_a_held_gate_neither_waits_nor_completes_and_records_the_would_be_action(self):
        from lightcycle.application.work.gate_hold import GateHold

        rig = _GateRig(count=2, merged=(1,), checks={2: [_check("build", "failure")]}, judged=2)
        GateHold(rig.store).place(rig.gate, "holding")

        rig.uc.execute()

        node = rig.gate_node()
        self.assertNotEqual(node.state, State.DONE)
        self.assertIsNone(node.park.needs)
        self.assertEqual(rig.gate_values("layer-ci-wait"), [])
        self.assertIn("held: layer CI failed on layer 2 of 2", node.notes)


class _AlternatingGitHub(FakeGitHub):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.reason_now = "required_checks"

    def required_checks(self, base_key):
        if self.reason_now == "required_checks":
            return ReadFailure(1, "boom")
        return super().required_checks(base_key)

    def pr_sync_state(self, pr):
        if self.reason_now == "pr_sync_state":
            return ReadFailure(1, "denied")
        return super().pr_sync_state(pr)


class TestUnreadPark(unittest.TestCase):
    def _poll(self, uc, clock, at):
        clock.now = at
        uc.execute()

    def _parked(self, store, step):
        return store.get_node(step).role != "engine"

    def test_a_rules_read_failing_past_the_ceiling_parks_the_step(self):
        gh = _gh([_ok("build")], required={"build"}, failing={"required_checks"})
        store, item, step, uc, clock = TestCiUnreadDiagnostics()._setup(gh)

        for at in (0.0, 61.0, 3600.0):
            self._poll(uc, clock, at)
            self.assertFalse(self._parked(store, step))
        self._poll(uc, clock, 3601.0)

        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        for text in ("rules-read-failed", _URL, "boom", "3601s"):
            self.assertIn(text, node.park.reason)
        self.assertIn("gh auth status", node.park.needs)

    def test_a_read_that_recovers_before_the_ceiling_never_parks(self):
        gh = _gh([_hung("build", 9990.0)], required={"build"}, failing={"required_checks"})
        store, item, step, uc, clock = TestCiUnreadDiagnostics()._setup(gh)

        self._poll(uc, clock, 0.0)
        self._poll(uc, clock, 3000.0)
        gh._failing_calls = set()
        self._poll(uc, clock, 3100.0)
        self.assertEqual(uc._unread_run, {})
        gh._failing_calls = {"required_checks"}
        self._poll(uc, clock, 3200.0)
        self._poll(uc, clock, 6000.0)

        self.assertFalse(self._parked(store, step))

    def test_alternating_reasons_do_not_park(self):
        gh = _AlternatingGitHub(
            head_shas={_URL: "sha1"}, check_runs_by_sha={(_URL, "sha1"): (_ok("build"),)},
            required_by_base={"acme/widget@main": {"build"}})
        store, item, step, uc, clock = TestCiUnreadDiagnostics()._setup(gh)

        for i, at in enumerate(range(0, 9000, 1000)):
            gh.reason_now = "required_checks" if i % 2 == 0 else "pr_sync_state"
            self._poll(uc, clock, float(at))
            self.assertFalse(self._parked(store, step))

        gh.reason_now = "required_checks"
        self._poll(uc, clock, 9000.0)
        self._poll(uc, clock, 11600.0)
        self.assertFalse(self._parked(store, step))
        self._poll(uc, clock, 11601.0)
        self.assertTrue(self._parked(store, step))

    def test_unblocking_restarts_the_unread_count(self):
        gh = _gh([_ok("build")], required={"build"}, failing={"required_checks"})
        store, item, step, uc, clock = TestCiUnreadDiagnostics()._setup(gh)

        self._poll(uc, clock, 0.0)
        self._poll(uc, clock, 3601.0)
        self.assertTrue(self._parked(store, step))
        _unblock(store, step)
        self._poll(uc, clock, 4000.0)
        self._poll(uc, clock, 7000.0)
        self.assertFalse(self._parked(store, step))
        self._poll(uc, clock, 7601.0)

        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("3601s", node.park.reason)

    def test_a_stack_layer_unread_parks_once(self):
        rig = _StackedCiRig(
            checks={n: [_wf("build")] for n in (1, 2, 3)}, required={"build"})
        rig.github.__class__ = _RulesFailingGitHub
        rig.github.failing_bases = {"acme/widget@%s" % rig.layers[1].base_ref}
        clock = _Clock()
        rig.uc._clock = clock
        rig.uc._wall_clock = lambda: 10000.0

        clock.now = 0.0
        rig.uc.execute()
        self.assertEqual(rig.node().role, "engine")
        rig.github._check_runs_by_sha[(rig.layers[0].url, rig.layers[0].head_sha)] = (
            _wf("build", conclusion="failure"),)
        clock.now = 3601.0
        rig.uc.execute()

        node = rig.node()
        self.assertEqual(node.role, "human")
        self.assertIn("https://github.com/acme/widget/pull/2", node.park.reason)
        self.assertNotEqual(node.outcome, "failed")
        self.assertNotEqual(node.state, State.DONE)
