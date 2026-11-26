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
        self.store.complete_node(closed, "done")
        rc, out, err = call(cli.cmd_dep, closed, "--needs", blocker)
        self.assertEqual(rc, 0)
        self.assertEqual(self.store._deps.get(closed), {blocker})


if __name__ == "__main__":
    unittest.main()


class TestCmdDepOnParkedStep(unittest.TestCase):
    def setUp(self):
        from tests.unit.test_halt_step import _OwnerFlow, _Spin
        from lightcycle.application.flow.unblock_step import UnblockStepUseCase
        from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase

        self.store = FakeStore()
        store = self.store
        self.container = FakeContainer(store)
        self.container.unblock_step_use_case = lambda: UnblockStepUseCase(
            store, _OwnerFlow(), spin_port=_Spin())
        cli.set_container(self.container)
        self.blocker = create_owned_step(store, "blocker", role="agent")
        self.blocked = create_owned_step(store, "blocked", role="agent")
        self.park = lambda: ParkStepUseCase(store).execute(
            ParkInput(step=self.blocked, observation="stuck", decision="pick one"))

    def test_dep_on_a_parked_step_clears_the_park_and_holds_it(self):
        self.park()
        rc, _out, _err = call(cli.cmd_dep, self.blocked, "--needs", self.blocker)
        node = self.store.get_node(self.blocked)
        self.assertEqual(rc, 0)
        self.assertFalse(node.park)
        self.assertNotIn("BLOCKED:", node.notes or "")
        self.assertIn("PARK RESOLVED", node.notes or "")
        self.assertEqual(node.role, "agent")
        self.assertEqual(self.store._deps.get(self.blocked), {self.blocker})
        self.assertIsNone(self.store.claim_ready("agent", "w1", item=node.item))

    def test_dependency_exists_before_the_park_is_cleared(self):
        self.park()
        real = self.container.unblock_step_use_case
        seen = []

        def recording():
            seen.append(set(self.store._deps.get(self.blocked, set())))
            return real()

        self.container.unblock_step_use_case = recording
        call(cli.cmd_dep, self.blocked, "--needs", self.blocker)
        self.assertEqual(seen, [{self.blocker}])

    def test_step_runs_with_no_park_once_the_dependency_closes(self):
        self.park()
        call(cli.cmd_dep, self.blocked, "--needs", self.blocker)
        self.store.complete_node(self.blocker, "done")
        claimed = self.store.claim_ready("agent", "w1", item=self.store.get_node(self.blocked).item)
        node = self.store.get_node(claimed.id)
        self.assertEqual(claimed.id, self.blocked)
        self.assertFalse(node.park)
        self.assertNotIn("BLOCKED:", node.notes or "")

    def test_dep_on_an_unparked_step_leaves_it_unchanged(self):
        before = self.store.get_node(self.blocked)
        rc, _out, _err = call(cli.cmd_dep, self.blocked, "--needs", self.blocker)
        after = self.store.get_node(self.blocked)
        self.assertEqual(rc, 0)
        self.assertEqual(after.notes, before.notes)
        self.assertEqual(after.role, before.role)
        self.assertFalse(after.park)
        self.assertEqual(self.store._deps.get(self.blocked), {self.blocker})
