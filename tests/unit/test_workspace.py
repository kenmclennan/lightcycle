import unittest

from the_grid.core.workspace import branch_for, story_repo, worktree_path


class TestWorkspace(unittest.TestCase):
    def test_branch_for(self):
        self.assertEqual(branch_for("s-9"), "grid/s-9")

    def test_worktree_path(self):
        self.assertEqual(worktree_path("/root/.worktrees", "s-9"), "/root/.worktrees/s-9")

    def test_story_repo_from_artifact(self):
        arts = [{"type": "spec", "value": "x.md"}, {"type": "repo", "value": "app"}]
        self.assertEqual(story_repo(arts, "engine"), "app")

    def test_story_repo_defaults(self):
        self.assertEqual(story_repo([{"type": "spec", "value": "x.md"}], "engine"), "engine")


if __name__ == "__main__":
    unittest.main()
