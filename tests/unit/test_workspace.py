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

    def test_for_feature_with_ident_short_title(self):
        self.assertEqual(
            Branch.for_feature("My Feature", ident="LC-1").name, "feat/LC-1-my-feature"
        )

    def test_for_feature_with_ident_custom_prefix(self):
        self.assertEqual(
            Branch.for_feature("My Feature", "wip", ident="LC-4").name, "wip/LC-4-my-feature"
        )

    def test_for_feature_with_ident_is_not_slugified(self):
        self.assertEqual(Branch.for_feature("thing", ident="LC-5.1").name, "feat/LC-5.1-thing")

    def test_for_feature_with_ident_truncates_long_title_on_word_boundary(self):
        title = (
            "Branch name is the entire item title slugified (100+ chars); use the item id "
            "or a short truncated slug"
        )
        branch = Branch.for_feature(title, ident="LC-10")
        self.assertEqual(branch.name, "feat/LC-10-branch-name-is-the-entire-item-title")
        self.assertFalse(branch.name.endswith("-"))
        self.assertLessEqual(len(branch.name) - len("feat/LC-10-"), 40)

    def test_for_feature_with_ident_empty_or_punctuation_title(self):
        self.assertEqual(Branch.for_feature("", ident="LC-3").name, "feat/LC-3")
        self.assertEqual(Branch.for_feature("!!!", ident="LC-3").name, "feat/LC-3")


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
