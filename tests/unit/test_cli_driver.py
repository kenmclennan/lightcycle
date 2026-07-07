import unittest

from lightcycle.cli import _compose_driver


class TestComposeDriver(unittest.TestCase):
    def test_no_skills_returns_base_unchanged(self):
        self.assertEqual(_compose_driver("BASE", []), "BASE")

    def test_appends_each_skill_labelled_by_step(self):
        out = _compose_driver("BASE", [("review-plan", "REVIEW BODY"), ("cleanup", "CLEAN BODY")])
        self.assertIn("BASE", out)
        for marker in ("## review-plan", "REVIEW BODY", "## cleanup", "CLEAN BODY"):
            self.assertIn(marker, out)
        self.assertLess(out.index("BASE"), out.index("review-plan"))


if __name__ == "__main__":
    unittest.main()
