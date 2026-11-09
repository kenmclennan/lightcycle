import json
import time
import unittest
from unittest.mock import MagicMock, patch
from tests.support.null_collaborators import NoopWorktrees

from lightcycle.adapters.github import GitHubEventsAdapter
from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.pr_snapshot import PrEntry, PrSnapshot
from lightcycle.application.pool.pr_writes import InlinePrWrites
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.application.pool.skip_idle_ci_watch import SkipIdleCiWatchUseCase
from lightcycle.application.pool.update_behind_prs import UpdateBehindPrsUseCase
from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun, NotYetRead
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.fake_view_freshness import AlwaysConfirmed
from tests.unit import test_dispatch_pr_feedback as dispatch_helpers
from tests.unit import test_resolve_ci as ci_helpers

_URL = "https://github.com/x/y/pull/7"
_API = "a" * 40
_GIT = "b" * 40
_PASSING = (CheckRun(name="build", status="completed", conclusion="success"),)


def _proc(stdout="", returncode=0):
    return MagicMock(returncode=returncode, stdout=stdout, stderr="")


def _divergent_snapshot(github):
    payload = json.dumps({
        "state": "OPEN", "headRefOid": _API, "baseRefName": "main",
        "mergeable": "MERGEABLE", "mergeStateStatus": "BEHIND",
        "updatedAt": "2026-01-01T00:00:00Z",
    })
    run = MagicMock(side_effect=[_proc(payload), _proc("%s\trefs/pull/7/head\n" % _GIT)])
    with patch("lightcycle.adapters.github.subprocess.run", run):
        view = GitHubEventsAdapter().pr_view(_URL)
    snapshot = PrSnapshot(github)
    snapshot.publish(_URL, PrEntry(state=view.state, view=view, updated_at=view.updated_at))
    return snapshot


class TestSnapshotNamesTheGitHead(unittest.TestCase):
    def test_head_is_the_git_head_and_the_sync_state_is_unsettled(self):
        snapshot = _divergent_snapshot(FakeGitHub(head_shas={_URL: _API}))

        sync = snapshot.pr_sync_state(_URL)

        self.assertEqual(snapshot.head_sha(_URL), _GIT)
        self.assertEqual(sync.head_sha, _GIT)
        self.assertFalse(sync.settled)
        self.assertFalse(sync.behind)


class TestContentPinActsOnTheGitHead(unittest.TestCase):
    _FLOW = flow_from_metas(
        {"reviewer": {
            "step": "ready-merge", "routes": {"merged": "cleanup"},
            "on_pr_merge": "merged", "on_pr_close": "abandoned"}},
        disposition={"merged": "completed", "abandoned": "abandoned"},
    )

    def _pin(self, store, item):
        return next(r.content_pin for r in store.runs_of(item) if r.content_pin is not None)

    def _run(self, store, item, snapshot):
        from tests.unit.test_check_content_pin import _FlowAdapter
        store.create_step(stage="build", role="agent", item=item)
        cc = CheckContentPinUseCase(
            store, snapshot, _FlowAdapter(self._FLOW), trusted_authors=lambda: frozenset())
        phase = self._FLOW.step_def(self._FLOW.merge_stages()[0]).phase
        cc.execute(store.get_node(item), _URL, phase)

    def test_first_sight_pins_the_git_head(self):
        from tests.unit.test_check_content_pin import plant_pr
        store = FakeStore()
        item = store.create_item("feature", "d")
        plant_pr(store, item, _URL)
        snapshot = _divergent_snapshot(FakeGitHub(head_shas={_URL: _API}))

        self._run(store, item, snapshot)

        self.assertEqual(self._pin(store, item), _GIT)

    def test_an_earlier_pin_on_the_api_head_is_seen_to_move_to_the_git_head(self):
        from tests.unit.test_check_content_pin import plant_pr
        store = FakeStore()
        item = store.create_item("feature", "d")
        rid = plant_pr(store, item, _URL)
        store.record_pr_pin(rid, _URL, _API)
        snapshot = _divergent_snapshot(FakeGitHub(head_shas={_URL: _API}))
        compared = []
        original = snapshot.changed_files
        snapshot.changed_files = lambda pr, sha, base=None: (compared.append(sha), original(pr, sha, base))[1]

        self._run(store, item, snapshot)

        self.assertIn(_GIT, compared)


