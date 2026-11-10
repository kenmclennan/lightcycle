import unittest

from lightcycle.application.work.gate_hold import GateHold
from tests.support.fake_store import FakeStore


class TestGateHold(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        item = self.store.create_item("f", "d")
        self.step = self.store.create_step(stage="gate", role="human", item=item)
        self.hold = GateHold(self.store)

    def _node(self):
        return self.store.get_node(self.step)

    def test_place_and_read_the_note(self):
        self.hold.place(self.step, "waiting on the stack")

        self.assertEqual(self.hold.note_of(self.step), "waiting on the stack")
        self.assertTrue(self.hold.is_held(self.step))

    def test_unheld_step_has_no_note(self):
        self.assertIsNone(self.hold.note_of(self.step))
        self.assertFalse(self.hold.is_held(self.step))

    def test_blank_note_reads_as_none(self):
        self.hold.place(self.step, "  ")

        self.assertIsNone(self.hold.note_of(self.step))

    def test_observe_writes_once_per_distinct_text(self):
        self.hold.observe(self._node(), "PR merged (would complete the gate)")
        first = self._node().notes
        self.hold.observe(self._node(), "PR merged (would complete the gate)")

        self.assertEqual(self._node().notes, first)
        self.assertEqual(first.count("held: PR merged"), 1)

        self.hold.observe(self._node(), "PR head moved (would route to x)")

        self.assertEqual(len(self._node().notes.splitlines()), 2)

    def test_lift_removes_the_marker_and_every_held_line(self):
        self.hold.place(self.step, "why")
        self.store.note_condition(self.step, "unrelated condition")
        self.hold.observe(self._node(), "PR merged (would complete the gate)")

        self.hold.lift(self.step)

        self.assertFalse(self.hold.is_held(self.step))
        self.assertNotIn("held:", self._node().notes)
        self.assertIn("unrelated condition", self._node().notes)
