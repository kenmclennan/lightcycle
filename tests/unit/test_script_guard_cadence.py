import contextlib
import io
import json
import unittest

from lightcycle.application.inspect.list_schedules import (
    SCRIPT_GUARD_LISTING,
    ListSchedulesInput,
    ListSchedulesUseCase,
)
from lightcycle.ports.script_runner import ScriptResult
from tests.support.schedule_fakes import ScheduleRig, block
from tests.unit.test_schedule_cadence import epoch, seed_firing

GUARD = "script:scripts/changed.sh"
KEY = "guard:weekly"


def passed(title="Sheet changed", **extra):
    payload = {"outcome": "pass", "title": title}
    payload.update(extra)
    return ScriptResult(exit_code=0, stdout=json.dumps(payload))


def rig_with_guard(**overrides):
    return ScheduleRig({"weekly": block(guard=GUARD, **overrides)})


def tick(rig, hour, minute=0):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        resp = rig.cadence.execute(epoch(hour, minute))
    return resp, err.getvalue()


class TestStartingAGuard(unittest.TestCase):
    def test_the_tick_that_starts_it_returns_without_waiting_or_filing(self):
        rig = rig_with_guard()

        resp, _ = tick(rig, 11)

        self.assertEqual(resp.fired, [])
        self.assertEqual(rig.runner.running(), [KEY])
        self.assertEqual(rig.activate.activated, [])

    def test_it_gets_guard_env_params_stdin_and_the_data_dir(self):
        rig = rig_with_guard(sheet="abc-1")

        tick(rig, 11)

        call = rig.runner.started[0]
        self.assertEqual(call["env"]["LC_WORKFLOW_SCRIPT"], "guard")
        self.assertEqual(call["env"]["LC_SCHEDULE_ID"], "weekly")
        self.assertEqual(call["env"]["LC_SCHEDULE_PARAM_SHEET"], "abc-1")
        self.assertNotIn("LC_WORKFLOW_HOOK", call["env"])
        self.assertEqual(call["cwd"], "/data/lightcycle/audit")
        self.assertTrue(call["script"].endswith("/scripts/changed.sh"))
        self.assertEqual(json.loads(call["stdin"]), {"schedule": "weekly", "last_state": None})

    def test_the_last_firings_schedule_state_is_passed_as_a_cursor(self):
        rig = rig_with_guard()
        seed_firing(rig, "weekly", "2026-10-14T08:00:00", state="cursor-7")

        tick(rig, 11)

        self.assertEqual(json.loads(rig.runner.started[0]["stdin"])["last_state"], "cursor-7")

    def test_a_running_guard_is_not_started_twice(self):
        rig = rig_with_guard()

        tick(rig, 11)
        tick(rig, 11, 5)

        self.assertEqual(len(rig.runner.started), 1)

    def test_a_missing_config_key_warns_and_does_not_record_evaluated(self):
        rig = rig_with_guard()
        rig.lifecycle.missing = ("api-token",)

        _, err = tick(rig, 11)

        self.assertIn("api-token", err)
        self.assertEqual(rig.runner.started, [])
        rig.lifecycle.missing = ()
        tick(rig, 11, 5)
        self.assertEqual(len(rig.runner.started), 1)


class TestReapingAGuard(unittest.TestCase):
    def _reaped(self, result, **rig_kwargs):
        rig = rig_with_guard(**rig_kwargs)
        tick(rig, 11)
        rig.runner.finish(KEY, result)
        resp, err = tick(rig, 11, 1)
        return rig, resp, err

    def test_pass_files_an_item_with_the_printed_title_description_and_state(self):
        rig, resp, _ = self._reaped(passed(description="3 rows", state="cursor-8"))

        self.assertEqual(len(resp.fired), 1)
        item = rig.store.get_item(resp.fired[0])
        self.assertEqual((item.title, item.description), ("Sheet changed", "3 rows"))
        state = [a.value for a in rig.store.item_artifacts(item.id) if a.type == "schedule-state"]
        self.assertEqual(state, ["cursor-8"])
        self.assertEqual(rig.activate.activated, [item.id])

    def test_fail_files_nothing(self):
        rig, resp, _ = self._reaped(ScriptResult(exit_code=0, stdout='{"outcome": "fail"}'))

        self.assertEqual((resp.fired, rig.activate.activated), ([], []))

    def test_violations_file_nothing_and_warn(self):
        cases = {
            "non-zero exit": ScriptResult(exit_code=3, stderr_tail="kaboom"),
            "timeout": ScriptResult(exit_code=None, timed_out=True),
            "bad json": ScriptResult(exit_code=0, stdout="nope"),
            "pass without a title": ScriptResult(exit_code=0, stdout='{"outcome": "pass"}'),
            "unknown key": ScriptResult(exit_code=0, stdout='{"outcome": "fail", "x": 1}'),
        }
        for label, result in cases.items():
            with self.subTest(label):
                rig, resp, err = self._reaped(result)

                self.assertEqual((resp.fired, rig.activate.activated), ([], []))
                self.assertIn("weekly", err)

    def test_a_broken_guard_is_not_run_again_until_the_next_due_time(self):
        rig, _, _ = self._reaped(ScriptResult(exit_code=1))

        tick(rig, 11, 30)
        self.assertEqual(len(rig.runner.started), 1)
        tick(rig, 12)
        self.assertEqual(len(rig.runner.started), 2)

    def test_a_restarted_pool_evaluates_the_same_due_time_once_more(self):
        rig = rig_with_guard()
        tick(rig, 11)
        rig.cadence.reset()
        rig.runner.finish(KEY, ScriptResult(exit_code=1))
        tick(rig, 11, 1)

        tick(rig, 11, 2)

        self.assertEqual(len(rig.runner.started), 2)

    def test_a_result_is_dropped_when_the_schedule_is_no_longer_enabled(self):
        rig = rig_with_guard()
        tick(rig, 11)
        rig.config.blocks["weekly"]["enabled"] = "false"
        rig.runner.finish(KEY, passed())

        resp, _ = tick(rig, 11, 1)

        self.assertEqual((resp.fired, rig.activate.activated), ([], []))

    def test_a_result_is_dropped_when_schedules_are_paused(self):
        rig = rig_with_guard()
        tick(rig, 11)
        rig.config.paused = "true"
        rig.runner.finish(KEY, passed())

        resp, _ = tick(rig, 11, 1)

        self.assertEqual(resp.fired, [])
        self.assertEqual(rig.activate.activated, [])

    def test_a_result_is_dropped_when_an_item_is_already_open(self):
        rig = rig_with_guard()
        tick(rig, 11)
        seed_firing(rig, "weekly", "2026-10-14T08:00:00", done=False)
        rig.runner.finish(KEY, passed())

        resp, _ = tick(rig, 11, 1)

        self.assertEqual(resp.fired, [])
        self.assertEqual(rig.activate.activated, [])


class TestListingNeverRunsAScriptGuard(unittest.TestCase):
    def test_the_listing_says_the_pool_evaluates_it_and_runs_nothing(self):
        rig = rig_with_guard()
        use_case = ListSchedulesUseCase(rig.store, rig.config, rig.flow, rig.source, rig.git)

        rows = use_case.execute(ListSchedulesInput(now=epoch(11))).rows

        self.assertEqual(rig.runner.started, [])
        self.assertIn(SCRIPT_GUARD_LISTING, [r.guard_result for r in rows])
