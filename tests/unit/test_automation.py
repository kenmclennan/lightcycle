import datetime
import unittest

from lightcycle.application.flow.engine_steps import (
    HELD_COMMENT_ORIGIN_LABEL,
    RETRO_ORIGIN_LABEL,
    SCHEDULE_ORIGIN_LABEL,
    SUMMARY_ORIGIN_LABEL,
)
from lightcycle.application.work import (
    CATEGORY_ALL,
    CATEGORY_AUTOMATION,
    DoneInput,
    DoneUseCase,
)
from lightcycle.application.work.automation import (
    AUTOMATION_LABELS,
    AutomationInput,
    AutomationUseCase,
    is_automation_item,
)
from lightcycle.application.work.closed_count import closed_count
from tests.support.fake_store import FakeStore

DAY = datetime.date(2026, 1, 1)


def _closed(store, id, label=None, step="build", closed_at="2026-01-01T10:00:00+00:00",
            disposition="completed", cost=None):
    item = store.create_item("item %s" % id, "d", id=id)
    child = store.create_step(stage=step, role="agent", item=item)
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
    def test_the_label_set_is_the_four_origin_labels(self):
        self.assertEqual(
            AUTOMATION_LABELS,
            frozenset({
                SUMMARY_ORIGIN_LABEL, RETRO_ORIGIN_LABEL, HELD_COMMENT_ORIGIN_LABEL,
                SCHEDULE_ORIGIN_LABEL,
            }),
        )

    def test_a_scheduled_item_is_automation(self):
        s = FakeStore()
        item = s.get_item(_closed(s, "SCH-1", label=SCHEDULE_ORIGIN_LABEL, step="build"))
        self.assertTrue(is_automation_item(s, item))

    def test_the_same_workflow_filed_by_hand_is_project_work(self):
        s = FakeStore()
        item = s.get_item(_closed(s, "SCH-1", step="build"))
        self.assertFalse(is_automation_item(s, item))

    def test_a_scheduled_item_is_not_counted_as_a_close(self):
        s = FakeStore()
        _closed(s, "LC-1")
        _closed(s, "SCH-1", label=SCHEDULE_ORIGIN_LABEL)
        self.assertEqual(closed_count(s, DAY), 1)

    def test_an_unlabelled_aud_item_is_project_work(self):
        s = FakeStore()
        item = s.get_item(_closed(s, "AUD-1"))
        self.assertFalse(is_automation_item(s, item))

    def test_a_labelled_lc_item_is_automation(self):
        s = FakeStore()
        item = s.get_item(_closed(s, "LC-1", label=RETRO_ORIGIN_LABEL, step="audit"))
        self.assertTrue(is_automation_item(s, item))


def _mixed_store():
    s = FakeStore()
    _closed(s, "LC-1", closed_at="2026-01-01T09:00:00+00:00")
    _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit", closed_at="2026-01-01T11:00:00+00:00")
    _closed(s, "SUM-1", label=SUMMARY_ORIGIN_LABEL, step="daily-summary", closed_at="2026-01-02T10:00:00+00:00")
    return s


class TestDoneCategories(unittest.TestCase):
    def _ids(self, uc, **kwargs):
        return [r.step.id for r in uc.execute(DoneInput(**kwargs)).rows]

    def test_the_default_filter_returns_no_automation_items(self):
        self.assertEqual(self._ids(DoneUseCase(_mixed_store())), ["LC-1"])

    def test_all_returns_work_and_automation_newest_first(self):
        self.assertEqual(
            self._ids(DoneUseCase(_mixed_store()), category=CATEGORY_ALL), ["SUM-1", "AUD-1", "LC-1"]
        )

    def test_automation_returns_only_automation_items(self):
        self.assertEqual(
            self._ids(DoneUseCase(_mixed_store()), category=CATEGORY_AUTOMATION), ["SUM-1", "AUD-1"]
        )

    def test_counts_report_every_category_and_projects_exclude_automation(self):
        s = _mixed_store()
        counts = DoneUseCase(s).counts()

        self.assertEqual(
            (counts.all_count, counts.no_automation_count, counts.automation_count), (3, 1, 2)
        )
        self.assertEqual(counts.total, 1)
        self.assertEqual(DoneUseCase(s).counts(CATEGORY_AUTOMATION).total, 2)
        self.assertEqual(DoneUseCase(s).counts(CATEGORY_ALL).total, 3)

    def test_a_project_choice_excludes_that_projects_automation_items(self):
        s = FakeStore()
        for id, label in [("P-1", None), ("P-2", RETRO_ORIGIN_LABEL)]:
            item = s.create_item("item %s" % id, "d", id=id, project="proj")
            s.complete_node(item, "merged", disposition="completed")
            if label:
                s.label_add(item, label)

        rows = DoneUseCase(s).execute(DoneInput(project="proj")).rows

        self.assertEqual([r.step.id for r in rows], ["P-1"])

    def test_day_counts_follow_the_category(self):
        uc = DoneUseCase(_mixed_store())

        self.assertEqual([(d.day.day, d.count) for d in uc.day_counts()], [(1, 1)])
        self.assertEqual(
            [(d.day.day, d.count) for d in uc.day_counts(category=CATEGORY_ALL)], [(2, 1), (1, 2)]
        )
        self.assertEqual(
            [(d.day.day, d.count) for d in uc.day_counts(category=CATEGORY_AUTOMATION)], [(2, 1), (1, 1)]
        )


class TestAutomationUseCase(unittest.TestCase):
    def test_total_counts_and_sums_spend_across_automation_items(self):
        s = FakeStore()
        _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit", cost=1.0)
        _closed(s, "SUM-1", label=SUMMARY_ORIGIN_LABEL, step="daily-summary", cost=0.5)
        _closed(s, "LC-1", cost=9.0)

        total = AutomationUseCase(s).execute(AutomationInput())

        self.assertEqual(total.count, 2)
        self.assertEqual(total.spend.cost_usd.micros, 1_500_000)

    def test_day_filters_by_closed_date(self):
        s = FakeStore()
        _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit")
        _closed(s, "AUD-2", label=RETRO_ORIGIN_LABEL, step="audit", closed_at="2026-01-02T10:00:00+00:00")

        self.assertEqual(AutomationUseCase(s).execute(AutomationInput(day=DAY)).count, 1)

    def test_an_in_flight_automation_item_is_excluded(self):
        s = FakeStore()
        item = s.create_item("running", "d", id="AUD-1")
        s.create_step(stage="audit", role="agent", item=item)
        s.label_add(item, RETRO_ORIGIN_LABEL)

        self.assertEqual(AutomationUseCase(s).execute(AutomationInput()).count, 0)

    def test_an_abandoned_automation_item_is_counted(self):
        s = FakeStore()
        _closed(s, "AUD-1", label=RETRO_ORIGIN_LABEL, step="audit", disposition="abandoned")

        self.assertEqual(AutomationUseCase(s).execute(AutomationInput()).count, 1)
