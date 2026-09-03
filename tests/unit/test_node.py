import unittest

from lightcycle.domain.work import State
from tests.support.factories import make_step


class TestNodeSlots(unittest.TestCase):
    def test_unknown_attribute_raises_attribute_error(self):
        node = make_step(id="x")
        with self.assertRaises(AttributeError):
            node.not_a_real_field = "oops"

    def test_state_can_still_be_mutated(self):
        node = make_step(id="x", state=None)
        node.state = State.DONE
        self.assertEqual(node.state, State.DONE)


class TestNodeAsDictWorkflow(unittest.TestCase):
    def test_unset_pass_is_an_explicit_null_not_a_missing_key(self):
        out = make_step(id="x").as_dict()
        self.assertIn("pass", out)
        self.assertIsNone(out["pass"])

    def test_set_pass_round_trips(self):
        out = make_step(id="x", pass_id="i-1.p2").as_dict()
        self.assertEqual(out["pass"], "i-1.p2")


if __name__ == "__main__":
    unittest.main()
