import unittest

from lightcycle.domain.work import Artifact, default_kind_for


class TestArtifact(unittest.TestCase):
    def test_from_dict_as_dict_round_trip_with_label(self):
        d = {"type": "pr", "value": "https://gh/9", "label": "PR 9"}
        self.assertEqual(Artifact.from_dict(d).as_dict(), d)

    def test_as_dict_omits_absent_label(self):
        self.assertEqual(
            Artifact(type="spec", value="s.md").as_dict(), {"type": "spec", "value": "s.md"}
        )

    def test_attribute_access(self):
        a = Artifact.from_dict({"type": "branch", "value": "feat/x"})
        self.assertEqual(a.type, "branch")
        self.assertEqual(a.value, "feat/x")
        self.assertIsNone(a.label)

    def test_internal_defaults_false_and_kind_defaults_none(self):
        a = Artifact(type="pr", value="x")
        self.assertFalse(a.internal)
        self.assertIsNone(a.kind)

    def test_explicit_kind_round_trips_through_as_dict_from_dict(self):
        d = {"type": "pr", "value": "x", "kind": "something-explicit"}
        self.assertEqual(Artifact.from_dict(d).as_dict(), d)

    def test_internal_round_trips_through_as_dict_from_dict(self):
        d = {"type": "pr", "value": "x", "internal": True}
        self.assertEqual(Artifact.from_dict(d).as_dict(), d)


class TestDefaultKindFor(unittest.TestCase):
    def test_pr_defaults_to_url(self):
        self.assertEqual(default_kind_for("pr"), "url")

    def test_spec_and_brief_default_to_filepath(self):
        self.assertEqual(default_kind_for("spec"), "filepath")
        self.assertEqual(default_kind_for("brief"), "filepath")

    def test_repo_and_branch_default_to_text(self):
        self.assertEqual(default_kind_for("repo"), "text")
        self.assertEqual(default_kind_for("branch"), "text")

    def test_unlisted_type_defaults_to_text(self):
        self.assertEqual(default_kind_for("resolves"), "text")


if __name__ == "__main__":
    unittest.main()
