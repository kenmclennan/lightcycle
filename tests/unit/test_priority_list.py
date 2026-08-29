import unittest

from lightcycle.adapters.tui.priority_list import _project, _queued_row, assemble_rows
from tests.support.fake_store import FakeStore


class TestProject(unittest.TestCase):
    def test_resolves_via_parent_items_repo_artifact(self):
        store = FakeStore()
        item = store.create_item("story")
        store.add_artifact(item, "repo", "lightcycle")
        step = store.create_step("build", step="build", role="coder", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")

    def test_blank_when_parent_item_has_no_repo_artifact(self):
        store = FakeStore()
        item = store.create_item("story")
        step = store.create_step("build", step="build", role="coder", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "")

    def test_resolves_via_own_id_when_no_parent(self):
        store = FakeStore()
        step = store.create_step("build", step="build", role="coder")
        store.add_artifact(step, "repo", "lightcycle")
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")

    def test_derives_the_short_label_from_a_slash_qualified_repo_artifact(self):
        store = FakeStore()
        item = store.create_item("story")
        store.add_artifact(item, "repo", "kenmclennan/lightcycle")
        step = store.create_step("build", step="build", role="coder", parent=item)
        node = store.get_node(step)
        self.assertEqual(_project(store, node), "lightcycle")


class TestQueuedRowDependencyTieBreak(unittest.TestCase):
    def test_shows_lexicographically_lowest_blocker(self):
        store = FakeStore()
        blocker_a = store.create_step("blocker a", step="build", role="coder")
        blocker_b = store.create_step("blocker b", step="build", role="coder")
        blocked = store.create_step(
            "blocked", step="build", role="coder", deps=[blocker_a, blocker_b]
        )
        node = store.get_node(blocked)
        expected = sorted([blocker_a, blocker_b])[0]
        other = blocker_b if expected == blocker_a else blocker_a

        row = _queued_row(store, node)

        self.assertIn(expected, row.step)
        self.assertNotIn(other, row.step)


class TestAssembleRows(unittest.TestCase):
    def test_concatenates_all_three_groups_with_no_separator(self):
        self.assertEqual(assemble_rows(["a"], ["b"], ["c"]), ["a", "b", "c"])

    def test_an_empty_middle_group_contributes_nothing(self):
        self.assertEqual(assemble_rows(["a"], [], ["c"]), ["a", "c"])

    def test_a_single_non_empty_group_renders_alone(self):
        self.assertEqual(assemble_rows([], [], ["c"]), ["c"])
