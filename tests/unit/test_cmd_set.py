import io
import unittest
from contextlib import redirect_stdout, redirect_stderr

from lightcycle import cli
from lightcycle.application.flow import BlockInput, BlockStepUseCase
from tests.support.fake_store import FakeStore
from tests.support.harness import DEFAULT_WORKFLOW, Harness


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class FakeContainer:
    def __init__(self, store):
        self.store = store


class TestCmdSetRefusesFlagsOutsideState(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(FakeContainer(self.store))

    def test_needs_without_state_blocked_is_refused(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        BlockStepUseCase(self.store).execute(
            BlockInput(step=bid, needs="pick a colour", reason="needed a decision")
        )
        rc, out, err = call(cli.cmd_set, bid, "--needs", "", "--description", "ANSWERED")
        self.assertNotEqual(rc, 0)
        self.assertIn("--needs", err)
        self.assertIn("blocked", err)
        t = self.store.get_node(bid)
        self.assertEqual(t.needs, "pick a colour")
        self.assertIsNone(t.description)

    def test_blocked_without_reason_is_refused(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--state", "blocked", "--needs", "decide X")
        self.assertEqual(rc, 2)
        self.assertIn("--reason", err)
        t = self.store.get_node(bid)
        self.assertEqual(t.role, "agent")
        self.assertIsNone(t.needs)

    def test_blocked_refuses_generic_edit_flags(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(
            cli.cmd_set, bid, "--state", "blocked", "--needs", "decide X", "--title", "renamed"
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("--title", err)
        t = self.store.get_node(bid)
        self.assertEqual(t.role, "agent")
        self.assertNotEqual(t.title, "renamed")

    def test_ready_refuses_any_other_flag(self):
        bid = self.store.create_step("build: x", step="build", role="human")
        rc, out, err = call(cli.cmd_set, bid, "--state", "ready", "--title", "renamed")
        self.assertNotEqual(rc, 0)
        self.assertIn("--title", err)

    def test_in_progress_refuses_any_other_flag(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--state", "in_progress", "--description", "d")
        self.assertNotEqual(rc, 0)
        self.assertIn("--description", err)

    def test_active_refuses_generic_edit_flags(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--state", "active", "--title", "renamed")
        self.assertNotEqual(rc, 0)
        self.assertIn("--title", err)

    def test_unknown_state_is_still_refused_with_its_own_message(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--state", "bogus")
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown --state", err)

    def test_generic_edit_with_allowed_flags_succeeds(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--description", "d", "--goal", "g")
        self.assertEqual(rc, 0)
        t = self.store.get_node(bid)
        self.assertEqual(t.description, "d")
        self.assertEqual(t.goal, "g")

    def test_notes_replaces_existing_notes(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        self.store.note(bid, "old note")
        rc, out, err = call(cli.cmd_set, bid, "--notes", "replacement")
        self.assertEqual(rc, 0, err)
        t = self.store.get_node(bid)
        self.assertEqual(t.notes, "replacement")

    def test_notes_empty_clears_notes(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        self.store.note(bid, "old note")
        rc, out, err = call(cli.cmd_set, bid, "--notes", "")
        self.assertEqual(rc, 0, err)
        t = self.store.get_node(bid)
        self.assertFalse(t.notes)

    def test_notes_combined_with_state_is_refused(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(
            cli.cmd_set, bid, "--state", "blocked", "--needs", "decide X", "--notes", "x"
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("--notes", err)


class TestCmdSetRefusesFlagsOutsideStateViaHarness(unittest.TestCase):
    def test_active_with_valid_flags_succeeds(self):
        h = Harness(["coder", "reviewer"])
        item = h.store.create_item("st")
        rc, step_id, err = h.run(
            "set", item, "--state", "active", "--workflow", DEFAULT_WORKFLOW, "--step", "build"
        )
        self.assertEqual(rc, 0)
        self.assertTrue(step_id.strip())


if __name__ == "__main__":
    unittest.main()
