import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool.dispatch_pr_feedback import DispatchPrFeedbackUseCase
from lightcycle.application.pool.pr_snapshot import PrEntry, PrSnapshot
from lightcycle.domain.work import parse_timestamp
from lightcycle.ports.github import PrView
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import (
    _CONFLICT_FLOW,
    _TRUST,
    _FlowAdapter,
    plant_pr,
)

_URL = "https://github.com/x/y/pull/60"


def _view(mergeable="CONFLICTING", merge_state_status="DIRTY"):
    return PrView(
        state="OPEN", head_sha="h1", base_ref="main", base_key="x/y@main",
        mergeable=mergeable, merge_state_status=merge_state_status, updated_at=1.0)


class _Rig:
    def __init__(self):
        self.store = FakeStore()
        self.item = self.store.create_item("conflicting feature", "a description")
        plant_pr(self.store, self.item, _URL)
        self.step = self.store.create_step(stage="watch-step", role="agent", item=self.item)
        self.opened = parse_timestamp(self.store.get_node(self.step).created_at).timestamp()
        self.snapshot = PrSnapshot(FakeGitHub())
        complete = CompleteStepUseCase(self.store, _FlowAdapter(_CONFLICT_FLOW), worktrees=None, config=None)
        self.dispatch = DispatchPrFeedbackUseCase(
            self.store, self.snapshot, _FlowAdapter(_CONFLICT_FLOW), complete, **_TRUST)

    def read(self, view, offset):
        self.snapshot.publish(
            _URL, PrEntry(state="OPEN", view=view, read_at=self.opened + offset))

    def tick(self):
        self.snapshot.head_sha(_URL)
        return self.dispatch.execute()

    def state(self):
        return self.store.get_node(self.step).state


class TestConflictReadingMustPostdateTheStep(unittest.TestCase):
    def setUp(self):
        self.rig = _Rig()

    def test_a_view_read_before_the_step_opened_does_not_fire(self):
        self.rig.read(_view(), -1.0)

        result = self.rig.tick()

        self.assertEqual(result.conflicted, [])
        self.assertNotEqual(self.rig.state(), "done")

    def test_a_view_read_after_the_step_opened_fires(self):
        self.rig.read(_view(), 1.0)

        result = self.rig.tick()

        self.assertEqual(result.conflicted, [self.rig.item])
        self.assertEqual(self.rig.store.get_node(self.rig.step).outcome, "conflicted")

    def test_a_view_read_exactly_when_the_step_opened_fires(self):
        self.rig.read(_view(), 0.0)

        result = self.rig.tick()

        self.assertEqual(result.conflicted, [self.rig.item])

    def test_an_unsettled_conflicting_view_does_not_fire(self):
        self.rig.read(_view(mergeable="UNKNOWN", merge_state_status="DIRTY"), 1.0)
        self.assertEqual(self.rig.tick().conflicted, [])

        self.rig.read(_view(mergeable="CONFLICTING", merge_state_status="UNKNOWN"), 1.0)
        self.assertEqual(self.rig.tick().conflicted, [])
        self.assertNotEqual(self.rig.state(), "done")

    def test_a_stale_view_is_held_and_a_fresh_one_on_the_next_tick_fires(self):
        self.rig.read(_view(), -5.0)
        self.assertEqual(self.rig.tick().conflicted, [])

        self.rig.read(_view(), 5.0)

        self.assertEqual(self.rig.tick().conflicted, [self.rig.item])


class TestReadingWithoutATimeStillCounts(unittest.TestCase):
    def test_a_fake_github_conflict_fires(self):
        store = FakeStore()
        item = store.create_item("conflicting feature", "a description")
        plant_pr(store, item, _URL)
        step = store.create_step(stage="watch-step", role="agent", item=item)
        complete = CompleteStepUseCase(store, _FlowAdapter(_CONFLICT_FLOW), worktrees=None, config=None)
        uc = DispatchPrFeedbackUseCase(
            store, FakeGitHub(conflicted_prs={_URL}), _FlowAdapter(_CONFLICT_FLOW), complete,
            **_TRUST)

        result = uc.execute()

        self.assertEqual(result.conflicted, [item])
        self.assertEqual(store.get_node(step).state, "done")
