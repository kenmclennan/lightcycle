import unittest

from lightcycle.application.workflows.pinned import pinned_shas
from tests.support.sqlite_store_factory import make_sqlite_store

PIN = "acme/spec-driven@abc123"


class TestPinnedShas(unittest.TestCase):
    def setUp(self):
        self.store = make_sqlite_store()

    def test_collects_the_pin_of_an_item_that_has_a_live_step(self):
        item = self.store.create_item("build the thing", "a description", workflow=PIN)
        self.store.create_step("write the code", step="write-code", role="agent", parent=item)
        self.assertEqual({"abc123"}, pinned_shas(self.store, "acme"))

    def test_ignores_an_origin_it_was_not_asked_about(self):
        self.store.create_item("build the thing", "a description", workflow=PIN)
        self.assertEqual(set(), pinned_shas(self.store, "other"))

    def test_an_item_with_no_workflow_pins_nothing(self):
        self.store.create_item("just captured", "a description")
        self.assertEqual(set(), pinned_shas(self.store, "acme"))


if __name__ == "__main__":
    unittest.main()
