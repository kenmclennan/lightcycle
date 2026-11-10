import unittest

from lightcycle import cli
from lightcycle.application.work.gate_hold import GateHold
from tests.support.fake_store import FakeStore
from tests.unit.test_cmd_close import _Container, call


class TestHeldStepRefusesTheHumanRoutes(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        cli.set_container(_Container(self.store))
        self.item = self.store.create_item("an item", "a description")
        self.gate = self.store.create_step(stage="gate", role="human", item=self.item)
        GateHold(self.store).place(self.gate, "wait for the stack")

    def _state(self):
        node = self.store.get_node(self.gate)
        return (node.state, node.outcome)

    def _refused(self, fn, *args):
        before = self._state()

        rc, out, err = call(fn, *args)

        self.assertEqual(rc, 1)
        self.assertIn("lc release %s" % self.gate, err)
        self.assertIn("wait for the stack", err)
        self.assertEqual(self._state(), before)

    def test_done_refuses(self):
        self._refused(cli.cmd_done, self.gate, "approved")

    def test_advance_refuses(self):
        self._refused(cli.cmd_advance, self.gate, "approved")

    def test_set_state_ready_refuses(self):
        self._refused(cli.cmd_set, self.gate, "--state", "ready")

    def test_set_notes_is_not_a_move_and_succeeds(self):
        rc, out, err = call(cli.cmd_set, self.gate, "--notes", "a note")

        self.assertEqual(rc, 0, err)

    def test_close_on_the_item_closes_it_and_completes_the_step(self):
        rc, out, err = call(cli.cmd_close, self.item)

        self.assertEqual(rc, 0, err)
        self.assertEqual(self.store.get_node(self.item).state, "done")
        self.assertEqual(self.store.get_node(self.gate).state, "done")

    def test_an_unheld_step_is_not_refused(self):
        GateHold(self.store).lift(self.gate)

        rc, out, err = call(cli.cmd_set, self.gate, "--notes", "x")

        self.assertEqual(rc, 0, err)
