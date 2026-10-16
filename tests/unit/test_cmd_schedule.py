import json
import unittest
from pathlib import Path

from tests.support.fake_fs import graph_text_from_metas
from tests.support.harness import Harness

_METAS = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}

_SUGGESTION = "---\nschedule:\n  cron: 0 9 * * 1\n  guard: materials-changed\n---\n"

_ROW_KEYS = {
    "id", "source", "state", "reason", "workflow", "project", "cron", "guard",
    "last_fire", "next_fire", "guard_result",
}


def _harness():
    return Harness(["coder"], workflow_text=_SUGGESTION + graph_text_from_metas(_METAS, entry="build"))


class TestScheduleListCommand(unittest.TestCase):
    def test_json_rows_carry_the_documented_shape_for_a_bare_suggestion(self):
        h = _harness()

        rc, out, err = h.run("schedule", "list", "--json")

        self.assertEqual(rc, 0, err)
        rows = json.loads(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), _ROW_KEYS)
        self.assertEqual(rows[0]["id"], "lightcycle/spec-driven")
        self.assertEqual((rows[0]["source"], rows[0]["state"]), ("bundle", "off"))
        self.assertEqual(rows[0]["last_fire"], "never")

    def test_listing_writes_nothing_to_the_store(self):
        h = _harness()
        before = len(h.store.all_items_including_done())

        h.run("schedule", "list", "--json")

        self.assertEqual(len(h.store.all_items_including_done()), before)

    def test_an_enabled_block_shows_on_and_the_text_mode_prints_state_and_reason(self):
        h = _harness()
        cfg = Path(h._cfg)
        cfg.write_text(cfg.read_text() + (
            "schedule-weekly:\n  enabled: true\n  workflow: lightcycle/spec-driven\n"
            "  project: acme/app\n"))

        rc, out, err = h.run("schedule", "list")

        self.assertEqual(rc, 0, err)
        fields = out.splitlines()[0].split("\t")
        self.assertEqual(fields[:4], ["weekly", "both", "on", "waiting for next due time"])

    def test_no_subcommand_prints_help_and_refuses(self):
        h = _harness()
        rc, _out, _err = h.run("schedule")
        self.assertEqual(rc, 2)


class TestScheduleRunCommand(unittest.TestCase):
    def _enabled(self, extra=""):
        h = _harness()
        cfg = Path(h._cfg)
        cfg.write_text(cfg.read_text() + (
            "schedule-weekly:\n  enabled: true\n  workflow: lightcycle/spec-driven\n"
            "  project: acme/app\n" + extra))
        return h

    def test_run_records_a_request_and_list_shows_it_pending(self):
        h = self._enabled()

        rc, out, err = h.run("schedule", "run", "weekly")

        self.assertEqual(rc, 0, err)
        self.assertIn("next tick", out)
        self.assertTrue(h.store.schedule_run_requested("weekly"))
        _rc, listing, _err = h.run("schedule", "list")
        self.assertEqual(listing.splitlines()[0].split("\t")[3], "run requested")

    def test_run_refuses_an_unknown_id_and_records_nothing(self):
        h = self._enabled()

        rc, _out, err = h.run("schedule", "run", "nope")

        self.assertEqual(rc, 1)
        self.assertIn("nope", err)
        self.assertFalse(h.store.schedule_run_requested("nope"))

    def test_help_lists_run(self):
        h = _harness()
        rc, out, _err = h.run("schedule", "--help")
        self.assertIn("run", out)
