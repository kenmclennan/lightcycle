import datetime
import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.flow import CompleteInput, CompleteStepUseCase
from lightcycle.application.flow.engine_steps import SCHEDULE_ORIGIN_LABEL
from lightcycle.application.flow.schedule_completion import ScheduleCompletion
from lightcycle.application.pool.schedule_guards import GuardResult
from lightcycle.application.work import ReportInput, ReportUseCase
from lightcycle.config import Config
from lightcycle.domain.feedback import RETROED_LABEL
from lightcycle.domain.schedule.schedule import merge_schedule
from lightcycle.domain.schedule.state import parse_batch_state, parse_day_state
from tests.support.fake_store import FakeStore
from tests.support.schedule_fakes import ScheduleRig, StubFlow
from tests.unit.test_flow_usecases import METAS, flow_for

DAY = datetime.date(2026, 10, 14)


class PassingGuards:
    def evaluate(self, guard, params, firings, now_local):
        return GuardResult(True, "forced", title="filed", description="d", state="batch: X-1")


def _fresh_config():
    root = tempfile.mkdtemp()
    path = os.path.join(root, "config")
    config = Config(environ={"LC_HOME": root, "LC_CONFIG": path})
    config.ensure_config()
    return config, path


class TestSeededConfig(unittest.TestCase):
    def test_a_fresh_config_seeds_the_three_schedules_enabled(self):
        config, path = _fresh_config()
        blocks = config.schedule_blocks()
        self.assertEqual(
            sorted(blocks), ["daily-summary", "material-audit", "retro-audit"])
        expected = {
            "retro-audit": ("lightcycle/retro-audit", "AUD", "0 9 * * *", "pending-reflections"),
            "material-audit": ("lightcycle/material-audit", "AUD", "0 9 * * 1", "materials-changed"),
            "daily-summary": ("lightcycle/daily-summary", "SUM", "0 7 * * *", "day-unsummarised"),
        }
        for sid, (workflow, shortcode, cron, guard) in expected.items():
            with self.subTest(sid):
                schedule = merge_schedule(sid, blocks[sid], None, workflow=workflow)
                self.assertTrue(schedule.enabled)
                self.assertIsNone(schedule.problem)
                self.assertEqual(
                    (schedule.workflow, schedule.shortcode, schedule.cron, schedule.guard,
                     schedule.project),
                    (workflow, shortcode, cron, guard, "guidance"))
        self.assertEqual(
            merge_schedule("retro-audit", blocks["retro-audit"], None).params, {"min": 30})

    def test_the_blocks_follow_the_seed_keys(self):
        _config, path = _fresh_config()
        lines = Path(path).read_text().splitlines()
        first = next(i for i, ln in enumerate(lines) if ln.startswith("schedule-"))
        self.assertTrue(all(not ln.startswith("schedule-") for ln in lines[:first]))
        self.assertTrue(any(ln.startswith("max-agents:") for ln in lines[:first]))

    def test_ensure_config_again_leaves_the_file_byte_identical(self):
        config, path = _fresh_config()
        before = Path(path).read_bytes()
        config.ensure_config()
        self.assertEqual(Path(path).read_bytes(), before)

    def test_an_existing_file_never_gains_a_schedule_block(self):
        config, path = _fresh_config()
        text = Path(path).read_text()
        kept = "\n".join(
            ln for ln in text.splitlines()
            if not ln.startswith(("schedule-", "  "))) + "\nschedule-x:\n  enabled: false\n"
        Path(path).write_text(kept)
        config.reload()
        config.ensure_config()
        config.reconcile_config()
        self.assertEqual(Path(path).read_text(), kept)
        self.assertEqual(sorted(config.schedule_blocks()), ["x"])

    def test_the_removed_keys_are_not_seeded_and_are_reported_when_left_behind(self):
        config, path = _fresh_config()
        for key in ("retro-interval-reflections", "material-audit-days",
                    "daily-summary-debounce-seconds", "summary-shortcode"):
            self.assertNotIn("%s:" % key, Path(path).read_text())
        with open(path, "a") as f:
            f.write("retro-interval-reflections: 20\nsummary-shortcode: SUM\n")
        config.reload()
        self.assertEqual(
            sorted(config.obsolete_config_keys()),
            ["retro-interval-reflections", "summary-shortcode"])


