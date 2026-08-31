import io
import unittest
from contextlib import redirect_stdout, redirect_stderr

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


class FakeContainer:
    def __init__(self, store):
        self.store = store


class TestCmdDep(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(FakeContainer(self.store))

    def test_remove_calls_store_remove(self):
        blocker = self.store.create_step("blocker", role="coder")
        blocked = self.store.create_step("blocked", role="coder")
        self.store.dep_add(blocked, blocker)
        rc, out, err = call(cli.cmd_dep, blocked, "--remove", blocker)
        self.assertEqual(rc, 0)
        ready_ids = [t.id for t in self.store.ready_steps()]
        self.assertIn(blocked, ready_ids)

    def test_needs_and_remove_together_is_a_usage_error(self):
        blocker = self.store.create_step("blocker", role="coder")
        blocked = self.store.create_step("blocked", role="coder")
        rc, out, err = call(cli.cmd_dep, blocked, "--needs", blocker, "--remove", blocker)
        self.assertNotEqual(rc, 0)

    def test_neither_needs_nor_remove_is_a_usage_error(self):
        blocked = self.store.create_step("blocked", role="coder")
        rc, out, err = call(cli.cmd_dep, blocked)
        self.assertNotEqual(rc, 0)

    def test_add_succeeds_when_both_ids_exist(self):
        blocker = self.store.create_step("blocker", role="coder")
        blocked = self.store.create_step("blocked", role="coder")
        rc, out, err = call(cli.cmd_dep, blocked, "--needs", blocker)
        self.assertEqual(rc, 0)
        ready_ids = [t.id for t in self.store.ready_steps()]
        self.assertNotIn(blocked, ready_ids)

    def test_add_refuses_empty_id(self):
        blocker = self.store.create_step("blocker", role="coder")
        rc, out, err = call(cli.cmd_dep, "", "--needs", blocker)
        self.assertEqual(rc, 1)
        self.assertIn("unknown node", err)
        self.assertEqual(self.store._deps.get(""), None)

    def test_add_refuses_empty_needs(self):
        blocked = self.store.create_step("blocked", role="coder")
        rc, out, err = call(cli.cmd_dep, blocked, "--needs", "")
        self.assertEqual(rc, 1)
        self.assertIn("unknown node", err)
        self.assertEqual(self.store._deps.get(blocked), set())

    def test_add_refuses_nonexistent_blocked_id(self):
        blocker = self.store.create_step("blocker", role="coder")
        rc, out, err = call(cli.cmd_dep, "does-not-exist", "--needs", blocker)
        self.assertEqual(rc, 1)
        self.assertIn("unknown node 'does-not-exist'", err)

    def test_add_refuses_nonexistent_needs_id(self):
        blocked = self.store.create_step("blocked", role="coder")
        rc, out, err = call(cli.cmd_dep, blocked, "--needs", "does-not-exist")
        self.assertEqual(rc, 1)
        self.assertIn("unknown node 'does-not-exist'", err)
        self.assertEqual(self.store._deps.get(blocked), set())


if __name__ == "__main__":
    unittest.main()
