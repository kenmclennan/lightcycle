import unittest

from the_grid.domain.work import TaskSpec


class TestTaskSpec(unittest.TestCase):
    def test_defaults_are_empty(self):
        spec = TaskSpec(title="build: x")
        self.assertEqual(spec.deps, ())
        self.assertIsNone(spec.step)
        self.assertIsNone(spec.parent)

    def test_as_kwargs_names_every_create_task_arg(self):
        spec = TaskSpec(title="review: x", step="review", role="reviewer",
                        parent="s-1", deps=("t-1", "t-2"), project="grid", goal="ship")
        self.assertEqual(spec.as_kwargs(), {
            "title": "review: x", "step": "review", "role": "reviewer",
            "parent": "s-1", "deps": ["t-1", "t-2"], "project": "grid", "goal": "ship",
        })

    def test_is_frozen(self):
        spec = TaskSpec(title="x")
        with self.assertRaises(Exception):
            spec.title = "y"


if __name__ == "__main__":
    unittest.main()
