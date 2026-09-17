import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lightcycle import cli
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class _FakeConfig:
    def max_title_length(self):
        return 200


class _Container:
    def __init__(self, store):
        self.store = store
        self.config = _FakeConfig()
        self.git = None
        self.fs = None
        self.workflow_source = None
        self.workflow_bundle = None
        self.scaffold = None


class TestCmdCloseOnUnknownId(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_refuses_rather_than_raising(self):
        rc, out, err = call(cli.cmd_close, "NOPE-1")
        self.assertEqual(rc, 1)
        self.assertIn("NOPE-1", err)


class TestCmdCloseRefusesAStep(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_names_done_as_the_verb_for_a_step(self):
        step = create_owned_step(self.store, "build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_close, step)
        self.assertEqual(rc, 2)
        self.assertIn("done", err)
        self.assertEqual(self.store.get_node(step).state, "queued")


class TestCmdCloseDefaults(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_no_flags_closes_completed_with_reason_closed(self):
        item = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_close, item)
        self.assertEqual(rc, 0, err)
        node = self.store.get_node(item)
        self.assertEqual(node.state, "done")
        self.assertEqual(node.outcome, "closed")
        self.assertEqual(node.disposition, "completed")

    def test_outcome_is_free_form_text_not_validated(self):
        item = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_close, item, "--outcome", "duplicate of LC-1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_node(item).outcome, "duplicate of LC-1")

    def test_disposition_can_be_overridden_to_abandoned(self):
        item = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_close, item, "--disposition", "abandoned")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_node(item).disposition, "abandoned")

    def test_note_is_recorded(self):
        item = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_close, item, "--note", "worth", "keeping")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_node(item).note, "worth keeping")


if __name__ == "__main__":
    unittest.main()
