import json
import unittest

from lightcycle.application.work.has_feedback import has_feedback
from lightcycle.application.work.pending_reflections import item_reflection_count
from tests.support.fake_store import FakeStore


def _add_reflection(store, node_id, feedback):
    store.add_artifact(
        node_id, "reflection", json.dumps({"step": node_id, "feedback": feedback, "spec_hash": "h"})
    )


class TestHasFeedback(unittest.TestCase):
    def test_no_reflection_anywhere_is_false(self):
        s = FakeStore()
        item = s.create_item("x", "a description")
        s.create_step("build: x", step="build", role="agent", parent=item)
        self.assertFalse(has_feedback(s, s.get_node(item)))

    def test_step_level_reflection_is_true(self):
        s = FakeStore()
        item = s.create_item("x", "a description")
        k = s.create_step("build: x", step="build", role="agent", parent=item)
        _add_reflection(s, k, "fb")
        self.assertTrue(has_feedback(s, s.get_node(item)))

    def test_item_level_only_reflection_is_true(self):
        s = FakeStore()
        item = s.create_item("x", "a description")
        _add_reflection(s, item, "fb")
        self.assertTrue(has_feedback(s, s.get_node(item)))

    def test_reflection_on_a_retroed_pass_only_is_false(self):
        s = FakeStore()
        item = s.create_item("x", "a description")
        pid = s.open_pass(item)
        k = s.create_step("build: x", step="build", role="agent", parent=item)
        s.set_step_pass(k, pid)
        _add_reflection(s, k, "fb")
        s.close_pass(pid)
        s.label_add(pid, "retroed")

        self.assertFalse(has_feedback(s, s.get_node(item)))
        self.assertEqual(item_reflection_count(s, s.get_node(item)), 0)


if __name__ == "__main__":
    unittest.main()
