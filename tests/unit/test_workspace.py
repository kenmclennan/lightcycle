import unittest

from the_grid.domain.artifact import Artifact
from the_grid.domain.workspace import (branch_for, is_worktree_lock_error, slugify,
                                story_repo, worktree_path)


class TestWorkspace(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("GRID-001-repo-validation"), "grid-001-repo-validation")
        self.assertEqual(slugify("  Hello, World!  "), "hello-world")
        self.assertEqual(slugify("a__b--c"), "a-b-c")

    def test_branch_for_default_prefix(self):
        self.assertEqual(branch_for("GRID-001 Repo Validation"), "feat/grid-001-repo-validation")

    def test_branch_for_custom_prefix(self):
        self.assertEqual(branch_for("My Feature", "wip"), "wip/my-feature")

    def test_worktree_path(self):
        self.assertEqual(worktree_path("/root/.worktrees", "s-9"), "/root/.worktrees/s-9")

    def test_story_repo_from_artifact(self):
        arts = [Artifact(type="spec", value="x.md"), Artifact(type="repo", value="app")]
        self.assertEqual(story_repo(arts, "engine"), "app")

    def test_story_repo_defaults(self):
        self.assertEqual(story_repo([Artifact(type="spec", value="x.md")], "engine"), "engine")


class TestWorktreeLockError(unittest.TestCase):
    def test_transient_lock_errors_retried(self):
        self.assertTrue(is_worktree_lock_error("fatal: could not lock working tree"))
        self.assertTrue(is_worktree_lock_error(
            "Unable to create '/r/.git/worktrees/x/index.lock': File exists"))
        self.assertTrue(is_worktree_lock_error("fatal: 'x' is already locked"))

    def test_real_errors_not_retried(self):
        self.assertFalse(is_worktree_lock_error("fatal: invalid reference: origin/main"))
        self.assertFalse(is_worktree_lock_error(""))
        self.assertFalse(is_worktree_lock_error(None))


if __name__ == "__main__":
    unittest.main()
