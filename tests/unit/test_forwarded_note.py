import unittest

from lightcycle.domain.work.forwarded_note import (
    Forwarded,
    has_forwarded_line,
    parse_forwarded,
    shim_notes,
)


class TestParseForwarded(unittest.TestCase):
    def test_empty_notes_parse_to_none(self):
        self.assertIsNone(parse_forwarded(None))
        self.assertIsNone(parse_forwarded(""))

    def test_notes_without_a_forwarded_line_parse_to_none(self):
        self.assertIsNone(parse_forwarded("just a note"))

    def test_forwarded_line_yields_stage_outcome_and_text(self):
        self.assertEqual(
            parse_forwarded("from build (done): all green\n"),
            Forwarded("build", "done", "all green"),
        )

    def test_text_stops_at_the_next_outcome_line(self):
        notes = "from build (done): first\nsecond\noutcome: x"
        self.assertEqual(parse_forwarded(notes), Forwarded("build", "done", "first\nsecond"))

    def test_only_trailing_newlines_are_stripped_from_the_text(self):
        self.assertEqual(
            parse_forwarded("from a (b): keep  \n\n"), Forwarded("a", "b", "keep  ")
        )
        self.assertEqual(parse_forwarded("from a (b): endX\n"), Forwarded("a", "b", "endX"))


class TestHasForwardedLine(unittest.TestCase):
    def test_detects_a_forwarded_line_anywhere(self):
        self.assertTrue(has_forwarded_line("x\nfrom a (b): c"))
        self.assertFalse(has_forwarded_line("from a: c"))
        self.assertFalse(has_forwarded_line(None))


class TestShimNotes(unittest.TestCase):
    def test_prepends_forwarded_line_to_stored_notes(self):
        self.assertEqual(shim_notes("a", "b", "rep", "stored"), "from a (b): rep\nstored")

    def test_no_stored_notes_yields_just_the_line(self):
        self.assertEqual(shim_notes("a", "b", "rep", ""), "from a (b): rep")

    def test_existing_forwarded_line_is_kept(self):
        self.assertEqual(shim_notes("a", "b", "rep", "from x (y): z"), "from x (y): z")

    def test_no_report_returns_stored(self):
        self.assertEqual(shim_notes("a", "b", "", "stored"), "stored")


if __name__ == "__main__":
    unittest.main()
