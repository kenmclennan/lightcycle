import unittest

from lightcycle.application.work.current_step import current_step
from tests.support.fake_store import FakeStore


class TestCurrentStep(unittest.TestCase):
    def test_returns_the_first_non_done_child(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        done = store.create_step("spec", step="spec-writer", role="agent", parent=item)
        store.complete_node(done, "done")
        active = store.create_step("build", step="build", role="agent", parent=item)

        self.assertEqual(current_step(store, item).id, active)

    def test_returns_none_when_every_child_is_done(self):
        store = FakeStore()
        item = store.create_item("story", "a description")
        done = store.create_step("spec", step="spec-writer", role="agent", parent=item)
        store.complete_node(done, "done")

        self.assertIsNone(current_step(store, item))

    def test_returns_none_for_an_item_with_no_children(self):
        store = FakeStore()
        item = store.create_item("story", "a description")

        self.assertIsNone(current_step(store, item))