class TestResolveCiJudgesTheGitHead(unittest.TestCase):
    def test_checks_are_read_for_the_git_head_and_stored_api_checks_form_no_verdict(self):
        github = FakeGitHub(
            head_shas={_URL: _API}, check_runs_by_sha={(_URL, _API): _PASSING}, push_time=100.0)
        snapshot = _divergent_snapshot(github)
        snapshot.publish_checks(_URL, _API, _PASSING)
        store = FakeStore()
        item = store.create_item("building a thing", "d")
        ci_helpers.plant_pr(store, item, _URL, branch="feat/x")
        poll = store.create_step(stage="poll-ci", role="engine", item=item)
        flow = flow_from_metas({
            "poller": {
                "engine": True, "step": "poll-ci",
                "routes": {"succeeded": "review", "failed": "review"},
                "on_ci_success": "succeeded", "on_ci_failure": "failed"},
            "reviewer": {"model": "sonnet", "step": "review"},
        })
        adapter = ci_helpers._FlowAdapter(flow)
        uc = ResolveCiUseCase(
            store, snapshot, adapter, CompleteStepUseCase(store, adapter, worktrees=NoopWorktrees(), config=None),
            clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600,
            ci_start_window_seconds=lambda: 600, ci_no_workflows_wait_seconds=lambda: 60,
            ci_unconfirmed_note_polls=lambda: 3, wall_clock=lambda: 10000.0,
            views=AlwaysConfirmed(), trusted_authors=lambda: frozenset())

        result = uc.execute()

        self.assertEqual(result.ci_resolved, [])
        self.assertNotEqual(store.get_node(poll).state, State.DONE)
        self.assertIsInstance(snapshot.check_runs(_URL, _GIT), NotYetRead)


class TestSkipIdleCiWatchOnTheGitHead(unittest.TestCase):
    def test_does_not_skip_when_ci_passed_on_the_api_head_and_git_names_a_newer_one(self):
        from tests.unit.test_skip_idle_ci_watch import _flow
        github = FakeGitHub(head_shas={_URL: _API}, push_time=100.0)
        snapshot = _divergent_snapshot(github)
        store = FakeStore()
        item = store.create_item("building a thing", "d")
        ci_helpers.plant_pr(store, item, _URL, branch="feat/x")
        poll = store.create_step(stage="poll-ci", role="engine", item=item)
        watch = store.create_step(stage="watch-ci", role="agent", item=item)
        flow = _flow()
        adapter = ci_helpers._FlowAdapter(flow)
        uc = SkipIdleCiWatchUseCase(
            store, snapshot, adapter, CompleteStepUseCase(store, adapter, worktrees=NoopWorktrees(), config=None),
            trusted_authors=lambda: frozenset())

        skipped = uc.execute(store.get_node(poll), watch, _URL, _API)

        self.assertFalse(skipped)
        self.assertEqual(store.get_node(watch).state, State.QUEUED)


class TestUpdateBehindWaitsForASettledGitHead(unittest.TestCase):
    def test_no_update_branch_while_the_head_differs_from_the_api(self):
        github = FakeGitHub(behind_prs={_URL}, head_shas={_URL: _API}, strict_bases={"x/y@main"})
        snapshot = _divergent_snapshot(github)
        store = FakeStore()
        item = store.create_item("feature", "d")
        dispatch_helpers.plant_pr(store, item, _URL)
        store.create_step(stage="watch-step", role="human", item=item)
        from tests.unit.test_update_behind_prs import _FLOW
        uc = UpdateBehindPrsUseCase(
            store, snapshot, dispatch_helpers._FlowAdapter(_FLOW),
            InlinePrWrites(snapshot, lambda: 1000.0))

        result = uc.execute()

        self.assertEqual(github.update_calls, [])
        self.assertEqual(result.updated, [])
