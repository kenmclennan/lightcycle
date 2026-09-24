import datetime
import unittest

from lightcycle.application.flow.engine_steps import RETRO_ORIGIN_LABEL, SUMMARY_ORIGIN_LABEL
from lightcycle.application.work.backlog import BacklogInput, BacklogUseCase
from lightcycle.application.work.report import ReportInput, ReportUseCase, _backlog_start_and_close
from lightcycle.domain.work import item_cost
from tests.support.fake_store import FakeStore


def _local_midnight_iso(day):
    return datetime.datetime.combine(day, datetime.time()).astimezone().isoformat()


def _closed_item(store, *, disposition, closed_at, id=None, label=None, step=None):
    item = store.create_item("item", "a description", id=id)
    if step:
        store.complete_node(store.create_step(step=step, role="agent", parent=item), "done")
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

    def test_automation_is_excluded_from_project_figures_by_label_regardless_of_id_shortcode(self):
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

        self.assertEqual(resp.automation_count, 2)
        self.assertEqual(resp.completed, 1)

    def test_all_automation_day_has_no_completed_and_a_non_zero_automation_count(self):
        s = FakeStore()
        _closed_item(
            s, disposition="completed", closed_at="2026-01-01T10:00:00+00:00",
            id="SUM-1", label=SUMMARY_ORIGIN_LABEL, step="daily-summary",
        )

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.completed, 0)
        self.assertEqual(resp.automation_count, 1)

    def test_a_day_with_zero_closed_items_returns_a_valid_all_zero_response(self):
        s = FakeStore()

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertEqual(resp.completed, 0)
        self.assertEqual(resp.abandoned, 0)
        self.assertEqual(resp.automation_count, 0)
        self.assertEqual(resp.escalations, 0)
        self.assertEqual(resp.backlog_start, 0)
        self.assertEqual(resp.backlog_close, 0)
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

        start, _close = _backlog_start_and_close(s, datetime.date(2026, 1, 5))

        self.assertEqual(start, 0)

    def test_item_created_the_day_before_with_no_step_yet_is_included(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s._records[item]["created_at"] = "2026-01-04T08:00:00"

        start, _close = _backlog_start_and_close(s, datetime.date(2026, 1, 5))

        self.assertEqual(start, 1)

    def test_item_closed_exactly_at_day_start_is_excluded(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s._records[item]["created_at"] = "2026-01-01T08:00:00"
        s.complete_node(item, "merged", disposition="completed")
        s._records[item]["closed_at"] = _local_midnight_iso(datetime.date(2026, 1, 5))

        start, _close = _backlog_start_and_close(s, datetime.date(2026, 1, 5))

        self.assertEqual(start, 0)

    def test_delta_is_the_days_own_movement_from_starting_to_closing_size(self):
        s = FakeStore()
        earlier = s.create_item("earlier", "a description")
        s._records[earlier]["created_at"] = "2026-01-01T08:00:00"
        entered = s.create_item("entered", "a description")
        s._records[entered]["created_at"] = "2026-01-05T08:00:00"
        also_entered = s.create_item("also entered", "a description")
        s._records[also_entered]["created_at"] = "2026-01-05T09:00:00"

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 5)))

        self.assertEqual(resp.backlog_start, 1)
        self.assertEqual(resp.backlog_close, 3)
        self.assertEqual(resp.backlog_delta, 2)

    def test_delta_is_negative_when_more_items_leave_the_backlog_than_enter(self):
        s = FakeStore()
        leaver = s.create_item("leaver", "a description")
        s._records[leaver]["created_at"] = "2026-01-01T08:00:00"
        s.create_step(step="build", role="agent", parent=leaver)
        s._records[s.children(leaver)[0].id]["created_at"] = "2026-01-05T08:00:00"

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 5)))

        self.assertEqual(resp.backlog_start, 1)
        self.assertEqual(resp.backlog_close, 0)
        self.assertEqual(resp.backlog_delta, -1)

    def test_a_reopened_item_with_abandoned_steps_counts_as_backlog_like_lc_backlog_does(self):
        s = FakeStore()
        item = s.create_item("reopened", "a description")
        s._records[item]["created_at"] = "2026-01-01T08:00:00"
        step = s.create_step(step="build", role="agent", parent=item)
        s._records[step]["created_at"] = "2026-01-02T08:00:00"
        s.complete_node(step, "done")
        s.complete_node(item, "abandoned", disposition="abandoned")
        s.reopen(item)
        day = datetime.date(2026, 1, 5)

        resp = ReportUseCase(s).execute(ReportInput(day=day))
        listed = BacklogUseCase(s, None).execute(BacklogInput()).rows

        self.assertEqual(len(listed), 1)
        self.assertEqual(resp.backlog_close, len(listed))


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


