import unittest

from tests.support.fake_store import FakeStore


class TestItemState(unittest.TestCase):
    def test_new_item_is_a_todo(self):
        s = FakeStore()
        tid = s.create_item("capture me")
        node = s.get_node(tid)
        self.assertEqual(node.type, "item")
        self.assertEqual(node.state, "backlogged")

    def test_item_can_be_created_without_a_theme(self):
        s = FakeStore()
        tid = s.create_item("un-themed")
        self.assertIsNone(s.get_node(tid).theme)

    def test_item_can_be_created_under_a_theme(self):
        s = FakeStore()
        theme = s.create_theme("focus")
        tid = s.create_item("themed", theme=theme)
        node = s.get_node(tid)
        self.assertEqual(node.theme, theme)
        self.assertEqual(node.state, "backlogged")


if __name__ == "__main__":
    unittest.main()
