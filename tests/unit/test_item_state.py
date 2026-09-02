import unittest

from tests.support.fake_store import FakeStore


class TestItemState(unittest.TestCase):
    def test_new_item_is_a_todo(self):
        s = FakeStore()
        tid = s.create_item("capture me")
        node = s.get_node(tid)
        self.assertEqual(node.type, "item")
        self.assertEqual(node.state, "backlogged")

    def test_item_is_created_top_level(self):
        s = FakeStore()
        tid = s.create_item("an item")
        node = s.get_node(tid)
        self.assertIsNone(node.parent)
        self.assertEqual(node.state, "backlogged")


if __name__ == "__main__":
    unittest.main()
