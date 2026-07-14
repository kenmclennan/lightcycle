import unittest

from lightcycle.domain.workflows.source import Source, parse_source_manifest


class TestParseSourceManifest(unittest.TestCase):
    def test_full_manifest(self):
        text = 'name = "acme"\ncontract = 3\ndescription = "acme flows"\n'
        source = parse_source_manifest(text)
        self.assertEqual(source, Source(name="acme", contract=3, description="acme flows"))

    def test_description_is_optional(self):
        source = parse_source_manifest('name = "acme"\ncontract = 1\n')
        self.assertEqual(source.description, "")

    def test_name_is_optional(self):
        source = parse_source_manifest("contract = 1\n")
        self.assertIsNone(source.name)

    def test_missing_contract_raises(self):
        with self.assertRaises(ValueError):
            parse_source_manifest('name = "acme"\n')

    def test_non_integer_contract_raises(self):
        with self.assertRaises(ValueError):
            parse_source_manifest('name = "acme"\ncontract = "one"\n')

    def test_malformed_toml_raises(self):
        with self.assertRaises(ValueError):
            parse_source_manifest("name = acme = broken\n")


if __name__ == "__main__":
    unittest.main()
