import unittest

from lightcycle.domain.work import format_facets, parse_facets, unformat_facets


class TestParseFacets(unittest.TestCase):
    def test_empty_string_is_no_facets(self):
        self.assertEqual(parse_facets(""), ())

    def test_accepts_kebab_case_names(self):
        self.assertEqual(parse_facets("kotlin"), ("kotlin",))
        self.assertEqual(parse_facets("kotlin,spring-boot"), ("kotlin", "spring-boot"))
        self.assertEqual(parse_facets("c4"), ("c4",))

    def test_rejects_non_kebab_names_naming_the_token(self):
        for bad, shown in (
            ("Kotlin", "'Kotlin'"), ("a_b", "'a_b'"), ("a, b", "' b'"),
            ("a,,b", "''"), ("-a", "'-a'"), ("a--b", "'a--b'"),
        ):
            with self.assertRaises(ValueError) as ctx:
                parse_facets(bad)
            self.assertIn("invalid facet %s" % shown, str(ctx.exception))
            self.assertIn("lowercase kebab-case", str(ctx.exception))

    def test_keeps_given_order_and_drops_a_repeat(self):
        self.assertEqual(parse_facets("b,a,b,c"), ("b", "a", "c"))


class TestFormatFacets(unittest.TestCase):
    def test_round_trips(self):
        for facets in ((), ("a",), ("kotlin", "spring-boot")):
            self.assertEqual(unformat_facets(format_facets(facets)), facets)

    def test_empty_text_is_no_facets(self):
        self.assertEqual(unformat_facets(""), ())
