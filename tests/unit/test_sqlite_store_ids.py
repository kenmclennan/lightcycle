import unittest

from tests.support.sqlite_store_factory import make_sqlite_store


class TestSqliteStoreIds(unittest.TestCase):
    def test_top_level_ids_are_shortcode_and_monotonic(self):
        s = make_sqlite_store(shortcode="GRID")
        a = s.create_task("a")
        b = s.create_task("b")
        self.assertEqual(a, "GRID-1")
        self.assertEqual(b, "GRID-2")

    def test_child_id_nests_under_parent(self):
        s = make_sqlite_store(shortcode="GRID")
        epic = s.create_epic("epic")
        story = s.create_story("story", epic=epic)
        child = s.create_task("child", parent=story)
        self.assertEqual(child, "%s.1" % story)

    def test_grandchild_id_nests_two_levels(self):
        s = make_sqlite_store(shortcode="GRID")
        epic = s.create_epic("epic")
        story = s.create_story("story", epic=epic)
        task = s.create_task("task", parent=story)
        self.assertEqual(story, "%s.1" % epic)
        self.assertEqual(task, "%s.1" % story)

    def test_second_child_of_same_parent_increments(self):
        s = make_sqlite_store(shortcode="GRID")
        epic = s.create_epic("epic")
        story = s.create_story("story", epic=epic)
        first = s.create_task("first", parent=story)
        second = s.create_task("second", parent=story)
        self.assertEqual(first, "%s.1" % story)
        self.assertEqual(second, "%s.2" % story)

    def test_provided_id_is_adopted_when_free(self):
        s = make_sqlite_store(shortcode="GRID")
        epic = s.create_epic("epic")
        tid = s.create_story("spec-adopted", epic=epic, id="GRID-57")
        self.assertEqual(tid, "GRID-57")

    def test_provided_id_rejected_when_taken(self):
        s = make_sqlite_store(shortcode="GRID")
        s.create_task("first", id="GRID-57")
        with self.assertRaises(ValueError):
            s.create_task("dup", id="GRID-57")


if __name__ == "__main__":
    unittest.main()