class TestHandOver(unittest.TestCase):
    def _rig(self, extra_blocks=None):
        config, _path = _fresh_config()
        blocks = config.schedule_blocks()
        blocks.update(extra_blocks or {})
        flow = StubFlow({
            "lightcycle/retro-audit": {}, "lightcycle/material-audit": {},
            "lightcycle/daily-summary": {}})
        rig = ScheduleRig(blocks, flow=flow)
        rig.cadence._guards = PassingGuards()
        rig.store.add_project("kenmclennan/guidance", local_path="/tmp/guidance")
        for block in blocks.values():
            if block.get("project") == "guidance":
                block["project"] = "kenmclennan/guidance"
        return rig

    def test_each_seeded_schedule_files_one_item_on_its_workflow(self):
        rig = self._rig()
        now = datetime.datetime(2026, 10, 19, 9, 30).timestamp()
        resp = rig.cadence.execute(now)
        self.assertEqual(resp.skipped, [])
        self.assertEqual(len(resp.fired), 3)
        by_guard = {}
        for item_id in resp.fired:
            labels = rig.store.labels_of(item_id)
            guard = next(l for l in labels if l.startswith("schedule-guard:"))
            by_guard[guard] = (item_id, rig.store.get_item(item_id).workflow, labels)
            kinds = {a.type for a in rig.store.item_artifacts(item_id)}
            self.assertIn("schedule-state", kinds)
            self.assertEqual(rig.store.get_item(item_id).repo, "kenmclennan/guidance")
            self.assertIn(SCHEDULE_ORIGIN_LABEL, labels)
        self.assertEqual(
            {g: v[1] for g, v in by_guard.items()},
            {"schedule-guard:pending-reflections": "lightcycle/retro-audit",
             "schedule-guard:materials-changed": "lightcycle/material-audit",
             "schedule-guard:day-unsummarised": "lightcycle/daily-summary"})
        self.assertIn("schedule:retro-audit", by_guard["schedule-guard:pending-reflections"][2])
        self.assertTrue(by_guard["schedule-guard:day-unsummarised"][0].startswith("SUM-"))
        self.assertTrue(by_guard["schedule-guard:materials-changed"][0].startswith("AUD-"))

    def test_a_block_without_a_shortcode_on_a_shortcode_less_project_is_refused(self):
        rig = self._rig({
            "bare": {"enabled": "true", "workflow": "lightcycle/retro-audit",
                     "project": "kenmclennan/guidance", "cron": "0 9 * * *",
                     "guard": "materials-changed"}})
        rig.config.blocks.pop("retro-audit")
        resp = rig.cadence.execute(datetime.datetime(2026, 10, 19, 9, 30).timestamp())
        reasons = dict(resp.skipped)
        self.assertIn("is registered but has no shortcode", reasons["bare"])

    def test_an_unregistered_project_is_still_refused_beside_a_valid_block(self):
        rig = self._rig({
            "ghost": {"enabled": "true", "workflow": "lightcycle/retro-audit",
                      "project": "acme/ghost", "shortcode": "GHO", "cron": "0 9 * * *",
                      "guard": "materials-changed"}})
        resp = rig.cadence.execute(datetime.datetime(2026, 10, 19, 9, 30).timestamp())
        self.assertEqual(len(resp.fired), 3)
        self.assertIn("not registered", dict(resp.skipped)["ghost"])


def _scheduled_item(store, state, summary=None):
    item = store.create_item("run", "d", shortcode="AUD", workflow="spec-driven")
    store.label_add(item, SCHEDULE_ORIGIN_LABEL)
    store.add_artifact(item, "schedule-state", state, internal=True)
    if summary is not None:
        store.add_artifact(item, "summary", summary)
    step = store.create_step(step="build", role="agent", parent=item)
    return item, step


def _closed_item(store, id):
    item = store.create_item("closed %s" % id, "d", id=id)
    child = store.create_step(step="build", role="agent", parent=item)
    store.complete_node(child, "done")
    store.complete_node(item, "merged")
    return item


class TestStateParsers(unittest.TestCase):
    def test_batch_state(self):
        self.assertEqual(parse_batch_state("batch: A-1, B-2"), ("A-1", "B-2"))
        self.assertIsNone(parse_batch_state("day: 2026-10-14 count: 3"))
        self.assertIsNone(parse_batch_state("abc123"))
        self.assertIsNone(parse_batch_state(None))

    def test_day_state(self):
        self.assertEqual(parse_day_state("day: 2026-10-14 count: 3"), ("2026-10-14", 3))
        self.assertIsNone(parse_day_state("batch: A-1"))
        self.assertIsNone(parse_day_state(""))


class TestScheduleCompletionBatch(unittest.TestCase):
    def _run(self, store, state):
        _item, step = _scheduled_item(store, state)
        ScheduleCompletion(store).execute(store.get_node(step), "done")
        return step

    def test_marks_exactly_the_unretroed_ids_of_the_batch(self):
        s = FakeStore()
        a, b, bystander = (_closed_item(s, i) for i in ("APP-1", "APP-2", "APP-3"))
        s.label_add(b, RETROED_LABEL)
        step = self._run(s, "batch: APP-1, APP-2, APP-9")
        self.assertIn(RETROED_LABEL, s.labels_of(a))
        self.assertNotIn(RETROED_LABEL, s.labels_of(bystander))
        self.assertIn("retroed: 1 of 3", s.get_node(step).notes)
        self.assertEqual([i.id for i in s.closed_unretroed_items()], ["APP-3"])

    def test_all_resolved_batch_marks_every_id(self):
        s = FakeStore()
        _closed_item(s, "APP-1")
        _closed_item(s, "APP-2")
        step = self._run(s, "batch: APP-1, APP-2")
        self.assertIn("retroed: 2 of 2", s.get_node(step).notes)
        self.assertEqual(s.closed_unretroed_items(), [])

    def test_none_resolved_batch_notes_zero(self):
        s = FakeStore()
        step = self._run(s, "batch: APP-8, APP-9")
        self.assertIn("retroed: 0 of 2", s.get_node(step).notes)

    def test_an_item_with_no_schedule_state_is_untouched(self):
        s = FakeStore()
        _closed_item(s, "APP-1")
        item = s.create_item("plain", "d", shortcode="PLN")
        step = s.create_step(step="build", role="agent", parent=item)
        ScheduleCompletion(s).execute(s.get_node(step), "done")
        self.assertEqual([i.id for i in s.closed_unretroed_items()], ["APP-1"])
        self.assertIsNone(s.get_node(step).notes)

    def test_a_materials_fingerprint_state_does_nothing(self):
        s = FakeStore()
        _closed_item(s, "APP-1")
        step = self._run(s, "3f9a0c")
        self.assertEqual([i.id for i in s.closed_unretroed_items()], ["APP-1"])
        self.assertIsNone(s.get_node(step).notes)


