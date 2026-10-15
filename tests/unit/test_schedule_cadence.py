import datetime
import unittest

from lightcycle.application.flow.engine_steps import SCHEDULE_ORIGIN_LABEL
from lightcycle.application.work.automation import automation_kind, is_automation_item
from tests.support.fake_git import FakeGit
from tests.support.schedule_fakes import (
    ScheduleRig,
    StubFlow,
    StubWorkflowSource,
    block,
)


def epoch(hour, minute=0, day=14):
    return datetime.datetime(2026, 10, day, hour, minute).timestamp()


def seed_firing(rig, schedule_id, created, done=True, state=""):
    item = rig.store.create_item("prior", "d", shortcode="APP")
    rig.store.label_add(item, "schedule:%s" % schedule_id)
    rig.store._records[item]["created_at"] = created
    if state:
        rig.store.add_artifact(item, "schedule-state", state, internal=True)
    if done:
        rig.store.complete_node(item, "merged")
    return item


class CountingGuards:
    def __init__(self, cadence, passed=True):
        self.calls = 0
        self._inner = cadence._guards
        self._passed = passed
        cadence._guards = self

    def evaluate(self, guard, params, firings, now_local):
        self.calls += 1
        result = self._inner.evaluate(guard, params, firings, now_local)
        return result if self._passed else type(result)(False, "forced")


class TestFiring(unittest.TestCase):
    def test_a_due_schedule_with_a_passing_guard_files_one_activated_automation_item(self):
        rig = ScheduleRig({"weekly": block(labels="audit weekly", shortcode="AUD")})

        resp = rig.cadence.execute(epoch(11))

        self.assertEqual(len(resp.fired), 1)
        item_id = resp.fired[0]
        item = rig.store.get_item(item_id)
        labels = rig.store.labels_of(item_id)
        self.assertTrue(item_id.startswith("AUD-"))
        self.assertEqual(item.workflow, "lightcycle/audit")
        self.assertIn(SCHEDULE_ORIGIN_LABEL, labels)
        self.assertIn("schedule:weekly", labels)
        self.assertIn("audit", labels)
        self.assertIn("weekly", labels)
        self.assertEqual(rig.activate.activated, [item_id])
        kinds = {a.type: a.value for a in rig.store.item_artifacts(item_id)}
        self.assertEqual(item.repo, "acme/app")
        self.assertIn("schedule-state", kinds)
        self.assertTrue(is_automation_item(rig.store, item))
        self.assertEqual(automation_kind(rig.store, item), "scheduled")

    def test_the_project_shortcode_is_the_default(self):
        rig = ScheduleRig({"weekly": block()})
        resp = rig.cadence.execute(epoch(11))
        self.assertTrue(resp.fired[0].startswith("APP-"))

    def test_a_failing_guard_files_nothing_and_is_asked_once_per_due_time(self):
        rig = ScheduleRig({"weekly": block()})
        seed_firing(rig, "weekly", "2026-10-14T08:00:00",
                    state="")
        guard = CountingGuards(rig.cadence, passed=False)

        first = rig.cadence.execute(epoch(11))
        second = rig.cadence.execute(epoch(11, 5))
        third = rig.cadence.execute(epoch(12))

        self.assertEqual(first.fired, [])
        self.assertEqual(second.fired, [])
        self.assertEqual(third.fired, [])
        self.assertEqual(guard.calls, 2)

    def test_an_open_item_blocks_firing_including_a_backlogged_one(self):
        rig = ScheduleRig({"weekly": block()})
        seed_firing(rig, "weekly", "2026-10-14T08:00:00", done=False)

        resp = rig.cadence.execute(epoch(11))

        self.assertEqual(resp.fired, [])
        self.assertEqual(resp.skipped[0][0], "weekly")
        self.assertIn("open item", resp.skipped[0][1])

    def test_an_outage_across_three_due_times_files_exactly_one_item(self):
        rig = ScheduleRig({"hourly": block(guard="day-unsummarised")})
        closed = rig.store.create_item("work", "d", id="LC-1")
        rig.store.complete_node(closed, "merged")
        rig.store._records[closed]["closed_at"] = "2026-10-14T10:30:00+00:00"
        prior = seed_firing(rig, "hourly", "2026-10-14T08:00:00")

        first = rig.cadence.execute(epoch(11))
        for item in first.fired:
            rig.store.complete_node(item, "merged")
        second = rig.cadence.execute(epoch(11, 1))

        self.assertEqual(len(first.fired), 1)
        self.assertEqual(second.fired, [])
        self.assertNotIn(prior, first.fired)

    def test_a_never_fired_schedule_files_on_the_first_tick(self):
        rig = ScheduleRig({"weekly": block()})
        self.assertEqual(len(rig.cadence.execute(epoch(9, 30)).fired), 1)

    def test_a_disabled_block_files_nothing(self):
        rig = ScheduleRig({"weekly": block(enabled="false")})
        resp = rig.cadence.execute(epoch(11))
        self.assertEqual((resp.fired, resp.skipped), ([], []))

    def test_a_bundle_suggestion_with_no_config_block_files_nothing(self):
        flow = StubFlow({"lightcycle/audit": {
            "schedule": {"cron": "0 * * * *", "guard": "materials-changed"}}})
        source = StubWorkflowSource(
            workflows={"lightcycle/audit": None}, shas={"lightcycle": "sha1"})
        rig = ScheduleRig({}, flow=flow, source=source)

        resp = rig.cadence.execute(epoch(11))

        self.assertEqual((resp.fired, resp.skipped), ([], []))
        self.assertEqual(rig.store.all_items_including_done(), [])

    def test_config_overrides_the_suggestion_field_by_field(self):
        flow = StubFlow({"lightcycle/audit": {
            "schedule": {"cron": "0 0 1 1 *", "guard": "day-unsummarised"}}})
        rig = ScheduleRig(
            {"weekly": {"enabled": "true", "workflow": "lightcycle/audit",
                        "project": "acme/app", "cron": "0 * * * *",
                        "guard": "materials-changed"}},
            flow=flow)
        self.assertEqual(len(rig.cadence.execute(epoch(11)).fired), 1)

    def test_a_suggestion_supplies_the_cron_and_guard_a_block_leaves_out(self):
        flow = StubFlow({"lightcycle/audit": {
            "schedule": {"cron": "0 * * * *", "guard": "materials-changed"}}})
        rig = ScheduleRig(
            {"weekly": {"enabled": "true", "workflow": "lightcycle/audit",
                        "project": "acme/app"}},
            flow=flow)
        self.assertEqual(len(rig.cadence.execute(epoch(11)).fired), 1)

    def test_a_valid_schedule_fires_while_broken_ones_are_skipped_with_reasons(self):
        rig = ScheduleRig({
            "good": block(),
            "badguard": block(guard="shell-out"),
            "badflow": block(workflow="lightcycle/ghost"),
        })

        resp = rig.cadence.execute(epoch(11))

        self.assertEqual(len(resp.fired), 1)
        reasons = dict(resp.skipped)
        self.assertIn("unknown guard", reasons["badguard"])
        self.assertIn("does not resolve", reasons["badflow"])

    def test_an_unregistered_project_is_skipped(self):
        rig = ScheduleRig({"weekly": block(project="acme/ghost")})
        resp = rig.cadence.execute(epoch(11))
        self.assertEqual(resp.fired, [])
        self.assertIn("project acme/ghost", dict(resp.skipped)["weekly"])

    def test_a_guard_that_cannot_read_the_world_does_not_file(self):
        git = FakeGit(raises=("ref_sha",))
        rig = ScheduleRig({"weekly": block()}, git=git)
        rig.store.add_project("guidance", local_path="/tmp/g")
        git._ref = "origin/main"

        resp = rig.cadence.execute(epoch(11))

        self.assertEqual(resp.fired, [])
        self.assertIn("could not read", dict(resp.skipped)["weekly"])

    def test_a_failed_activation_leaves_the_item_open_and_blocks_the_next_tick(self):
        from lightcycle.application.errors import UseCaseError
        rig = ScheduleRig({"weekly": block()}, activate_fail=UseCaseError("clone failed"))

        first = rig.cadence.execute(epoch(11))
        second = rig.cadence.execute(epoch(12))

        self.assertEqual(first.fired, [])
        self.assertIn("could not activate", dict(first.skipped)["weekly"])
        self.assertIn("open item", dict(second.skipped)["weekly"])


