import unittest

from lightcycle.domain.workflows.identity import format_pin, parse_pin


class TestPinIdentity(unittest.TestCase):
    def test_format_pin(self):
        self.assertEqual(format_pin("lightcycle", "spec-driven", "abc123"),
                         "lightcycle/spec-driven@abc123")

    def test_parse_pin_roundtrip(self):
        self.assertEqual(parse_pin("lightcycle/spec-driven@abc123"),
                         ("lightcycle", "spec-driven", "abc123"))

    def test_bare_name_is_not_a_pin(self):
        self.assertIsNone(parse_pin("standard"))

    def test_selector_without_sha_is_not_a_pin(self):
        self.assertIsNone(parse_pin("lightcycle/spec-driven"))

    def test_missing_origin_is_not_a_pin(self):
        self.assertIsNone(parse_pin("spec-driven@abc123"))

    def test_empty_is_not_a_pin(self):
        self.assertIsNone(parse_pin(""))
        self.assertIsNone(parse_pin(None))


if __name__ == "__main__":
    unittest.main()
