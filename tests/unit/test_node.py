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


class TestNodeAsDictWorkflow(unittest.TestCase):
    def test_unset_workflow_is_an_explicit_null_not_a_missing_key(self):
        out = Node(id="x").as_dict()
        self.assertIn("workflow", out)
        self.assertIsNone(out["workflow"])

    def test_set_workflow_round_trips_as_the_pin(self):
        out = Node(id="x", workflow="lightcycle/solo@abc123").as_dict()
        self.assertEqual(out["workflow"], "lightcycle/solo@abc123")


if __name__ == "__main__":
    unittest.main()
