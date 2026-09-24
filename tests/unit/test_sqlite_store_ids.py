import unittest

from tests.support.sqlite_store_factory import make_sqlite_store
from tests.support.step_factory import create_owned_step


class TestSqliteStoreIds(unittest.TestCase):
    def test_top_level_ids_are_shortcode_and_monotonic(self):
        s = make_sqlite_store()
        a = s.create_item("a", "a description", shortcode="GRID")
        b = s.create_item("b", "a description", shortcode="GRID")
        self.assertEqual(a, "GRID-1")
        self.assertEqual(b, "GRID-2")

    def test_child_id_nests_under_parent(self):
        s = make_sqlite_store()
        item = s.create_item("item", "a description", shortcode="GRID")
        child = s.create_step(parent=item)
        self.assertEqual(child, "%s.1" % item)

    def test_second_child_of_same_parent_increments(self):
        s = make_sqlite_store()
        item = s.create_item("item", "a description", shortcode="GRID")
        first = s.create_step(parent=item)
        second = s.create_step(parent=item)
        self.assertEqual(first, "%s.1" % item)
        self.assertEqual(second, "%s.2" % item)

    def test_provided_id_is_adopted_when_free(self):
        s = make_sqlite_store()
        tid = s.create_item("spec-adopted", "a description", id="GRID-57")
        self.assertEqual(tid, "GRID-57")

    def test_provided_id_rejected_when_taken(self):
        s = make_sqlite_store()
        create_owned_step(s, "first", id="GRID-57")
        with self.assertRaises(ValueError):
            create_owned_step(s, "dup", id="GRID-57")

    def test_a_shortcodeless_top_level_create_refuses_and_does_not_advance_the_counter(self):
        s = make_sqlite_store()
        with self.assertRaises(ValueError):
            s.create_item("a", "a description")
        with self.assertRaises(ValueError):
            s.create_item("a", "a description", shortcode="")
        self.assertEqual(s.all_nodes(), [])
        self.assertEqual(s.create_item("b", "a description", shortcode="GRID"), "GRID-1")

    def test_a_step_mints_under_its_parent_on_a_config_with_no_shortcode_key(self):
        s = make_sqlite_store()
        item = s.create_item("item", "a description", shortcode="SIM")
        self.assertEqual(s.create_step(parent=item), "SIM-1.1")


if __name__ == "__main__":
    unittest.main()
