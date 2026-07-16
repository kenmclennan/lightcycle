import json
import unittest

from lightcycle.application.work.pending_reflections import (
    item_reflection_count,
    pending_reflection_count,
)
from tests.support.fake_store import FakeStore


def _add_reflection(store, node_id, feedback):
    store.add_artifact(
        node_id, "reflection", json.dumps({"step": node_id, "feedback": feedback, "spec_hash": "h"})
    )


def _close_item(store, title, per_step_reflections=(0,)):
    eid = store.create_item(title)
    store.close(eid, "done")
    for i, count in enumerate(per_step_reflections):
        k = store.create_step("build: %d" % i, step="build", role="coder", parent=eid)
        store.close(k, "done")
        for j in range(count):
            _add_reflection(store, k, "fb %d.%d" % (i, j))
    return eid


class TestItemReflectionCount(unittest.TestCase):
    def test_item_with_no_reflection_is_zero(self):
        s = FakeStore()
        item = _close_item(s, "x", per_step_reflections=(0,))
        self.assertEqual(item_reflection_count(s, s.get_node(item)), 0)

    def test_item_with_n_reflections_on_a_single_step(self):
        s = FakeStore()
        item = _close_item(s, "x", per_step_reflections=(4,))
        self.assertEqual(item_reflection_count(s, s.get_node(item)), 4)

    def test_item_with_reflections_split_across_two_steps_sums(self):
        s = FakeStore()
        item = _close_item(s, "x", per_step_reflections=(2, 3))
        self.assertEqual(item_reflection_count(s, s.get_node(item)), 5)


class TestPendingReflectionCount(unittest.TestCase):
    def test_sums_across_multiple_pending_items(self):
        s = FakeStore()
        _close_item(s, "a", per_step_reflections=(3,))
        _close_item(s, "b", per_step_reflections=(2,))
        self.assertEqual(pending_reflection_count(s), 5)

    def test_excludes_retroed_items(self):
        s = FakeStore()
        _close_item(s, "a", per_step_reflections=(3,))
        retroed = _close_item(s, "b", per_step_reflections=(2,))
        s.label_add(retroed, "retroed")
        self.assertEqual(pending_reflection_count(s), 3)

    def test_excludes_retro_origin_items(self):
        s = FakeStore()
        _close_item(s, "a", per_step_reflections=(3,))
        origin = _close_item(s, "b", per_step_reflections=(2,))
        s.label_add(origin, "retro-origin")
        self.assertEqual(pending_reflection_count(s), 3)


if __name__ == "__main__":
    unittest.main()