class TestPause(unittest.TestCase):
    def test_a_paused_tick_files_nothing_and_asks_no_guard(self):
        rig = ScheduleRig({"weekly": block()}, paused="true")
        guard = CountingGuards(rig.cadence)

        resp = rig.cadence.execute(epoch(11))

        self.assertEqual(resp.fired, [])
        self.assertEqual(resp.skipped, [("weekly", "paused")])
        self.assertEqual(guard.calls, 0)
        self.assertEqual(rig.flow.meta_reads, 0)

    def test_resuming_after_three_missed_due_times_files_exactly_one_item(self):
        rig = ScheduleRig({"hourly": block()}, paused="true")
        seed_firing(rig, "hourly", "2026-10-14T08:00:00")
        rig.cadence.execute(epoch(9))
        rig.cadence.execute(epoch(10))
        rig.cadence.execute(epoch(11))

        rig.config.paused = "false"
        resumed = rig.cadence.execute(epoch(11, 2))
        for item in resumed.fired:
            rig.store.complete_node(item, "merged")
        after = rig.cadence.execute(epoch(11, 3))

        self.assertEqual(len(resumed.fired), 1)
        self.assertEqual(after.fired, [])

    def test_an_unreadable_pause_value_pauses(self):
        rig = ScheduleRig({"weekly": block()}, paused="maybe")
        resp = rig.cadence.execute(epoch(11))
        self.assertEqual(resp.fired, [])
        self.assertEqual(resp.skipped, [("weekly", "paused")])

    def test_a_disabled_schedule_is_not_listed_as_paused(self):
        rig = ScheduleRig({"weekly": block(enabled="false")}, paused="true")
        self.assertEqual(rig.cadence.execute(epoch(11)).skipped, [])

