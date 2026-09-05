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
        rc, out, err = call(cli.cmd_set, bid, "--needs", "")
        self.assertNotEqual(rc, 0)
        self.assertIn("--needs", err)
        self.assertIn("blocked", err)
        t = self.store.get_node(bid)
        self.assertEqual(t.park.needs, "pick a colour")

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
        item = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_set, item, "--state", "active", "--title", "renamed")
        self.assertNotEqual(rc, 0)
        self.assertIn("--title", err)

    def test_unknown_state_is_still_refused_with_its_own_message(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--state", "bogus")
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown --state", err)

    def test_generic_edit_with_allowed_flags_succeeds(self):
        iid = self.store.create_item("an item", "old")
        rc, out, err = call(cli.cmd_set, iid, "--description", "d")
        self.assertEqual(rc, 0)
        self.assertEqual(self.store.get_item(iid).description, "d")

    def test_notes_replaces_existing_notes(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        self.store.note(bid, "old note")
        rc, out, err = call(cli.cmd_set, bid, "--notes", "replacement")
        self.assertEqual(rc, 0, err)
        t = self.store.get_node(bid)
        self.assertEqual(t.notes, "replacement")

    def test_notes_empty_is_refused(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        self.store.note(bid, "old note")
        rc, out, err = call(cli.cmd_set, bid, "--notes", "")
        self.assertNotEqual(rc, 0)
        self.assertIn("--notes", err)
        self.assertIn("--unset", err)
        t = self.store.get_node(bid)
        self.assertEqual(t.notes, "old note")

    def test_unset_notes_clears_notes(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        self.store.note(bid, "old note")
        rc, out, err = call(cli.cmd_set, bid, "--unset", "notes")
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


class TestCmdSetEmptyStringIsNeverAValue(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(FakeContainer(self.store))

    def test_title_empty_is_refused(self):
        iid = self.store.create_item("original title", "a description")
        rc, out, err = call(cli.cmd_set, iid, "--title", "")
        self.assertNotEqual(rc, 0)
        self.assertIn("--title", err)
        self.assertEqual(self.store.get_item(iid).title, "original title")

    def test_description_empty_is_refused(self):
        iid = self.store.create_item("an item", "original description")
        rc, out, err = call(cli.cmd_set, iid, "--description", "")
        self.assertNotEqual(rc, 0)
        self.assertIn("--description", err)
        self.assertIn("--unset description", err)
        self.assertEqual(self.store.get_item(iid).description, "original description")

    def test_project_empty_is_refused(self):
        iid = self.store.create_item("an item", "a description", project="alpha")
        rc, out, err = call(cli.cmd_set, iid, "--project", "")
        self.assertNotEqual(rc, 0)
        self.assertIn("--unset project", err)
        self.assertEqual(self.store.get_item(iid).project, "alpha")

    def test_workflow_empty_is_refused(self):
        iid = self.store.create_item("an item", "a description", workflow="custom@sha")
        rc, out, err = call(cli.cmd_set, iid, "--workflow", "")
        self.assertNotEqual(rc, 0)
        self.assertIn("--unset workflow", err)
        self.assertEqual(self.store.get_item(iid).workflow, "custom@sha")

    def test_label_empty_is_refused(self):
        iid = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_set, iid, "--label", "")
        self.assertNotEqual(rc, 0)

    def test_tried_empty_combined_with_state_blocked_is_refused_before_parking(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(
            cli.cmd_set, bid, "--state", "blocked", "--needs", "X", "--reason", "Y", "--tried", ""
        )
        self.assertNotEqual(rc, 0)
        t = self.store.get_node(bid)
        self.assertEqual(t.role, "agent")
        self.assertFalse(t.park)

    def test_unset_description_clears_description(self):
        iid = self.store.create_item("an item", "original description")
        rc, out, err = call(cli.cmd_set, iid, "--unset", "description")
        self.assertEqual(rc, 0, err)
        self.assertFalse(self.store.get_item(iid).description)

    def test_unset_project_clears_project(self):
        iid = self.store.create_item("an item", "a description", project="alpha")
        rc, out, err = call(cli.cmd_set, iid, "--unset", "project")
        self.assertEqual(rc, 0, err)
        self.assertFalse(self.store.get_item(iid).project)

    def test_unset_workflow_clears_workflow(self):
        iid = self.store.create_item("an item", "a description", workflow="custom@sha")
        rc, out, err = call(cli.cmd_set, iid, "--unset", "workflow")
        self.assertEqual(rc, 0, err)
        self.assertFalse(self.store.get_item(iid).workflow)

    def test_unset_several_fields_in_one_call(self):
        iid = self.store.create_item(
            "an item", "original description", workflow="custom@sha"
        )
        rc, out, err = call(
            cli.cmd_set, iid, "--unset", "description", "--unset", "workflow"
        )
        self.assertEqual(rc, 0, err)
        item = self.store.get_item(iid)
        self.assertFalse(item.description)
        self.assertFalse(item.workflow)

    def test_unset_title_is_refused(self):
        iid = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_set, iid, "--unset", "title")
        self.assertNotEqual(rc, 0)
        self.assertIn("a title must not be blank", err)

    def test_unset_label_is_refused(self):
        iid = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_set, iid, "--unset", "label")
        self.assertNotEqual(rc, 0)
        self.assertIn("there is no way to clear a label this way", err)

    def test_unset_needs_is_refused(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--unset", "needs")
        self.assertNotEqual(rc, 0)
        self.assertIn("--state ready", err)

    def test_unset_reason_is_refused(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--unset", "reason")
        self.assertNotEqual(rc, 0)
        self.assertIn("--state ready", err)

    def test_unset_tried_is_refused(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--unset", "tried")
        self.assertNotEqual(rc, 0)
        self.assertIn("--state ready", err)

    def test_unset_description_on_a_step_is_refused_by_field_ownership(self):
        bid = self.store.create_step("build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_set, bid, "--unset", "description")
        self.assertNotEqual(rc, 0)
        self.assertIn("--description", err)
        self.assertIn("a step", err)

    def test_unset_notes_on_an_item_is_refused_by_field_ownership(self):
        iid = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_set, iid, "--unset", "notes")
        self.assertNotEqual(rc, 0)
        self.assertIn("--notes", err)
        self.assertIn("an item", err)

    def test_value_and_unset_on_the_same_field_is_a_contradiction(self):
        iid = self.store.create_item("an item", "a description", project="alpha")
        rc, out, err = call(cli.cmd_set, iid, "--project", "x", "--unset", "project")
        self.assertNotEqual(rc, 0)
        self.assertIn("--project", err)
        self.assertEqual(self.store.get_item(iid).project, "alpha")

    def test_unset_combined_with_state_is_refused(self):
        iid = self.store.create_item("an item", "a description")
        rc, out, err = call(
            cli.cmd_set, iid, "--state", "active", "--unset", "description"
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("--unset", err)

    def test_unset_description_alone_succeeds(self):
        iid = self.store.create_item("an item", "original description")
        rc, out, err = call(cli.cmd_set, iid, "--unset", "description")
        self.assertEqual(rc, 0, err)
        self.assertNotIn("nothing to set", err)


class TestCmdSetRefusesFlagsOutsideStateViaHarness(unittest.TestCase):
    def test_active_with_valid_flags_succeeds(self):
        h = Harness(["coder", "reviewer"])
        item = h.store.create_item("st", "a description")
        rc, step_id, err = h.run(
            "set", item, "--state", "active", "--workflow", DEFAULT_WORKFLOW, "--step", "build"
        )
        self.assertEqual(rc, 0)
        self.assertTrue(step_id.strip())


if __name__ == "__main__":
    unittest.main()
