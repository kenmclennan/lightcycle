import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from lightcycle import cli
from lightcycle.application.work.gate_hold import GateHold
from lightcycle.commands import flow as flow_cmds
from tests.support.fake_store import FakeStore


def _run(store, fn, argv):
    out, err = io.StringIO(), io.StringIO()
    container = mock.Mock()
    container.store = store
    with mock.patch.object(flow_cmds, "container", return_value=container), \
            redirect_stdout(out), redirect_stderr(err):
        rc = fn(argv)
    return rc, out.getvalue(), err.getvalue()


class TestHoldAndRelease(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item("f", "d")
        self.gate = self.store.create_step(stage="gate", role="human", item=self.item)

    def _snapshot(self):
        return {
            n.id: (n.state, n.outcome, getattr(n, "notes", None), tuple(a.type for a in self.store.item_artifacts(n.id)))
            for n in self.store.all_nodes()
        }

    def _hold(self, *argv):
        return _run(self.store, cli.cmd_hold, list(argv))

    def test_holds_by_step_id_and_leaves_the_step_otherwise_alone(self):
        before = self.store.get_node(self.gate)

        rc, out, _ = self._hold(self.gate, "--note", "wait for stack")

        after = self.store.get_node(self.gate)
        self.assertEqual(rc, 0)
        self.assertIn("held %s: wait for stack" % self.gate, out)
        self.assertEqual(GateHold(self.store).note_of(self.gate), "wait for stack")
        self.assertEqual((after.state, after.outcome, after.park), (before.state, before.outcome, before.park))
        self.assertNotEqual(self.store.get_node(self.item).state, "done")

    def test_holds_by_item_id(self):
        rc, _, _ = self._hold(self.item, "--note", "why")

        self.assertEqual(rc, 0)
        self.assertTrue(GateHold(self.store).is_held(self.gate))

    def test_missing_note_exits_two_and_touches_nothing(self):
        before = self._snapshot()

        rc, _, err = self._hold(self.gate)

        self.assertEqual(rc, 2)
        self.assertEqual(before, self._snapshot())

    def test_refuses_an_unknown_id(self):
        rc, _, err = self._hold("NOPE-1", "--note", "x")

        self.assertEqual(rc, 1)
        self.assertIn("NOPE-1", err)

    def test_refuses_an_agent_step(self):
        agent = self.store.create_step(stage="build", role="agent", item=self.item)
        before = self._snapshot()

        rc, _, err = self._hold(agent, "--note", "x")

        self.assertEqual(rc, 1)
        self.assertIn("lc set", err)
        self.assertEqual(before, self._snapshot())

    def test_refuses_a_running_step(self):
        other = self.store.create_item("g", "d")
        step = self.store.create_step(stage="build", role="agent", item=other)
        self.store.claim_ready("agent", "sp1", item=other)
        before = self._snapshot()

        rc, _, err = self._hold(step, "--note", "x")

        self.assertEqual(rc, 1)
        self.assertIn("lc halt", err)
        self.assertEqual(before, self._snapshot())

    def test_refuses_an_item_with_no_waiting_human_gate(self):
        other = self.store.create_item("g", "d")
        self.store.create_step(stage="build", role="agent", item=other)

        rc, _, err = self._hold(other, "--note", "x")

        self.assertEqual(rc, 1)
        self.assertIn("no waiting human gate", err)

    def test_refuses_an_item_with_two_gates(self):
        self.store.create_step(stage="gate2", role="human", item=self.item)
        self.store._get(self.store.children(self.item)[-1].id)["state"] = "waiting"

        rc, _, err = self._hold(self.item, "--note", "x")

        self.assertEqual(rc, 1)
        self.assertIn("give one step id", err)

    def test_refuses_an_already_held_step(self):
        self._hold(self.gate, "--note", "first")

        rc, _, err = self._hold(self.gate, "--note", "second")

        self.assertEqual(rc, 1)
        self.assertIn("already held", err)
        self.assertEqual(GateHold(self.store).note_of(self.gate), "first")

    def test_refuses_a_closed_step(self):
        self.store.complete_node(self.gate, "done")

        rc, _, err = self._hold(self.gate, "--note", "x")

        self.assertEqual(rc, 1)
        self.assertIn("closed", err)

    def test_release_lifts_the_hold_and_leaves_the_step_waiting(self):
        self._hold(self.gate, "--note", "why")
        state = self.store.get_node(self.gate).state

        rc, out, _ = _run(self.store, cli.cmd_release, [self.gate])

        self.assertEqual(rc, 0)
        self.assertIn("released %s" % self.gate, out)
        self.assertFalse(GateHold(self.store).is_held(self.gate))
        self.assertEqual(self.store.get_node(self.gate).state, state)

    def test_release_refuses_an_unheld_step(self):
        rc, _, err = _run(self.store, cli.cmd_release, [self.gate])

        self.assertEqual(rc, 1)
        self.assertIn("is not held", err)
