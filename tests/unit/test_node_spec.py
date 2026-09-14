import unittest

from lightcycle.domain.work import NodeSpec


class TestNodeSpec(unittest.TestCase):
    def test_defaults_are_empty(self):
        spec = NodeSpec()
        self.assertEqual(spec.deps, ())
        self.assertIsNone(spec.step)
        self.assertIsNone(spec.parent)

    def test_as_kwargs_names_every_create_task_arg(self):
        spec = NodeSpec(
            step="review",
            role="agent",
            parent="s-1",
            deps=("t-1", "t-2"),
        )
        self.assertEqual(
            spec.as_kwargs(),
            {
                "step": "review",
                "role": "agent",
                "parent": "s-1",
                "deps": ["t-1", "t-2"],
            },
        )

    def test_is_frozen(self):
        spec = NodeSpec(step="x")
        with self.assertRaises(Exception):
            spec.step = "y"


if __name__ == "__main__":
    unittest.main()
