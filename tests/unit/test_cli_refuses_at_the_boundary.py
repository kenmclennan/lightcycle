import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lightcycle import cli
from tests.support.fake_store import FakeStore


def call(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(list(args)) or 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class _Container:
    def __init__(self, store):
        self.store = store


class TestUnknownIdIsRefusedNotRaised(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_set_on_an_unknown_id_refuses(self):
        rc, out, err = call(cli.cmd_set, "NOPE-1", "--title", "x")
        self.assertEqual(rc, 1)
        self.assertIn("NOPE-1", err)

    def test_done_on_an_unknown_id_refuses(self):
        rc, out, err = call(cli.cmd_done, "NOPE-1", "done")
        self.assertEqual(rc, 1)
        self.assertIn("NOPE-1", err)


class TestNoCommandExitsZeroHavingDoneNothing(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_set_with_no_flags_refuses_rather_than_succeeding_silently(self):
        item = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_set, item)
        self.assertEqual(rc, 2)
        self.assertIn("nothing to set", err)

    def test_clearing_a_note_is_a_real_change_not_an_empty_one(self):
        step = self.store.create_step("build: x", step="build", role="agent")
        self.store.note(step, "something")
        rc, out, err = call(cli.cmd_set, step, "--notes", "")
        self.assertEqual(rc, 0, err)


class TestANoteHasSomewhereToGo(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))

    def test_new_step_takes_a_note(self):
        item = self.store.create_item("an item", "a description")
        step = self.store.create_step("build: x", step="build", role="agent", parent=item)
        self.store.note(step, "the human decided X")
        self.assertIn("the human decided X", self.store.get_step(step).notes)

    def test_a_note_on_an_item_is_refused_rather_than_discarded(self):
        item = self.store.create_item("an item", "a description")
        rc, out, err = call(cli.cmd_done, item, "done", "--note", "worth keeping")
        self.assertEqual(rc, 2)
        self.assertIn("--note", err)


if __name__ == "__main__":
    unittest.main()
