import unittest

from lightcycle.domain.workspace import Branch, Worktree


class TestBranch(unittest.TestCase):
    def test_for_feature_default_prefix(self):
        self.assertEqual(
            Branch.for_feature("GRID-001 Repo Validation").name, "feat/grid-001-repo-validation"
        )

    def test_for_feature_custom_prefix(self):
        self.assertEqual(Branch.for_feature("My Feature", "wip").name, "wip/my-feature")

    def test_for_feature_slugifies(self):
        self.assertEqual(Branch.for_feature("  Hello, World!  ").name, "feat/hello-world")
        self.assertEqual(Branch.for_feature("a__b--c").name, "feat/a-b-c")
        self.assertEqual(
            Branch.for_feature("GRID-001-repo-validation").name, "feat/grid-001-repo-validation"
        )


class TestWorktree(unittest.TestCase):
    def test_path_in(self):
        self.assertEqual(Worktree("s-9").path_in("/root/.worktrees"), "/root/.worktrees/s-9")

    def test_transient_lock_errors_are_contention(self):
        self.assertTrue(Worktree.is_lock_contention("fatal: could not lock working tree"))
        self.assertTrue(
            Worktree.is_lock_contention(
                "Unable to create '/r/.git/worktrees/x/index.lock': File exists"
            )
        )
        self.assertTrue(Worktree.is_lock_contention("fatal: 'x' is already locked"))

    def test_real_errors_are_not_contention(self):
        self.assertFalse(Worktree.is_lock_contention("fatal: invalid reference: origin/main"))
        self.assertFalse(Worktree.is_lock_contention(""))
        self.assertFalse(Worktree.is_lock_contention(None))


if __name__ == "__main__":
    unittest.main()
