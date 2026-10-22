import unittest

from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.flow.route_step import RouteStepService
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun, WorkflowFile
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.fake_view_freshness import AlwaysConfirmed
from tests.unit.test_resolve_ci import _FlowAdapter, plant_pr

_URL = "https://github.com/x/y/pull/90"
_SHA = "sha1"
_BASE = "x/y@main"
_FLOW = flow_from_metas({
    "poller": {
        "engine": True,
        "step": "poll-ci",
        "routes": {"succeeded": "watch-ci", "failed": "watch-ci"},
        "on_ci_success": "succeeded",
        "on_ci_failure": "failed",
    },
    "watcher": {"model": "sonnet", "step": "watch-ci"},
})
_PR_CI = WorkflowFile("ci.yml", "name: ci\non:\n  push:\n  pull_request:\njobs: {}\n")
_PUSH_ONLY = WorkflowFile("release.yml", "name: r\non:\n  push:\n    branches: [main]\njobs: {}\n")
_BROKEN = WorkflowFile("odd.yml", "name: odd\non: {pull_request: {branches: [main]}}\njobs: {}\n")
_START = 10000.0


class _Wall:
    def __init__(self):
        self.now = _START

    def __call__(self):
        return self.now


def _green(name="build"):
    return (CheckRun(name=name, status="completed", conclusion="success"),)


class _Case(unittest.TestCase):
    def _setup(self, workflows=(), runs=0, files=("a.py",), checks=(), **kw):
        self.store = FakeStore()
        item = self.store.create_item("building a thing", "a description")
        plant_pr(self.store, item, _URL, branch="feat/thing")
        self.step = self.store.create_step(stage="poll-ci", role="engine", item=item)
        self.github = FakeGitHub(
            head_shas={_URL: _SHA}, base_keys={_URL: _BASE},
            files_by_sha={(_URL, _SHA): frozenset(files)},
            workflows_by_sha={(_URL, _SHA): tuple(workflows)},
            runs_by_sha={(_URL, _SHA): runs},
            check_runs_by_sha={(_URL, _SHA): checks}, **kw)
        flow = _FlowAdapter(_FLOW)
        self.wall = _Wall()
        self.uc = ResolveCiUseCase(
            self.store, self.github, flow, CompleteStepUseCase(self.store, flow),
            clock=lambda: self.wall.now, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600,
            ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60,
            wall_clock=self.wall, views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())

    def _at(self, elapsed):
        self.wall.now = _START + elapsed
        return self.uc.execute()

    def _node(self):
        return self.store.get_node(self.step)

    def _judged(self):
        return [a.value for a in self.store.item_artifacts(self.step) if a.type == "ci-judged-sha"]

    def _count(self, name):
        return len([c for c in self.github.calls if c[0] == name])


class TestStalledPark(_Case):
    def test_expected_workflow_with_no_run_parks_past_the_window(self):
        self._setup(workflows=(_PR_CI, _BROKEN))
        self._at(0)
        self._at(600)
        self.assertEqual(self._node().role, "engine")
        self._at(601)
        node = self._node()
        self.assertEqual((node.state, node.role), (State.WAITING, "human"))
        for text in (_SHA, "600s", "main", "ci.yml", "odd.yml", _URL):
            self.assertIn(text, node.park.reason)
        self.assertIn("Could not read or parse: odd.yml", node.park.reason)
        self.assertEqual(self._judged(), [])
        self.assertIsNone(node.outcome)

    def test_a_parked_step_is_skipped_on_the_next_execute(self):
        self._setup(workflows=(_PR_CI,))
        self._at(0)
        self._at(601)
        before = len(self.github.calls)
        self._at(700)
        self.assertEqual(len(self.github.calls), before)

    def test_within_the_window_the_step_is_left_alone(self):
        self._setup(workflows=(_PR_CI,))
        self._at(0)
        self._at(300)
        node = self._node()
        self.assertEqual(node.role, "engine")
        self.assertIsNone(node.park.reason)
        self.assertEqual(self._judged(), [])

    def test_unparseable_workflow_counts_as_should_run(self):
        self._setup(workflows=(_BROKEN,))
        self._at(0)
        self._at(601)
        node = self._node()
        self.assertEqual(node.role, "human")
        self.assertIn("Could not read or parse: odd.yml", node.park.reason)

    def test_after_an_unblock_the_window_restarts(self):
        self._setup(workflows=(_PR_CI,))
        self._at(0)
        self._at(601)
        self.store.update_metadata(self.step, {"reason": None, "needs": None, "tried": None})
        RouteStepService(self.store).route(self.step, "engine")
        self._at(5000)
        self.assertEqual(self._node().role, "engine")
        self._at(5600)
        self.assertEqual(self._node().role, "engine")
        self._at(5601)
        self.assertEqual(self._node().role, "human")


