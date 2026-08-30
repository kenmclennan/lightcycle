import unittest

from lightcycle.domain.work import Node, State


class TestNodeSlots(unittest.TestCase):
    def test_unknown_attribute_raises_attribute_error(self):
        node = Node(id="x")
        with self.assertRaises(AttributeError):
            node.not_a_real_field = "oops"

    def test_state_can_still_be_mutated(self):
        node = Node(id="x", state=None)
        node.state = State.DONE
        self.assertEqual(node.state, State.DONE)


if __name__ == "__main__":
    unittest.main()
