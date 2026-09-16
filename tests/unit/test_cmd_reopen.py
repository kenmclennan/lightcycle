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


class TestCmdReopenOnUnknownId(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_refuses_rather_than_raising(self):
        rc, out, err = call(cli.cmd_reopen, "NOPE-1")
        self.assertEqual(rc, 1)
        self.assertIn("NOPE-1", err)


class TestCmdReopenRefusesAStep(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_names_state_ready_as_the_route_for_a_step(self):
        step = create_owned_step(self.store, "build: x", step="build", role="agent")
        rc, out, err = call(cli.cmd_reopen, step)
        self.assertEqual(rc, 1)
        self.assertIn("--state ready", err)


class TestCmdReopenRefusesANonClosedItem(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_names_the_current_state(self):
        item = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_reopen, item)
        self.assertEqual(rc, 1)
        self.assertIn("backlogged", err)


class TestCmdReopenAClosedChildlessItem(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_succeeds_and_clears_outcome_and_closed_at(self):
        item = self.store.create_item("an item", "a description")
        self.store.complete_node(item, "closed", disposition="completed")
        rc, out, err = call(cli.cmd_reopen, item)
        self.assertEqual(rc, 0, err)
        node = self.store.get_node(item)
        self.assertEqual(node.state, "backlogged")
        self.assertIsNone(node.outcome)
        self.assertIsNone(node.closed_at)


if __name__ == "__main__":
    unittest.main()
