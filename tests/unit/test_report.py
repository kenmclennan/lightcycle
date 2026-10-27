import dataclasses
import datetime
import unittest

from lightcycle.application.flow.engine_steps import RETRO_ORIGIN_LABEL, SUMMARY_ORIGIN_LABEL
from lightcycle.application.work.backlog import BacklogInput, BacklogUseCase
from lightcycle.application.work.report import ReportInput, ReportResponse, ReportUseCase, _backlog_start_and_close
from lightcycle.domain.money import Cost
from lightcycle.domain.work import item_cost
from tests.support.fake_store import FakeStore


def _local_midnight_iso(day):
    return datetime.datetime.combine(day, datetime.time()).astimezone().isoformat()


def _closed_item(store, *, disposition, closed_at, id=None, label=None, step=None):
    item = store.create_item("item", "a description", id=id)
    if step:
        store.complete_node(store.create_step(stage=step, role="agent", item=item), "done")
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
        self.assertEqual(resp.backlog_start, 0)
        self.assertEqual(resp.backlog_close, 0)
        self.assertEqual(resp.backlog_delta, 0)
        self.assertFalse(resp.spend.cost_usd)

    def test_cost_matches_item_cost_over_the_days_closed_items_children(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        step = s.create_step(stage="build", role="agent", item=item)
        s.claim_ready("agent")
        s.record_usage(step, 100, 10, 0, 0, 2.50, "list", None)
        s.complete_node(step, "done")
        s.complete_node(item, "merged", disposition="completed")
        s._records[item]["closed_at"] = "2026-01-01T10:00:00+00:00"

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        expected = item_cost(s.children(item))
        self.assertEqual(resp.spend.cost_usd, expected.cost_usd)
        self.assertEqual(resp.spend.unpriced_count, expected.unpriced_count)


class TestReportUseCaseCacheHitRate(unittest.TestCase):
    def _closed_with_tokens(self, s, id, cache_read, input_tokens, label=None):
        item = s.create_item("item", "a description", id=id)
        step = s.create_step(stage="build", role="agent", item=item)
        s.claim_ready("agent")
        s.record_usage(step, input_tokens, 0, cache_read, 0, 1.0, "list", None)
        s.complete_node(step, "done")
        s.complete_node(item, "merged", disposition="completed")
        s._records[item]["closed_at"] = "2026-01-01T10:00:00+00:00"
        if label:
            s.label_add(item, label)

    def test_the_rate_counts_automation_items_tokens(self):
        s = FakeStore()
        self._closed_with_tokens(s, "LC-1", cache_read=90, input_tokens=10)
        self._closed_with_tokens(s, "SUM-1", cache_read=0, input_tokens=100, label=SUMMARY_ORIGIN_LABEL)

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertAlmostEqual(resp.cache_hit_rate, 90 / 200)
        self.assertAlmostEqual(resp.spend.cache_hit_rate, 0.9)

    def test_a_day_with_no_tokens_has_no_rate(self):
        resp = ReportUseCase(FakeStore()).execute(ReportInput(day=datetime.date(2026, 1, 1)))

        self.assertIsNone(resp.cache_hit_rate)


class TestReportUseCaseBacklog(unittest.TestCase):
    def test_item_created_the_same_day_as_the_snapshot_is_excluded(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s._records[item]["created_at"] = "2026-01-05T08:00:00"
        s.create_step(stage="build", role="agent", item=item)

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
        s.create_step(stage="build", role="agent", item=leaver)
        s._records[s.children(leaver)[0].id]["created_at"] = "2026-01-05T08:00:00"

        resp = ReportUseCase(s).execute(ReportInput(day=datetime.date(2026, 1, 5)))

        self.assertEqual(resp.backlog_start, 1)
        self.assertEqual(resp.backlog_close, 0)
        self.assertEqual(resp.backlog_delta, -1)

    def test_a_reopened_item_with_abandoned_steps_counts_as_backlog_like_lc_backlog_does(self):
        s = FakeStore()
        item = s.create_item("reopened", "a description")
        s._records[item]["created_at"] = "2026-01-01T08:00:00"
        step = s.create_step(stage="build", role="agent", item=item)
        s._records[step]["created_at"] = "2026-01-02T08:00:00"
        s.complete_node(step, "done")
        s.complete_node(item, "abandoned", disposition="abandoned")
        s.reopen(item)
        day = datetime.date(2026, 1, 5)

        resp = ReportUseCase(s).execute(ReportInput(day=day))
        listed = BacklogUseCase(s, None).execute(BacklogInput()).rows

        self.assertEqual(len(listed), 1)
        self.assertEqual(resp.backlog_close, len(listed))


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


class TestReportUseCaseReads(unittest.TestCase):
    DAY = datetime.date(2026, 1, 1)

    def test_execute_reads_all_steps_exactly_once(self):
        s = FakeStore()
        item = s.create_item("item", "a description")
        s.create_step(stage="review-code", role="agent", item=item)
        calls = {"n": 0}
        original = s.all_steps_including_done

        def counted():
            calls["n"] += 1
            return original()

        s.all_steps_including_done = counted

        ReportUseCase(s).execute(ReportInput(day=self.DAY))

        self.assertEqual(calls["n"], 1)

    def test_the_response_has_no_slow_steps_field(self):
        self.assertNotIn("slow_steps", [f.name for f in dataclasses.fields(ReportResponse)])


if __name__ == "__main__":
    unittest.main()


def _project_item(store, project, *, disposition="completed", closed_at="2026-01-01T10:00:00+00:00",
                  cost=None, label=None):
    item = store.create_item("item", "a description", project=project)
    step = store.create_step(stage="write-code", role="agent", item=item)
    if cost is not None:
        store.claim_ready("agent")
        store.record_usage(step, 100, 10, 5, 2, cost, "list", None)
    store.complete_node(step, "done")
    store.complete_node(item, "merged", disposition=disposition)
    store._records[item]["closed_at"] = closed_at
    if label:
        store.label_add(item, label)
    return item


def _store_summary(store, day, text):
    with store.transaction():
        store.mark_day_summary_dirty(day)
        store.start_day_summary(day, step_id="s", spawn_count=1)
    store.finish_day_summary(day, summary=text, summarized_count=1, clear_dirty=True)


DAY = datetime.date(2026, 1, 1)


class TestReportProjectSections(unittest.TestCase):
    def _store(self):
        s = FakeStore()
        _project_item(s, "kenmclennan/lightcycle", cost=1.0)
        _project_item(s, "kenmclennan/lightcycle", disposition="abandoned", cost=0.5)
        _project_item(s, "kenmclennan/lightcycle", cost=0.25)
        _project_item(s, "kenmclennan/yori", cost=2.0)
        _project_item(s, None, cost=0.75)
        _project_item(s, "kenmclennan/lightcycle", cost=9.0, label=RETRO_ORIGIN_LABEL)
        return s

    def test_sections_are_ordered_by_closed_count_then_label_and_exclude_automation(self):
        resp = ReportUseCase(self._store()).execute(ReportInput(day=DAY))

        self.assertEqual([p.project for p in resp.projects], ["lightcycle", None, "yori"])
        self.assertEqual(resp.automation_count, 1)
        self.assertEqual(resp.projects[0].completed + resp.projects[0].abandoned, 3)

    def test_ties_on_closed_count_sort_by_displayed_label(self):
        s = FakeStore()
        _project_item(s, "kenmclennan/yori")
        _project_item(s, "kenmclennan/alpha")
        _project_item(s, None)

        resp = ReportUseCase(s).execute(ReportInput(day=DAY))

        self.assertEqual([p.project for p in resp.projects], [None, "alpha", "yori"])

    def test_sections_sum_to_the_day_totals(self):
        resp = ReportUseCase(self._store()).execute(ReportInput(day=DAY))
        sections = resp.projects

        self.assertEqual(sum(p.completed for p in sections), resp.completed)
        self.assertEqual(sum(p.abandoned for p in sections), resp.abandoned)
        self.assertEqual(
            sum(p.completed + p.abandoned for p in sections), resp.completed + resp.abandoned
        )
        for attr in (
            "turn_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
        ):
            self.assertEqual(sum(getattr(p.spend, attr) for p in sections), getattr(resp.spend, attr), attr)
        self.assertEqual(sum((p.spend.cost_usd for p in sections), Cost.from_usd(0)), resp.spend.cost_usd)

    def test_summary_bullets_land_in_their_project_and_the_rest_is_unmatched(self):
        s = FakeStore()
        a = _project_item(s, "kenmclennan/lightcycle")
        b = _project_item(s, "kenmclennan/yori")
        text = "Delivered\n- One [%s]\n- Two [%s]\n- Stray [ZZ-1]\n\nFixed\n- Three [%s]" % (a, b, a)
        _store_summary(s, DAY, text)

        resp = ReportUseCase(s).execute(ReportInput(day=DAY))
        by_project = {p.project: p for p in resp.projects}

        self.assertEqual(by_project["lightcycle"].delivered, ("- One [%s]" % a,))
        self.assertEqual(by_project["lightcycle"].fixed, ("- Three [%s]" % a,))
        self.assertEqual(by_project["yori"].delivered, ("- Two [%s]" % b,))
        self.assertEqual(resp.summary_unmatched, "Delivered\n- Stray [ZZ-1]")
        self.assertEqual(resp.summary, text)

    def test_an_id_free_summary_is_wholly_unmatched(self):
        s = FakeStore()
        _project_item(s, "kenmclennan/lightcycle")
        text = "A themed prose summary of the day with no ids."
        _store_summary(s, DAY, text)

        resp = ReportUseCase(s).execute(ReportInput(day=DAY))

        self.assertEqual(resp.summary_unmatched, text)
        self.assertEqual(resp.projects[0].delivered, ())

    def test_no_stored_summary_leaves_unmatched_none(self):
        s = FakeStore()
        _project_item(s, "kenmclennan/lightcycle")

        resp = ReportUseCase(s).execute(ReportInput(day=DAY))

        self.assertIsNone(resp.summary_unmatched)
