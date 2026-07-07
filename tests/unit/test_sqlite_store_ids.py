import unittest

from tests.support.sqlite_store_factory import make_sqlite_store


class TestSqliteStoreIds(unittest.TestCase):
    def test_top_level_ids_are_shortcode_and_monotonic(self):
        s = make_sqlite_store(shortcode="GRID")
        a = s.create_step("a")
        b = s.create_step("b")
        self.assertEqual(a, "GRID-1")
        self.assertEqual(b, "GRID-2")

    def test_child_id_nests_under_parent(self):
        s = make_sqlite_store(shortcode="GRID")
        theme = s.create_theme("theme")
        item = s.create_item("item", theme=theme)
        child = s.create_step("child", parent=item)
        self.assertEqual(child, "%s.1" % item)

    def test_grandchild_id_nests_two_levels(self):
        s = make_sqlite_store(shortcode="GRID")
        theme = s.create_theme("theme")
        item = s.create_item("item", theme=theme)
        step = s.create_step("step", parent=item)
        self.assertEqual(item, "%s.1" % theme)
        self.assertEqual(step, "%s.1" % item)

    def test_second_child_of_same_parent_increments(self):
        s = make_sqlite_store(shortcode="GRID")
        theme = s.create_theme("theme")
        item = s.create_item("item", theme=theme)
        first = s.create_step("first", parent=item)
        second = s.create_step("second", parent=item)
        self.assertEqual(first, "%s.1" % item)
        self.assertEqual(second, "%s.2" % item)

    def test_provided_id_is_adopted_when_free(self):
        s = make_sqlite_store(shortcode="GRID")
        theme = s.create_theme("theme")
        tid = s.create_item("spec-adopted", theme=theme, id="GRID-57")
        self.assertEqual(tid, "GRID-57")

    def test_provided_id_rejected_when_taken(self):
        s = make_sqlite_store(shortcode="GRID")
        s.create_step("first", id="GRID-57")
        with self.assertRaises(ValueError):
            s.create_step("dup", id="GRID-57")


if __name__ == "__main__":
    unittest.main()