def _seed_step(store, item, stage, seconds, *, turns=0, closed_at=None, finish=True):
    step = store.create_step(step=stage, role="agent", parent=item)
    store.claim_ready("agent")
    store.accrue_active_seconds([step], seconds)
    if turns:
        store.record_attribution(step, turns, {})
    if finish:
        store.complete_node(step, "done")
        store._records[step]["closed_at"] = closed_at
    return step


def _seed_history(store, item, stage, count, closed_at):
    for n in range(count):
        _seed_step(store, item, stage, 60 * (n + 1), turns=6 * (n + 1), closed_at=closed_at)


class TestReportUseCaseSlowSteps(unittest.TestCase):
    DAY = datetime.date(2026, 1, 1)
    ON_DAY = "2026-01-01T10:00:00+00:00"
    OTHER_DAY = "2026-01-02T10:00:00+00:00"

    def _store_with_history(self, count=20, stage="review-code"):
        s = FakeStore()
        item = s.create_item("item", "a description")
        _seed_history(s, item, stage, count, "2025-12-20T10:00:00+00:00")
        return s, item

    def test_a_slow_step_closed_on_the_day_is_listed(self):
        s, item = self._store_with_history()
        slow = _seed_step(s, item, "review-code", 3167.5, turns=87, closed_at=self.ON_DAY)

        resp = ReportUseCase(s).execute(ReportInput(day=self.DAY))

        self.assertEqual([r.step.id for r in resp.slow_steps], [slow])

    def test_the_same_step_closed_on_another_day_is_not_listed(self):
        s, item = self._store_with_history()
        _seed_step(s, item, "review-code", 3167.5, turns=87, closed_at=self.OTHER_DAY)

        resp = ReportUseCase(s).execute(ReportInput(day=self.DAY))

        self.assertEqual(resp.slow_steps, [])

    def test_a_running_step_is_not_listed(self):
        s, item = self._store_with_history()
        _seed_step(s, item, "review-code", 3167.5, turns=87, finish=False)

        resp = ReportUseCase(s).execute(ReportInput(day=self.DAY))

        self.assertEqual(resp.slow_steps, [])

    def test_a_day_with_two_slow_steps_lists_only_the_one_in_a_measured_stage(self):
        s, item = self._store_with_history(count=20, stage="review-code")
        _seed_history(s, item, "spec-writer", 19, "2025-12-20T10:00:00+00:00")
        measured = _seed_step(s, item, "review-code", 3000, turns=30, closed_at=self.ON_DAY)
        _seed_step(s, item, "spec-writer", 9000, turns=30, closed_at=self.ON_DAY)

        resp = ReportUseCase(s).execute(ReportInput(day=self.DAY))

        self.assertEqual([r.step.id for r in resp.slow_steps], [measured])

    def test_execute_reads_all_steps_exactly_once(self):
        s, item = self._store_with_history()
        calls = {"n": 0}
        original = s.all_steps_including_done

        def counted():
            calls["n"] += 1
            return original()

        s.all_steps_including_done = counted

        ReportUseCase(s).execute(ReportInput(day=self.DAY))

        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
