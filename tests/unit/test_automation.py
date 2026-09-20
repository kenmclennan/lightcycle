import datetime
import unittest

from lightcycle.application.flow.engine_steps import (
    GOAL_STATE_OF_PLAY_STEP,
    RETRO_ORIGIN_LABEL,
    SUMMARY_ORIGIN_LABEL,
)
from lightcycle.application.work import DoneInput, DoneUseCase
from lightcycle.application.work.automation import (
    AUTOMATION_LABELS,
    AutomationInput,
    AutomationUseCase,
    automation_kind,
    is_automation_item,
)
from tests.support.fake_store import FakeStore

DAY = datetime.date(2026, 1, 1)


def _closed(store, id, label=None, step="build", closed_at="2026-01-01T10:00:00+00:00",
            disposition="completed", cost=None):
    item = store.create_item("item %s" % id, "d", id=id)
    child = store.create_step(step=step, role="agent", parent=item)
    if cost is not None:
        store.claim_ready("agent")
        store.record_usage(child, 100, 10, 0, 0, cost, "list", None)
    store.complete_node(child, "done")
    store.complete_node(item, "merged", disposition=disposition)
    store._records[item]["closed_at"] = closed_at
    if label:
        store.label_add(item, label)
    return item


class TestMembershipIsByLabel(unittest.TestCase):
    def test_the_label_set_is_the_two_origin_labels(self):
        self.assertEqual(AUTOMATION_LABELS, frozenset({SUMMARY_ORIGIN_LABEL, RETRO_ORIGIN_LABEL}))

    def test_an_unlabelled_aud_item_is_project_work(self):
        s = FakeStore()
        item = s.get_item(_closed(s, "AUD-1"))
        self.assertFalse(is_automation_item(s, item))
        self.assertIsNone(automation_kind(s, item))

    def test_a_labelled_lc_item_is_automation(self):
        s = FakeStore()
        item = s.get_item(_closed(s, "LC-1", label=RETRO_ORIGIN_LABEL, step="audit"))
        self.assertTrue(is_automation_item(s, item))
        self.assertEqual(automation_kind(s, item), "audit")

    def test_summary_kinds_are_told_apart_by_step_stage(self):
        s = FakeStore()
        daily = s.get_item(_closed(s, "SUM-1", label=SUMMARY_ORIGIN_LABEL, step="daily-summary"))
        sop = s.get_item(_closed(s, "SUM-2", label=SUMMARY_ORIGIN_LABEL, step=GOAL_STATE_OF_PLAY_STEP))
        self.assertEqual(automation_kind(s, daily), "daily-summary")
        self.assertEqual(automation_kind(s, sop), "state-of-play")


class TestDoneExcludesAutomation(unittest.TestCase):
    def test_execute_counts_and_day_counts_drop_automation_and_keep_project_items(self):
        s = FakeStore()
        _closed(s, "LC-1")
        _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit")
        _closed(s, "SUM-1", label=SUMMARY_ORIGIN_LABEL, step="daily-summary")

        uc = DoneUseCase(s)

        self.assertEqual([r.step.id for r in uc.execute(DoneInput()).rows], ["LC-1"])
        self.assertEqual(uc.counts().total, 1)
        self.assertEqual([(d.day, d.count) for d in uc.day_counts()], [(DAY, 1)])

    def test_two_items_of_the_same_id_shape_land_on_opposite_sides(self):
        s = FakeStore()
        _closed(s, "AUD-1")
        _closed(s, "AUD-2", label=RETRO_ORIGIN_LABEL, step="audit")

        rows = DoneUseCase(s).execute(DoneInput()).rows

        self.assertEqual([r.step.id for r in rows], ["AUD-1"])


class TestAutomationUseCase(unittest.TestCase):
    def test_tallies_are_always_three_in_order_with_absent_kind_at_zero(self):
        s = FakeStore()
        _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit", cost=1.0)
        _closed(s, "SUM-1", label=SUMMARY_ORIGIN_LABEL, step="daily-summary", cost=0.5)

        resp = AutomationUseCase(s).execute(AutomationInput())

        self.assertEqual([t.kind for t in resp.tallies], ["audit", "daily-summary", "state-of-play"])
        self.assertEqual([t.count for t in resp.tallies], [1, 1, 0])
        self.assertFalse(resp.tallies[2].spend.cost_usd)
        self.assertEqual(resp.total.count, 2)
        self.assertEqual(resp.total.spend.cost_usd.micros, 1_500_000)

    def test_day_filters_by_closed_date(self):
        s = FakeStore()
        _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit")
        _closed(s, "AUD-2", label=RETRO_ORIGIN_LABEL, step="audit", closed_at="2026-01-02T10:00:00+00:00")

        resp = AutomationUseCase(s).execute(AutomationInput(day=DAY))

        self.assertEqual([r.step.id for r in resp.rows], ["AUD-1"])

    def test_rows_are_newest_closed_first(self):
        s = FakeStore()
        _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit")
        _closed(s, "AUD-2", label=RETRO_ORIGIN_LABEL, step="audit", closed_at="2026-01-02T10:00:00+00:00")

        resp = AutomationUseCase(s).execute(AutomationInput())

        self.assertEqual([r.step.id for r in resp.rows], ["AUD-2", "AUD-1"])

    def test_an_in_flight_automation_item_is_excluded(self):
        s = FakeStore()
        item = s.create_item("running", "d", id="AUD-1")
        s.create_step(step="audit", role="agent", parent=item)
        s.label_add(item, RETRO_ORIGIN_LABEL)

        self.assertEqual(AutomationUseCase(s).execute(AutomationInput()).total.count, 0)

    def test_an_abandoned_automation_item_is_counted(self):
        s = FakeStore()
        _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit", disposition="abandoned")

        self.assertEqual(AutomationUseCase(s).execute(AutomationInput()).total.count, 1)
