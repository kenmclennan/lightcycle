import unittest

from lightcycle.domain.work import Artifact, Item


class TestItem(unittest.TestCase):
    def test_repo_from_artifact(self):
        s = Item("s-1", (Artifact("spec", "x.md"), Artifact("repo", "app")))
        self.assertEqual(s.repo(), "app")

    def test_repo_absent_is_none(self):
        self.assertIsNone(Item("s-1", (Artifact("spec", "x.md"),)).repo())

    def test_branch_from_artifact(self):
        self.assertEqual(Item("s-1", (Artifact("branch", "feat/x"),)).branch(), "feat/x")

    def test_branch_absent_is_none(self):
        self.assertIsNone(Item("s-1", ()).branch())

    def test_artifact_of(self):
        s = Item("s-1", (Artifact("pr", "http://x"),))
        self.assertEqual(s.artifact_of("pr"), "http://x")
        self.assertIsNone(s.artifact_of("spec"))

    def test_present_types(self):
        s = Item("s-1", (Artifact("spec", "x"), Artifact("repo", "app")))
        self.assertEqual(s.present_types(), {"spec", "repo"})


if __name__ == "__main__":
    unittest.main()
