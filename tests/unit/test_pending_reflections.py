import json
import unittest

from lightcycle.application.work.pending_reflections import (
    item_reflection_count,
    pass_reflection_count,
    pending_reflection_count,
)
from tests.support.fake_store import FakeStore


def _add_reflection(store, node_id, feedback):
    store.add_artifact(
        node_id, "reflection", json.dumps({"step": node_id, "feedback": feedback, "spec_hash": "h"})
    )


def _close_item(store, title, per_step_reflections=(0,)):
    eid = store.create_item(title, "a description")
    store.complete_node(eid, "done")
    for i, count in enumerate(per_step_reflections):
        k = store.create_step("build: %d" % i, step="build", role="agent", parent=eid)
        store.complete_node(k, "done")
        for j in range(count):
            _add_reflection(store, k, "fb %d.%d" % (i, j))
    return eid


def _open_item_with_closed_pass(store, title, per_step_reflections=(0,)):
    eid = store.create_item(title, "a description")
    pid = store.open_pass(eid)
    for i, count in enumerate(per_step_reflections):
        k = store.create_step("build: %d" % i, step="build", role="agent", parent=eid)
        store.set_step_pass(k, pid)
        store.complete_node(k, "done")
        for j in range(count):
            _add_reflection(store, k, "fb %d.%d" % (i, j))
    store.close_pass(pid)
    return eid, pid


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


class TestPassReflectionCount(unittest.TestCase):
    def test_sums_reflections_across_steps_assigned_to_one_pass(self):
        s = FakeStore()
        item, pid = _open_item_with_closed_pass(s, "x", per_step_reflections=(2, 3))
        self.assertEqual(pass_reflection_count(s, s.get_pass(pid)), 5)

    def test_ignores_steps_assigned_to_a_different_pass_on_the_same_item(self):
        s = FakeStore()
        item = s.create_item("x", "a description")
        pid1 = s.open_pass(item)
        k1 = s.create_step("build: 0", step="build", role="agent", parent=item)
        s.set_step_pass(k1, pid1)
        s.complete_node(k1, "done")
        _add_reflection(s, k1, "fb 1")
        s.close_pass(pid1)
        pid2 = s.open_pass(item)
        k2 = s.create_step("build: 1", step="build", role="agent", parent=item)
        s.set_step_pass(k2, pid2)
        s.complete_node(k2, "done")
        _add_reflection(s, k2, "fb 2")
        _add_reflection(s, k2, "fb 3")
        s.close_pass(pid2)
        self.assertEqual(pass_reflection_count(s, s.get_pass(pid1)), 1)
        self.assertEqual(pass_reflection_count(s, s.get_pass(pid2)), 2)


class TestPendingReflectionCountAcrossOpenItems(unittest.TestCase):
    def test_includes_reflections_from_a_closed_pass_of_a_still_open_item(self):
        s = FakeStore()
        _open_item_with_closed_pass(s, "x", per_step_reflections=(3,))
        self.assertEqual(pending_reflection_count(s), 3)

    def test_excludes_a_closed_pass_already_labelled_retroed(self):
        s = FakeStore()
        item, pid = _open_item_with_closed_pass(s, "x", per_step_reflections=(3,))
        s.label_add(pid, "retroed")
        self.assertEqual(pending_reflection_count(s), 0)

    def test_item_with_two_closed_passes_only_counts_the_unretroed_one_once_item_closes(self):
        s = FakeStore()
        item = s.create_item("x", "a description")
        pid1 = s.open_pass(item)
        k1 = s.create_step("build: 0", step="build", role="agent", parent=item)
        s.set_step_pass(k1, pid1)
        s.complete_node(k1, "done")
        _add_reflection(s, k1, "pass 1 feedback")
        s.close_pass(pid1)
        s.label_add(pid1, "retroed")

        pid2 = s.open_pass(item)
        k2 = s.create_step("build: 1", step="build", role="agent", parent=item)
        s.set_step_pass(k2, pid2)
        s.complete_node(k2, "done")
        _add_reflection(s, k2, "pass 2 feedback")
        s.close_pass(pid2)

        s.complete_node(item, "done")

        self.assertEqual(item_reflection_count(s, s.get_node(item)), 1)


if __name__ == "__main__":
    unittest.main()
