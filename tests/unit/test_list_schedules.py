import datetime
import unittest

from lightcycle.application.inspect.list_schedules import ListSchedulesInput, ListSchedulesUseCase
from tests.support.schedule_fakes import ScheduleRig, StubFlow, StubWorkflowSource, block

NOW = datetime.datetime(2026, 10, 14, 11, 30).timestamp()

SUGGESTION = {"schedule": {"cron": "0 9 * * 1", "guard": "materials-changed"}}


def rows_of(rig, now=NOW):
    uc = ListSchedulesUseCase(rig.store, rig.config, rig.flow, rig.source, rig.git)
    return {r.id: r for r in uc.execute(ListSchedulesInput(now=now)).rows}


def suggesting_rig(blocks=None, paused="false"):
    return ScheduleRig(
        blocks or {}, paused=paused,
        flow=StubFlow({"lightcycle/audit": SUGGESTION}),
        source=StubWorkflowSource(
            workflows={"lightcycle/audit": None}, shas={"lightcycle": "sha1"}))


class TestName(unittest.TestCase):
    def test_a_row_carries_the_block_name_or_none(self):
        rig = ScheduleRig({"named": block(name="audit"), "plain": block()})

        rows = rows_of(rig)

        self.assertEqual((rows["named"].name, rows["plain"].name), ("audit", None))
        self.assertEqual(rows["named"].as_dict()["name"], "audit")
        self.assertIsNone(rows["plain"].as_dict()["name"])


class TestStates(unittest.TestCase):
    def test_a_bare_suggestion_is_off_and_listed_from_the_bundle(self):
        rows = rows_of(suggesting_rig())

        row = rows["lightcycle/audit"]
        self.assertEqual((row.state, row.source), ("off", "bundle"))
        self.assertEqual(row.reason, "bundle suggestion, not enabled in config")
        self.assertEqual((row.cron, row.guard), ("0 9 * * 1", "materials-changed"))

    def test_enabled_false_is_off_and_the_suggestion_is_not_listed_twice(self):
        rows = rows_of(suggesting_rig({"weekly": block(enabled="false")}))

        self.assertEqual(list(rows), ["weekly"])
        self.assertEqual((rows["weekly"].state, rows["weekly"].source), ("off", "both"))
        self.assertEqual(rows["weekly"].reason, "config sets enabled: false")

    def test_an_enabled_schedule_is_on_waiting_for_its_next_due_time(self):
        row = rows_of(ScheduleRig({"weekly": block()}))["weekly"]

        self.assertEqual((row.state, row.reason), ("on", "waiting for next due time"))
        self.assertEqual(row.source, "config")
        self.assertEqual(row.next_fire, "2026-10-14 12:00")
        self.assertEqual(row.last_fire, "never")
        self.assertTrue(row.guard_result.startswith("passed: "))

    def test_an_open_item_is_named_as_the_reason(self):
        rig = ScheduleRig({"weekly": block()})
        item = rig.store.create_item("prior", "d", shortcode="APP")
        rig.store.label_add(item, "schedule:weekly")
        rig.store._records[item]["created_at"] = "2026-10-14T08:00:00"

        row = rows_of(rig)["weekly"]

        self.assertEqual((row.state, row.reason), ("on", "open item %s blocks firing" % item))
        self.assertEqual(row.last_fire, "2026-10-14 08:00")

    def test_an_invalid_enabled_schedule_is_on_with_the_problem(self):
        row = rows_of(ScheduleRig({"weekly": block(guard="shell-out")}))["weekly"]

        self.assertEqual(row.state, "on")
        self.assertTrue(row.reason.startswith("invalid: "))
        self.assertEqual((row.next_fire, row.guard_result), ("-", "-"))

    def test_the_pause_key_shows_enabled_schedules_as_paused(self):
        rows = rows_of(ScheduleRig({"weekly": block()}, paused="true"))

        self.assertEqual(rows["weekly"].state, "paused")
        self.assertEqual(rows["weekly"].reason, "schedules-paused is true in config")

    def test_an_unreadable_pause_value_reads_as_paused(self):
        row = rows_of(ScheduleRig({"weekly": block()}, paused="maybe"))["weekly"]

        self.assertEqual(row.state, "paused")
        self.assertIn("unreadable", row.reason)

    def test_off_outranks_paused(self):
        rows = rows_of(suggesting_rig({"weekly": block(enabled="false")}, paused="true"))
        self.assertEqual(rows["weekly"].state, "off")
        rows = rows_of(suggesting_rig({}, paused="true"))
        self.assertEqual(rows["lightcycle/audit"].state, "off")

    def test_listing_writes_nothing(self):
        rig = ScheduleRig({"weekly": block()})
        before = [i.id for i in rig.store.all_items_including_done()]

        rows_of(rig)

        self.assertEqual([i.id for i in rig.store.all_items_including_done()], before)
        self.assertEqual(rig.activate.activated, [])
