import unittest

from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


class TestCreateOwnedStep(unittest.TestCase):
    def test_mints_an_owning_item_when_parent_omitted(self):
        s = FakeStore()
        tid = create_owned_step(s, "t")
        step = s.get_step(tid)
        item = s.get_node(step.item)
        self.assertEqual(item.title, "t")
        self.assertEqual(item.description, "an owning item")

    def test_passes_an_explicit_parent_through_unchanged(self):
        s = FakeStore()
        item = s.create_item("an item", "a description")
        tid = create_owned_step(s, "t", parent=item)
        step = s.get_step(tid)
        self.assertEqual(step.item, item)


if __name__ == "__main__":
    unittest.main()
