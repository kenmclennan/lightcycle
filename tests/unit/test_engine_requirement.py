import unittest

from lightcycle.domain.workflows.engine_requirement import parse_engine_requirement, parse_version
from lightcycle.domain.workflows.source import parse_source_manifest


class TestEngineRequirement(unittest.TestCase):
    def test_minimum_and_exclusive_maximum_bounds(self):
        req = parse_engine_requirement(">=0.6.318,<0.7.0")
        self.assertTrue(req.satisfied_by("0.6.318"))
        self.assertTrue(req.satisfied_by("0.6.999"))
        self.assertFalse(req.satisfied_by("0.6.317"))
        self.assertFalse(req.satisfied_by("0.7.0"))

    def test_comparison_is_numeric_not_string(self):
        req = parse_engine_requirement(">=0.6.318")
        self.assertFalse(req.satisfied_by("0.6.9"))
        self.assertTrue(req.satisfied_by("0.6.1000"))

    def test_strict_and_inclusive_operators(self):
        self.assertFalse(parse_engine_requirement(">0.6.318").satisfied_by("0.6.318"))
        self.assertTrue(parse_engine_requirement(">0.6.318").satisfied_by("0.6.319"))
        self.assertTrue(parse_engine_requirement("<=0.6.318").satisfied_by("0.6.318"))
        self.assertFalse(parse_engine_requirement("<=0.6.318").satisfied_by("0.6.319"))

    def test_whitespace_is_ignored_and_describe_normalises(self):
        req = parse_engine_requirement(" >= 0.6.318 , < 0.7.0 ")
        self.assertEqual(req.describe(), ">=0.6.318,<0.7.0")

    def test_malformed_values_raise(self):
        for bad in ("", "   ", "0.6.318", "~=0.6.318", ">=0.6", ">=a.b.c", ">=0.6.318,", 5, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                parse_engine_requirement(bad)

    def test_parse_version_rejects_non_triples(self):
        self.assertEqual(parse_version("0.6.318"), (0, 6, 318))
        with self.assertRaises(ValueError):
            parse_version("0.6")


class TestManifestRequirement(unittest.TestCase):
    def test_requirement_is_parsed_from_the_manifest(self):
        source = parse_source_manifest('contract = 1\nrequires-engine = ">=0.6.318"\n')
        self.assertTrue(source.requires_engine.satisfied_by("0.6.318"))

    def test_absent_requirement_is_none(self):
        self.assertIsNone(parse_source_manifest("contract = 1\n").requires_engine)

    def test_malformed_requirement_raises_value_error_naming_the_key(self):
        for text in ('contract = 1\nrequires-engine = ">=0.6"\n', "contract = 1\nrequires-engine = 5\n"):
            with self.assertRaises(ValueError) as ctx:
                parse_source_manifest(text)
            self.assertIn("requires-engine", str(ctx.exception))

    def test_rendered_origin_template_has_no_requirement(self):
        from lightcycle.adapters.scaffold import read_template
        from lightcycle.domain.workflows.contract import ENGINE_CONTRACT
        text = read_template("source.toml") % ("mine", ENGINE_CONTRACT, "mine")
        manifest = parse_source_manifest(text)
        self.assertEqual(manifest.contract, ENGINE_CONTRACT)
        self.assertIsNone(manifest.requires_engine)


if __name__ == "__main__":
    unittest.main()
