import io
import unittest
from contextlib import redirect_stdout, redirect_stderr

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


class FakeContainer:
    def __init__(self, store):
        self.store = store


class TestCmdDep(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(FakeContainer(self.store))

    def test_remove_calls_store_remove(self):
        blocker = create_owned_step(self.store, "blocker", role="agent")
        blocked = create_owned_step(self.store, "blocked", role="agent")
        self.store.dep_add(blocked, blocker)
        rc, out, err = call(cli.cmd_dep, blocked, "--remove", blocker)
        self.assertEqual(rc, 0)
        ready_ids = [t.id for t in self.store.ready_steps()]
        self.assertIn(blocked, ready_ids)

    def test_needs_and_remove_together_is_a_usage_error(self):
        blocker = create_owned_step(self.store, "blocker", role="agent")
        blocked = create_owned_step(self.store, "blocked", role="agent")
        rc, out, err = call(cli.cmd_dep, blocked, "--needs", blocker, "--remove", blocker)
        self.assertNotEqual(rc, 0)

    def test_neither_needs_nor_remove_is_a_usage_error(self):
        blocked = create_owned_step(self.store, "blocked", role="agent")
        rc, out, err = call(cli.cmd_dep, blocked)
        self.assertNotEqual(rc, 0)

    def test_add_succeeds_when_both_ids_exist(self):
        blocker = create_owned_step(self.store, "blocker", role="agent")
        blocked = create_owned_step(self.store, "blocked", role="agent")
        rc, out, err = call(cli.cmd_dep, blocked, "--needs", blocker)
        self.assertEqual(rc, 0)
        ready_ids = [t.id for t in self.store.ready_steps()]
        self.assertNotIn(blocked, ready_ids)

    def test_add_refuses_empty_id(self):
        blocker = create_owned_step(self.store, "blocker", role="agent")
        rc, out, err = call(cli.cmd_dep, "", "--needs", blocker)
        self.assertEqual(rc, 1)
        self.assertIn("unknown node", err)
        self.assertEqual(self.store._deps.get(""), None)

    def test_add_refuses_empty_needs(self):
        blocked = create_owned_step(self.store, "blocked", role="agent")
        rc, out, err = call(cli.cmd_dep, blocked, "--needs", "")
        self.assertEqual(rc, 1)
        self.assertIn("unknown node", err)
        self.assertEqual(self.store._deps.get(blocked), set())

    def test_add_refuses_nonexistent_blocked_id(self):
        blocker = create_owned_step(self.store, "blocker", role="agent")
        rc, out, err = call(cli.cmd_dep, "does-not-exist", "--needs", blocker)
        self.assertEqual(rc, 1)
        self.assertIn("unknown node 'does-not-exist'", err)

    def test_add_refuses_nonexistent_needs_id(self):
        blocked = create_owned_step(self.store, "blocked", role="agent")
        rc, out, err = call(cli.cmd_dep, blocked, "--needs", "does-not-exist")
        self.assertEqual(rc, 1)
        self.assertIn("unknown node 'does-not-exist'", err)
        self.assertEqual(self.store._deps.get(blocked), set())

    def test_add_refuses_a_claimed_target(self):
        blocker = create_owned_step(self.store, "blocker", role=None)
        claimed = create_owned_step(self.store, "claimed", role="agent")
        got = self.store.claim_ready("agent")
        self.assertEqual(got.id, claimed)
        rc, out, err = call(cli.cmd_dep, claimed, "--needs", blocker)
        self.assertNotEqual(rc, 0)
        self.assertIn(claimed, err)
        self.assertIn(got.claimed_by, err)
        self.assertEqual(self.store._deps.get(claimed), set())

    def test_remove_still_succeeds_on_a_claimed_target(self):
        blocker = create_owned_step(self.store, "blocker", role=None)
        claimed = create_owned_step(self.store, "claimed", role="agent")
        self.store.dep_add(claimed, blocker)
        self.store.claim_ready("agent")
        rc, out, err = call(cli.cmd_dep, claimed, "--remove", blocker)
        self.assertEqual(rc, 0)
        self.assertEqual(self.store._deps.get(claimed), set())

    def test_add_succeeds_when_target_is_an_item_not_a_step(self):
        a = self.store.create_item("a", "a description")
        b = self.store.create_item("b", "a description")
        rc, out, err = call(cli.cmd_dep, a, "--needs", b)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store._deps.get(a), {b})

    def test_add_succeeds_on_a_target_claimed_in_the_past_but_now_closed(self):
        blocker = create_owned_step(self.store, "blocker", role=None)
        closed = create_owned_step(self.store, "closed", role="agent")
        got = self.store.claim_ready("agent")
        self.assertEqual(got.id, closed)
        self.store.close(closed, "done")
        rc, out, err = call(cli.cmd_dep, closed, "--needs", blocker)
        self.assertEqual(rc, 0)
        self.assertEqual(self.store._deps.get(closed), {blocker})


if __name__ == "__main__":
    unittest.main()