class TestScheduleCompletionSummary(unittest.TestCase):
    def _complete(self, store, state, outcome, summary):
        _item, step = _scheduled_item(store, state, summary)
        ScheduleCompletion(store).execute(store.get_node(step), outcome)

    def test_done_with_a_summary_artifact_records_the_day(self):
        s = FakeStore()
        self.assertIsNone(s.day_summary(DAY))
        self._complete(s, "day: 2026-10-14 count: 4", "done", "A good day.")
        row = s.day_summary(DAY)
        self.assertEqual(row.summary, "A good day.")
        self.assertEqual(row.summarized_count, 4)
        self.assertIsNone(row.dirty_since)

    def test_the_report_returns_the_recorded_text(self):
        s = FakeStore()
        self._complete(s, "day: 2026-10-14 count: 4", "done", "A good day.")
        report = ReportUseCase(s).execute(ReportInput(day=DAY))
        self.assertEqual(report.summary, "A good day.")

    def test_abandoned_writes_nothing(self):
        s = FakeStore()
        self._complete(s, "day: 2026-10-14 count: 4", "abandoned", "A good day.")
        self.assertIsNone(s.day_summary(DAY))

    def test_no_summary_artifact_writes_nothing(self):
        s = FakeStore()
        self._complete(s, "day: 2026-10-14 count: 4", "done", None)
        self.assertIsNone(s.day_summary(DAY))

    def test_a_summary_on_the_step_alone_records_the_day(self):
        s = FakeStore()
        item, step = _scheduled_item(s, "day: 2026-10-14 count: 21")
        s.add_artifact(step, "summary", "Step-level day.")
        ScheduleCompletion(s).execute(s.get_node(step), "done")
        row = s.day_summary(DAY)
        self.assertEqual((row.summary, row.summarized_count), ("Step-level day.", 21))

    def test_the_step_summary_wins_over_the_item_summary(self):
        s = FakeStore()
        item, step = _scheduled_item(s, "day: 2026-10-14 count: 2", "Item-level.")
        s.add_artifact(step, "summary", "Step-level.")
        ScheduleCompletion(s).execute(s.get_node(step), "done")
        self.assertEqual(s.day_summary(DAY).summary, "Step-level.")

    def test_a_summary_on_a_sibling_step_is_the_last_fallback(self):
        s = FakeStore()
        item, step = _scheduled_item(s, "day: 2026-10-14 count: 2")
        sibling = s.create_step(step="earlier", role="agent", parent=item)
        s.add_artifact(sibling, "summary", "From a sibling.")
        ScheduleCompletion(s).execute(s.get_node(step), "done")
        self.assertEqual(s.day_summary(DAY).summary, "From a sibling.")

    def test_a_legacy_row_with_a_higher_count_keeps_it(self):
        s = FakeStore()
        s.mark_day_summary_dirty(DAY)
        s.finish_day_summary(DAY, summary="old", summarized_count=9, clear_dirty=True)
        self._complete(s, "day: 2026-10-14 count: 4", "done", "new")
        row = s.day_summary(DAY)
        self.assertEqual((row.summary, row.summarized_count), ("new", 9))


class TestCompleteStepRunsTheScheduleRule(unittest.TestCase):
    def test_closing_a_scheduled_workflow_step_marks_the_batch(self):
        s = FakeStore()
        _closed_item(s, "APP-1")
        item = s.create_item("run", "d", shortcode="AUD", workflow="spec-driven")
        s.add_artifact(item, "schedule-state", "batch: APP-1", internal=True)
        step = s.create_step(step="build", role="agent", parent=item)
        CompleteStepUseCase(s, flow_for(METAS, s)).execute(
            CompleteInput(step=step, outcome="done"))
        self.assertEqual(s.get_node(step).state, "done")
        self.assertIn(RETROED_LABEL, s.labels_of("APP-1"))
        self.assertIn("retroed: 1 of 1", s.get_node(step).notes)
