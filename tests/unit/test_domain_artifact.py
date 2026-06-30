import unittest

from the_grid.domain.artifact import Artifact


class TestArtifact(unittest.TestCase):
    def test_from_dict_as_dict_round_trip_with_label(self):
        d = {"type": "pr", "value": "https://gh/9", "label": "PR 9"}
        self.assertEqual(Artifact.from_dict(d).as_dict(), d)

    def test_as_dict_omits_absent_label(self):
        self.assertEqual(Artifact(type="spec", value="s.md").as_dict(),
                         {"type": "spec", "value": "s.md"})

    def test_attribute_access(self):
        a = Artifact.from_dict({"type": "branch", "value": "feat/x"})
        self.assertEqual(a.type, "branch")
        self.assertEqual(a.value, "feat/x")
        self.assertIsNone(a.label)


if __name__ == "__main__":
    unittest.main()
