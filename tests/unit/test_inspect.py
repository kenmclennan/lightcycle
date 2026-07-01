import unittest

from the_grid.application.inspect import ShowTask
from tests.support.fake_store import FakeStore


class TestShowTask(unittest.TestCase):
    def test_returns_task_view(self):
        s = FakeStore()
        tid = s.create_task("build: x", step="build", role="coder")
        view = ShowTask(s).execute(tid)
        self.assertEqual(view["id"], tid)
        self.assertEqual(view["title"], "build: x")
        self.assertIn("story_artifacts", view)


if __name__ == "__main__":
    unittest.main()
