import unittest

from lightcycle.domain.work import NodeSpec


class TestNodeSpec(unittest.TestCase):
    def test_defaults_are_empty(self):
        spec = NodeSpec()
        self.assertEqual(spec.deps, ())
        self.assertIsNone(spec.stage)
        self.assertIsNone(spec.item)
        self.assertIsNone(spec.previous)

    def test_as_kwargs_names_every_create_task_arg(self):
        spec = NodeSpec(
            stage="review",
            role="agent",
            item="s-1",
            deps=("t-1", "t-2"),
            previous="t-1",
        )
        self.assertEqual(
            spec.as_kwargs(),
            {
                "stage": "review",
                "role": "agent",
                "item": "s-1",
                "deps": ["t-1", "t-2"],
                "previous": "t-1",
            },
        )

    def test_is_frozen(self):
        spec = NodeSpec(stage="x")
        with self.assertRaises(Exception):
            spec.stage = "y"


if __name__ == "__main__":
    unittest.main()
