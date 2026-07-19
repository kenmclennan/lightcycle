import unittest

from lightcycle.domain.health import fsck
from lightcycle.domain.work import Artifact, Node, State


def _node(id, type, parent=None, state=State.READY, artifacts=None):
    return Node(id=id, title=id, type=type, parent=parent, state=state,
                artifacts=artifacts or [])


class TestFsck(unittest.TestCase):
    def test_empty_graph_has_no_problems(self):
        self.assertEqual(fsck([]), [])

    def test_clean_graph_has_no_problems(self):
        theme = _node("t-1", "theme")
        item = _node("t-1.1", "item", parent="t-1")
        step = _node("t-1.1.1", "step", parent="t-1.1")
        self.assertEqual(fsck([theme, item, step]), [])

    def test_orphaned_node_missing_parent(self):
        step = _node("s-1", "step", parent="missing")
        problems = fsck([step])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].category, "store")
        self.assertEqual(problems[0].node_id, "s-1")
        self.assertIn("missing", problems[0].message)

    def test_open_node_under_closed_parent_is_orphaned(self):
        item = _node("i-1", "item", state=State.DONE)
        step = _node("i-1.1", "step", parent="i-1", state=State.READY)
        problems = fsck([item, step])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].node_id, "i-1.1")

    def test_closed_node_under_closed_parent_is_not_orphaned(self):
        item = _node("i-1", "item", state=State.DONE)
        step = _node("i-1.1", "step", parent="i-1", state=State.DONE)
        self.assertEqual(fsck([item, step]), [])

    def test_dangling_resolves_artifact(self):
        step = _node("s-1", "step", artifacts=[Artifact(type="resolves", value="missing")])
        problems = fsck([step])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].category, "store")
        self.assertIn("resolves", problems[0].message)

    def test_dangling_filed_from_artifact(self):
        step = _node("s-1", "step", artifacts=[Artifact(type="filed-from", value="missing")])
        self.assertEqual(len(fsck([step])), 1)

    def test_dangling_watched_step_artifact(self):
        step = _node("s-1", "step", artifacts=[Artifact(type="watched-step", value="missing")])
        self.assertEqual(len(fsck([step])), 1)

    def test_resolving_artifact_pointing_at_existing_node_is_fine(self):
        other = _node("s-2", "step")
        step = _node("s-1", "step", artifacts=[Artifact(type="resolves", value="s-2")])
        self.assertEqual(fsck([step, other]), [])

    def test_other_artifact_types_are_not_checked(self):
        step = _node("s-1", "step", artifacts=[Artifact(type="spec", value="missing")])
        self.assertEqual(fsck([step]), [])

    def test_item_in_progress_with_all_steps_done_is_stuck(self):
        item = _node("i-1", "item", state=State.IN_PROGRESS)
        step = _node("i-1.1", "step", parent="i-1", state=State.DONE)
        problems = fsck([item, step])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].node_id, "i-1")
        self.assertIn("done", problems[0].message)

    def test_item_in_progress_with_one_open_step_is_not_stuck(self):
        item = _node("i-1", "item", state=State.IN_PROGRESS)
        done_step = _node("i-1.1", "step", parent="i-1", state=State.DONE)
        open_step = _node("i-1.2", "step", parent="i-1", state=State.READY)
        self.assertEqual(fsck([item, done_step, open_step]), [])

    def test_backlogged_item_with_steps_is_stuck(self):
        item = _node("i-1", "item", state=State.BACKLOGGED)
        step = _node("i-1.1", "step", parent="i-1", state=State.READY)
        problems = fsck([item, step])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].node_id, "i-1")
        self.assertIn("backlogged", problems[0].message)

    def test_backlogged_item_without_steps_is_not_stuck(self):
        item = _node("i-1", "item", state=State.BACKLOGGED)
        self.assertEqual(fsck([item]), [])


if __name__ == "__main__":
    unittest.main()
