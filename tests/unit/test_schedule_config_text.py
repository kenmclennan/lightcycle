import datetime
import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.inspect.list_schedules import ListSchedulesInput, ListSchedulesUseCase
from lightcycle.config import _SEED_KEYS, Config
from tests.support.schedule_fakes import ScheduleRig

NOW = datetime.datetime(2026, 10, 14, 11, 30).timestamp()


def real_config(guard_lines):
    text = "".join("%s: %s\n" % (k, v) for k, v in _SEED_KEYS)
    text += (
        "schedule-reflect:\n"
        "  enabled: true\n"
        "  workflow: lightcycle/audit\n"
        "  project: acme/app\n"
        "  cron: 0 * * * *\n"
        "  guard: pending-reflections\n" + guard_lines
    )
    path = os.path.join(tempfile.mkdtemp(), "config")
    Path(path).write_text(text)
    return Config(environ={"LC_CONFIG": path})


def rig_over(config):
    rig = ScheduleRig()
    rig.config = config
    rig.cadence._config = config
    rig.cadence._resolver._config = config
    return rig


class TestParamsFromConfigText(unittest.TestCase):
    def test_the_tick_reads_a_min_written_in_config_text_without_crashing(self):
        rig = rig_over(real_config("  min: 1\n"))

        resp = rig.cadence.execute(datetime.datetime(2026, 10, 14, 11).timestamp())

        self.assertEqual(resp.fired, [])
        self.assertEqual(resp.skipped, [])

    def test_list_reads_a_min_written_in_config_text(self):
        rig = rig_over(real_config("  min: 1\n"))
        uc = ListSchedulesUseCase(rig.store, rig.config, rig.flow, rig.source, rig.git)

        row = {r.id: r for r in uc.execute(ListSchedulesInput(now=NOW)).rows}["reflect"]

        self.assertEqual(row.state, "on")
        self.assertTrue(row.guard_result.startswith("not passed: 0 pending reflections, needs 1"))

    def test_a_bad_min_is_the_schedules_problem_in_the_tick_and_in_list(self):
        rig = rig_over(real_config("  min: lots\n"))

        resp = rig.cadence.execute(datetime.datetime(2026, 10, 14, 11).timestamp())
        uc = ListSchedulesUseCase(rig.store, rig.config, rig.flow, rig.source, rig.git)
        row = {r.id: r for r in uc.execute(ListSchedulesInput(now=NOW)).rows}["reflect"]

        self.assertEqual([sid for sid, _ in resp.skipped], ["reflect"])
        self.assertIn("min must be an integer", resp.skipped[0][1])
        self.assertIn("min must be an integer", row.reason)

    def test_an_unexpected_guard_error_is_one_schedules_skipped_reason(self):
        rig = rig_over(real_config("  min: 1\n"))

        class Boom:
            def evaluate(self, *args):
                raise RuntimeError("boom")

        rig.cadence._guards = Boom()

        resp = rig.cadence.execute(datetime.datetime(2026, 10, 14, 11).timestamp())

        self.assertEqual(resp.fired, [])
        self.assertEqual(resp.skipped, [("reflect", "guard pending-reflections failed: boom")])
