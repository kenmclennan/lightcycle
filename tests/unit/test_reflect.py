import unittest

from the_grid.core.reflect import build_reflection, build_sections, spec_hash_from_bytes


class TestBuildSections(unittest.TestCase):
    def test_used(self):
        s = build_sections(used="Summary,Scope")
        self.assertEqual(s["Summary"], "used")
        self.assertEqual(s["Scope"], "used")

    def test_skipped(self):
        s = build_sections(skipped="Risks")
        self.assertEqual(s["Risks"], "skipped")

    def test_guess(self):
        s = build_sections(guess="Decisions")
        self.assertEqual(s["Decisions"], "guess")

    def test_last_wins_on_collision(self):
        s = build_sections(used="X", skipped="X")
        self.assertEqual(s["X"], "skipped")

    def test_strips_whitespace(self):
        s = build_sections(used=" Summary , Scope ")
        self.assertIn("Summary", s)
        self.assertIn("Scope", s)

    def test_empty_strings_produce_empty_dict(self):
        self.assertEqual(build_sections(), {})

    def test_empty_csv_entry_skipped(self):
        s = build_sections(used="A,,B")
        self.assertNotIn("", s)
        self.assertIn("A", s)
        self.assertIn("B", s)


class TestSpecHashFromBytes(unittest.TestCase):
    def test_returns_8_hex_chars(self):
        h = spec_hash_from_bytes(b"# spec\ncontent")
        self.assertEqual(len(h), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_deterministic(self):
        data = b"hello world"
        self.assertEqual(spec_hash_from_bytes(data), spec_hash_from_bytes(data))

    def test_different_for_different_input(self):
        self.assertNotEqual(spec_hash_from_bytes(b"a"), spec_hash_from_bytes(b"b"))


class TestBuildReflection(unittest.TestCase):
    def test_full_reflection(self):
        r = build_reflection(
            "task-1",
            used="Summary,Scope",
            skipped="Risks",
            guess="Decisions",
            missing=["acceptance criteria"],
            noise=["Out of scope"],
            spec_hash="abc12345",
        )
        self.assertEqual(r["task"], "task-1")
        self.assertEqual(r["sections"]["Summary"], "used")
        self.assertEqual(r["sections"]["Scope"], "used")
        self.assertEqual(r["sections"]["Risks"], "skipped")
        self.assertEqual(r["sections"]["Decisions"], "guess")
        self.assertEqual(r["missing"], ["acceptance criteria"])
        self.assertEqual(r["noise"], ["Out of scope"])
        self.assertEqual(r["spec_hash"], "abc12345")

    def test_defaults(self):
        r = build_reflection("task-1")
        self.assertEqual(r["sections"], {})
        self.assertEqual(r["missing"], [])
        self.assertEqual(r["noise"], [])
        self.assertEqual(r["friction"], [])
        self.assertEqual(r["spec_hash"], "unknown")

    def test_json_shape_stable(self):
        r = build_reflection("t", used="Summary", missing=["x"], noise=["y"], spec_hash="aabbccdd")
        self.assertIn("task", r)
        self.assertIn("sections", r)
        self.assertIn("missing", r)
        self.assertIn("noise", r)
        self.assertIn("friction", r)
        self.assertIn("spec_hash", r)

    def test_friction_single_entry(self):
        r = build_reflection("task-1", friction=["pytest not found"])
        self.assertEqual(r["friction"], ["pytest not found"])

    def test_friction_multiple_entries(self):
        r = build_reflection("task-1", friction=["pytest not found", "missing env var"])
        self.assertEqual(r["friction"], ["pytest not found", "missing env var"])

    def test_friction_independent_of_missing_and_noise(self):
        r = build_reflection(
            "task-1",
            missing=["needed context"],
            noise=["boilerplate"],
            friction=["tool crashed"],
        )
        self.assertEqual(r["missing"], ["needed context"])
        self.assertEqual(r["noise"], ["boilerplate"])
        self.assertEqual(r["friction"], ["tool crashed"])


if __name__ == "__main__":
    unittest.main()