class TestNoCiPath(_Case):
    def _closed_with(self, note_part):
        node = self._node()
        self.assertEqual(node.state, State.DONE)
        self.assertIn(note_part, node.report)

    def test_push_only_workflows_succeed_after_the_quiet_wait_with_a_note(self):
        self._setup(workflows=(_PUSH_ONLY,))
        self._at(0)
        self._at(60)
        self.assertNotEqual(self._node().state, State.DONE)
        self._at(61)
        self._closed_with("no CI checks are defined for this repo; none appeared on %s." % _SHA)
        self.assertEqual(self._judged(), [_SHA])

    def test_no_workflow_directory_succeeds_after_the_quiet_wait(self):
        self._setup()
        self._at(0)
        self._at(61)
        self._closed_with("no CI checks are defined")

    def test_branch_filter_excluding_the_base_succeeds(self):
        wf = WorkflowFile("ci.yml", "on:\n  pull_request:\n    branches: [release]\n")
        self._setup(workflows=(wf,))
        self._at(0)
        self._at(61)
        self._closed_with("no CI checks are defined")

    def test_path_filter_excluding_every_changed_file_succeeds(self):
        wf = WorkflowFile("ci.yml", "on:\n  pull_request:\n    paths: ['src/**']\n")
        self._setup(workflows=(wf,), files=("docs/a.md",))
        self._at(0)
        self._at(61)
        self._closed_with("no CI checks are defined")


class TestListedRun(_Case):
    def test_a_listed_run_waits_without_parking_and_reads_nothing_more(self):
        self._setup(workflows=(_PR_CI,), runs=1)
        self._at(0)
        self._at(601)
        self._at(3000)
        self.assertEqual(self._node().role, "engine")
        self.assertEqual(self._count("workflow_sources"), 0)
        self.assertEqual(self._count("changed_files"), 0)

    def test_a_listed_run_with_no_check_past_the_ceiling_routes_failed(self):
        self._setup(runs=2)
        self._at(0)
        self._at(3601)
        node = self._node()
        self.assertEqual(node.outcome, "failed")
        self.assertIn("2 workflow run(s) listed for the head but no check run appeared", node.report)
        self.assertIn("ci-check-ceiling-seconds", node.report)


class TestMixedCase(_Case):
    def test_a_green_check_arriving_after_an_empty_head_succeeds_without_a_park(self):
        self._setup(workflows=(_PR_CI,))
        self._at(0)
        self._at(30)
        self.github._check_runs_by_sha[(_URL, _SHA)] = _green()
        self._at(40)
        node = self._node()
        self.assertEqual(node.state, State.DONE)
        self.assertEqual(node.outcome, "succeeded")
        self.assertIn("CI succeeded on %s." % _SHA, node.report)
        self.assertIsNone(node.park.reason)

    def test_a_failing_check_arriving_after_an_empty_head_routes_failed(self):
        self._setup(workflows=(_PR_CI,))
        self._at(0)
        self.github._check_runs_by_sha[(_URL, _SHA)] = (
            CheckRun(name="build", status="completed", conclusion="failure"),)
        self._at(10)
        self.assertEqual(self._node().outcome, "failed")


class TestReadsAndFailures(_Case):
    def test_classification_reads_happen_once_per_head(self):
        self._setup(workflows=(_PR_CI,))
        for elapsed in (0, 10, 20, 30):
            self._at(elapsed)
        self.assertEqual(self._count("workflow_sources"), 1)
        self.assertEqual(self._count("changed_files"), 1)
        self.assertEqual(self._count("workflow_runs"), 4)

    def test_a_read_failure_leaves_the_step_unclosed_unparked_and_reports_once(self):
        for call in ("workflow_runs", "workflow_sources", "changed_files"):
            self._setup(workflows=(_PR_CI,), failing_calls=(call,))
            self._at(0)
            reported = self._at(700).ci_unread
            node = self._node()
            self.assertEqual(node.role, "engine", call)
            self.assertIsNone(node.outcome, call)
            self.assertIsNone(node.park.reason, call)
            self.assertEqual(len(reported), 1, call)
            self.assertIn("read-failed", reported[0].reason)


class TestQueuedCheckCeiling(_Case):
    def _queued(self, status="queued"):
        return (CheckRun(name="build", status=status, conclusion=None),)

    def test_a_check_left_queued_past_the_ceiling_routes_failed_saying_queued(self):
        self._setup(checks=self._queued())
        self._at(0)
        self._at(3601)
        node = self._node()
        self.assertEqual(node.outcome, "failed")
        self.assertIn("check 'build'", node.report)
        self.assertIn("still queued", node.report)

    def test_an_in_progress_check_keeps_its_wording(self):
        self._setup(checks=(
            CheckRun(name="build", status="in_progress", conclusion=None, started_at=_START - 4000),))
        self._at(0)
        self.assertIn("still in progress", self._node().report)

    def test_a_queued_check_inside_the_ceiling_is_pending(self):
        self._setup(checks=self._queued())
        self._at(0)
        self._at(3600)
        self.assertEqual(self._node().role, "engine")
        self.assertIsNone(self._node().outcome)


if __name__ == "__main__":
    unittest.main()
