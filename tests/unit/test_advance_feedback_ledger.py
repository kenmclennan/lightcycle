import unittest

from lightcycle.application.flow.advance_feedback_ledger import AdvanceFeedbackLedgerUseCase
from tests.support.fake_fs import flow_from_metas
from tests.unit.test_dispatch_pr_feedback import _FEEDBACK_FLOW, _FlowAdapter, plant_pr
from tests.support.fake_store import FakeStore


class TestAdvanceFeedbackLedger(unittest.TestCase):
    def _setup(self, stored=None, flow=_FEEDBACK_FLOW, stage="ready-merge", with_run=True):
        store = FakeStore()
        item = store.create_item("feature", "a description")
        step = store.create_step(stage=stage, role="human", item=item)
        rid = None
        adapter = _FlowAdapter(flow)
        if with_run:
            rid = plant_pr(
                store, item, "https://github.com/x/y/pull/1",
                phase=flow.step_def(stage).phase)
            if stored is not None:
                store.set_comments_dispatched_through(rid, stored)
        return store, step, rid, adapter

    def _run(self, store, step, flow, now):
        AdvanceFeedbackLedgerUseCase(store, flow, lambda: now).execute(step)

    def _ledger(self, store, rid):
        return next(
            r for r in store._runs if r.id == rid).comments_dispatched_through

    def test_advances_from_none(self):
        store, step, rid, flow = self._setup()
        self._run(store, step, flow, 3000.0)
        self.assertEqual(self._ledger(store, rid), "3000.0")

    def test_advances_from_earlier_value(self):
        store, step, rid, flow = self._setup(stored="1500.0")
        self._run(store, step, flow, 3000.0)
        self.assertEqual(self._ledger(store, rid), "3000.0")

    def test_never_moves_backwards(self):
        store, step, rid, flow = self._setup(stored="5000.0")
        self._run(store, step, flow, 3000.0)
        self.assertEqual(self._ledger(store, rid), "5000.0")

    def test_equal_to_clock_is_unchanged(self):
        store, step, rid, flow = self._setup(stored="3000")
        self._run(store, step, flow, 3000.0)
        self.assertEqual(self._ledger(store, rid), "3000")

    def test_stage_without_pr_feedback_is_untouched(self):
        flow = flow_from_metas({"reviewer": {"step": "ready-merge", "routes": {"merged": "cleanup"}}})
        store, step, rid, adapter = self._setup(flow=flow)
        self._run(store, step, adapter, 3000.0)
        self.assertIsNone(self._ledger(store, rid))

    def test_no_run_is_a_noop(self):
        store, step, _, flow = self._setup(with_run=False)
        self._run(store, step, flow, 3000.0)
