import unittest

from lightcycle.domain.work import Artifact, Item


class TestItem(unittest.TestCase):
    def test_repo_from_artifact(self):
        s = Item("s-1", (Artifact("spec", "x.md"), Artifact("repo", "app")))
        self.assertEqual(s.repo(), "app")

    def test_repo_absent_is_none(self):
        self.assertIsNone(Item("s-1", (Artifact("spec", "x.md"),)).repo())

    def test_artifact_of(self):
        s = Item("s-1", (Artifact("pr", "http://x"),))
        self.assertEqual(s.artifact_of("pr"), "http://x")
        self.assertIsNone(s.artifact_of("spec"))

    def test_artifact_of_ignores_label_when_none_requested(self):
        s = Item("s-1", (Artifact("branch", "feat/spec-x", label="spec"),))
        self.assertEqual(s.artifact_of("branch"), "feat/spec-x")

    def test_artifact_of_prefers_exact_label_match(self):
        s = Item("s-1", (
            Artifact("pr", "http://spec", label="spec"),
            Artifact("pr", "http://code", label="code"),
        ))
        self.assertEqual(s.artifact_of("pr", label="code"), "http://code")
        self.assertEqual(s.artifact_of("pr", label="spec"), "http://spec")

    def test_artifact_of_falls_back_to_unlabelled_when_label_requested_but_absent(self):
        s = Item("s-1", (Artifact("branch", "feat/legacy"),))
        self.assertEqual(s.artifact_of("branch", label="code"), "feat/legacy")

    def test_artifact_of_label_requested_and_only_a_different_label_present(self):
        s = Item("s-1", (Artifact("branch", "feat/spec-x", label="spec"),))
        self.assertIsNone(s.artifact_of("branch", label="code"))

    def test_present_types(self):
        s = Item("s-1", (Artifact("spec", "x"), Artifact("repo", "app")))
        self.assertEqual(s.present_types(), {"spec", "repo"})


if __name__ == "__main__":
    unittest.main()
