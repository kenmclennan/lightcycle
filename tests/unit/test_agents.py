import unittest

from grid.core.agents import parse_frontmatter, split_frontmatter


class TestParseFrontmatter(unittest.TestCase):
    def test_simple_key_values(self):
        m = parse_frontmatter("model: sonnet\nstep: build\n")
        self.assertEqual(m, {"model": "sonnet", "step": "build"})

    def test_one_level_nested_block(self):
        m = parse_frontmatter("model: opus\nroutes:\n  done: open-pr\n  rejected: build\n")
        self.assertEqual(m["model"], "opus")
        self.assertEqual(m["routes"], {"done": "open-pr", "rejected": "build"})

    def test_blank_and_non_kv_lines_ignored(self):
        m = parse_frontmatter("\nmodel: x\nnonsense line\n")
        self.assertEqual(m, {"model": "x"})


class TestSplitFrontmatter(unittest.TestCase):
    def test_strips_fenced_block_and_returns_body(self):
        meta, body = split_frontmatter("---\nmodel: sonnet\n---\n# Coder\n\nDo it.\n")
        self.assertEqual(meta["model"], "sonnet")
        self.assertTrue(body.startswith("# Coder"))
        self.assertNotIn("model:", body)

    def test_no_frontmatter_returns_empty_meta_and_full_text(self):
        meta, body = split_frontmatter("no frontmatter here")
        self.assertEqual(meta, {})
        self.assertEqual(body, "no frontmatter here")


if __name__ == "__main__":
    unittest.main()
