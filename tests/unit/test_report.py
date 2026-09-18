import datetime
import unittest

from lightcycle.application.flow.engine_steps import RETRO_ORIGIN_LABEL
from lightcycle.application.work.report import ReportInput, ReportUseCase, _backlog_size_asof_pair
from lightcycle.domain.work import item_cost
from tests.support.fake_store import FakeStore


def _local_midnight_iso(day):
    return datetime.datetime.combine(day, datetime.time()).astimezone().isoformat()


def _closed_item(store, *, disposition, closed_at, id=None, label=None):
    item = store.create_item("item", "a description", id=id)
    store.complete_node(item, "merged", disposition=disposition)
    store._records[item]["closed_at"] = closed_at
    if label:
        store.label_add(item, label)
    return item


class TestReportUseCase(unittest.TestCase):
    def test_counts_completed_and_abandoned_separately(self):
        s = FakeStore()
        _closed_item(s, disposition="completed", closed_at="2026-01-01T10:00:00+00:00")
        _closed_item(s, disposition="abandoned", closed_at="2026-01-01T11:00:00+00:00")

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.completed, 1)
        self.assertEqual(resp.abandoned, 1)

    def test_counts_legacy_aborted_disposition_as_abandoned(self):
        s = FakeStore()
        _closed_item(s, disposition="abandoned", closed_at="2026-01-01T10:00:00+00:00")
        _closed_item(s, disposition="aborted", closed_at="2026-01-01T11:00:00+00:00")

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.abandoned, 2)

    def test_audit_is_counted_by_label_regardless_of_id_shortcode(self):
        s = FakeStore()
        _closed_item(
            s, disposition="completed", closed_at="2026-01-01T10:00:00+00:00",
            id="AUD-1", label=RETRO_ORIGIN_LABEL,
        )
        _closed_item(
            s, disposition="completed", closed_at="2026-01-01T10:00:00+00:00",
            id="LC-1", label=RETRO_ORIGIN_LABEL,
        )
        _closed_item(
            s, disposition="completed", closed_at="2026-01-01T10:00:00+00:00", id="LC-2",
        )

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.audits, 2)
        self.assertEqual(resp.completed, 3)

    def test_a_day_with_zero_closed_items_returns_a_valid_all_zero_response(self):
        s = FakeStore()

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.completed, 0)
        self.assertEqual(resp.abandoned, 0)
        self.assertEqual(resp.audits, 0)
        self.assertEqual(resp.escalations, 0)
        self.assertEqual(resp.backlog_size, 0)
        self.assertEqual(resp.backlog_delta, 0)
        self.assertFalse(resp.spend.cost_usd)

    def test_cost_matches_item_cost_over_the_days_closed_items_children(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(step="build", role="agent", parent=item)
        s.claim_ready("agent")
        s.record_usage(step, 100, 10, 0, 0, 2.50, "list", None)
        s.complete_node(step, "done")
        s.complete_node(item, "merged", disposition="completed")
        s._records[item]["closed_at"] = "2026-01-01T10:00:00+00:00"

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        expected = item_cost(s.children(item))
        self.assertEqual(resp.spend.cost_usd, expected.cost_usd)
        self.assertEqual(resp.spend.unpriced_count, expected.unpriced_count)


class TestReportUseCaseBacklog(unittest.TestCase):
    def test_item_created_the_same_day_as_the_snapshot_is_excluded(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s._records[item]["created_at"] = "2026-01-05T08:00:00"
        s.create_step(step="build", role="agent", parent=item)

        today, _yesterday = _backlog_size_asof_pair(s, datetime.date(2026, 1, 5))

        self.assertEqual(today, 0)

    def test_item_created_the_day_before_with_no_step_yet_is_included(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s._records[item]["created_at"] = "2026-01-04T08:00:00"

        today, _yesterday = _backlog_size_asof_pair(s, datetime.date(2026, 1, 5))

        self.assertEqual(today, 1)

    def test_item_closed_exactly_at_day_start_is_excluded(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s._records[item]["created_at"] = "2026-01-01T08:00:00"
        s.complete_node(item, "merged", disposition="completed")
        s._records[item]["closed_at"] = _local_midnight_iso(datetime.date(2026, 1, 5))

        today, _yesterday = _backlog_size_asof_pair(s, datetime.date(2026, 1, 5))

        self.assertEqual(today, 0)

    def test_delta_equals_todays_size_minus_yesterdays_across_two_distinct_days(self):
        s = FakeStore()
        earlier = s.create_item("earlier", "a description")
        s._records[earlier]["created_at"] = "2026-01-01T08:00:00"
        later = s.create_item("later", "a description")
        s._records[later]["created_at"] = "2026-01-04T08:00:00"

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 5)))

        self.assertEqual(resp.backlog_size, 2)
        self.assertEqual(resp.backlog_delta, 1)


class TestReportUseCaseEscalations(unittest.TestCase):
    def test_a_step_still_parked_with_a_waiting_entry_on_the_day_counts(self):
        s = FakeStore(now=lambda: "2026-01-01T10:00:00+00:00")
        item = s.create_item("item", "a description")
        step = s.create_step(step="build", role="agent", parent=item)
        s.reassign(step, "human")

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.escalations, 1)

    def test_a_resolved_park_still_counts_even_though_its_current_role_is_agent_again(self):
        s = FakeStore(now=lambda: "2026-01-01T10:00:00+00:00")
        item = s.create_item("item", "a description")
        step = s.create_step(step="build", role="agent", parent=item)
        s.reassign(step, "human")
        s.reassign(step, "agent")

        self.assertEqual(s.get_node(step).role, "agent")
        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.escalations, 1)

    def test_a_waiting_entry_on_a_different_day_does_not_count(self):
        s = FakeStore(now=lambda: "2026-01-02T10:00:00+00:00")
        item = s.create_item("item", "a description")
        step = s.create_step(step="build", role="agent", parent=item)
        s.reassign(step, "human")

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.escalations, 0)

    def test_counting_is_unaffected_by_park_reason_already_being_cleared(self):
        s = FakeStore(now=lambda: "2026-01-01T10:00:00+00:00")
        item = s.create_item("item", "a description")
        step = s.create_step(step="build", role="agent", parent=item)
        s.reassign(step, "human")
        s.update_metadata(step, {"reason": None, "needs": None, "tried": None})
        s.reassign(step, "agent")

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.escalations, 1)


class TestReportUseCaseSummary(unittest.TestCase):
    def test_a_day_with_a_generated_summary_returns_it(self):
        s = FakeStore()
        day = datetime.date(2026, 1, 1)
        with s.transaction():
            s.mark_day_summary_dirty(day)
            s.start_day_summary(day, step_id="step-1", spawn_count=0)
        s.finish_day_summary(day, summary="what shipped", summarized_count=0, clear_dirty=True)

        resp = ReportUseCase(s).execute(ReportInput(day=day))

        self.assertEqual(resp.summary, "what shipped")

    def test_a_day_with_no_row_returns_none(self):
        s = FakeStore()

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertIsNone(resp.summary)

    def test_a_day_with_a_row_but_no_summary_yet_returns_none(self):
        s = FakeStore()
        day = datetime.date(2026, 1, 1)
        s.mark_day_summary_dirty(day)

        resp = ReportUseCase(s).execute(ReportInput(day=day))

        self.assertIsNone(resp.summary)


if __name__ == "__main__":
    unittest.main()
