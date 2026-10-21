import unittest

from lightcycle.domain.guidance.detection import detect, parse_detected_by, validate_element

RULES = {
    "python": ("pyproject.toml", "setup.cfg"),
    "typescript": ("package.json+tsconfig.json",),
    "markdown": ("*.md",),
}


class TestValidateElement(unittest.TestCase):
    def test_accepts_names_globs_and_plus_joins(self):
        for ok in ("pyproject.toml", "*.md", "*.[ch]", "package.json+tsconfig.json"):
            self.assertTrue(validate_element(ok), ok)

    def test_rejects_quotes_dotfiles_paths_and_dangling_plus(self):
        for bad in ('"*.md"', ".python-version", "a/b", "a+", "+a", "a b"):
            self.assertFalse(validate_element(bad), bad)


class TestParseDetectedBy(unittest.TestCase):
    def test_valid_items_become_a_tuple(self):
        self.assertEqual(parse_detected_by(["a.toml", "*.md"]), ("a.toml", "*.md"))

    def test_none_or_an_invalid_item_is_none(self):
        self.assertIsNone(parse_detected_by(None))
        self.assertIsNone(parse_detected_by(["a.toml", '"*.md"']))

    def test_empty_list_is_valid_and_never_matches(self):
        self.assertEqual(parse_detected_by([]), ())
        self.assertEqual(detect({"x": ()}, ["a.md"]), [])


class TestDetect(unittest.TestCase):
    def test_worked_example(self):
        paths = ["pyproject.toml", "src/a.py", "docs/x.md", "package.json", "web/tsconfig.json"]
        self.assertEqual(
            detect(RULES, paths),
            [
                ("markdown", "docs/x.md"),
                ("python", "pyproject.toml"),
                ("typescript", "package.json + web/tsconfig.json"),
            ],
        )

    def test_plus_element_needs_every_part(self):
        self.assertEqual(detect(RULES, ["package.json", "src/a.ts"]), [])

    def test_first_matching_element_supplies_the_file(self):
        self.assertEqual(
            detect({"python": ("setup.cfg", "pyproject.toml")}, ["pyproject.toml", "setup.cfg"]),
            [("python", "setup.cfg")],
        )
