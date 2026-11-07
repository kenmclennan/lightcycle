import unittest

from lightcycle.frontmatter import parse_frontmatter, split_frontmatter


class TestParseFrontmatter(unittest.TestCase):
    def test_simple_key_values(self):
        m = parse_frontmatter("model: sonnet\nstep: build\n")
        self.assertEqual(m, {"model": "sonnet", "step": "build"})

    def test_nested_block(self):
        m = parse_frontmatter("model: opus\nroutes:\n  done: open-pr\n  rejected: build\n")
        self.assertEqual(m, {"model": "opus", "routes": {"done": "open-pr", "rejected": "build"}})

    def test_one_line_list(self):
        self.assertEqual(
            parse_frontmatter("detail: [pr, in:digest]\n"), {"detail": "[pr, in:digest]"})

    def test_wrapped_list_with_trailing_comma_matches_one_line(self):
        m = parse_frontmatter("detail:\n  [\n    pr,\n    in:digest,\n  ]\n")
        self.assertEqual(m, {"detail": "[pr, in:digest]"})

    def test_wrapped_list_without_trailing_comma_matches_one_line(self):
        m = parse_frontmatter("detail:\n  [\n    pr,\n    in:digest\n  ]\n")
        self.assertEqual(m, {"detail": "[pr, in:digest]"})

    def test_key_after_wrapped_list_still_parses(self):
        m = parse_frontmatter("detail:\n  [\n    pr,\n  ]\nx: y\n")
        self.assertEqual(m, {"detail": "[pr]", "x": "y"})

    def test_unclosed_list_block_stays_empty_mapping(self):
        self.assertEqual(parse_frontmatter("detail:\n  [\n    pr,\n"), {"detail": {}})

    def test_dash_item_block_stays_empty_mapping(self):
        self.assertEqual(parse_frontmatter("detail:\n  - pr\n"), {"detail": {}})

    def test_ignores_blank_and_non_kv_lines(self):
        m = parse_frontmatter("\nmodel: x\nnonsense line\n")
        self.assertEqual(m, {"model": "x"})


class TestSplitFrontmatter(unittest.TestCase):
    def test_splits_leading_block_from_body(self):
        meta, body = split_frontmatter("---\nmodel: sonnet\n---\n# Coder\n\nDo it.\n")
        self.assertEqual(meta, {"model": "sonnet"})
        self.assertEqual(body, "# Coder\n\nDo it.")

    def test_no_frontmatter_returns_empty_meta_and_full_body(self):
        meta, body = split_frontmatter("no frontmatter here")
        self.assertEqual(meta, {})
        self.assertEqual(body, "no frontmatter here")


if __name__ == "__main__":
    unittest.main()
