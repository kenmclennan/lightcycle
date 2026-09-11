import unittest

from lightcycle.domain.work import Park


class TestParkAsHistoryNote(unittest.TestCase):
    def test_empty_park_returns_none(self):
        self.assertIsNone(Park().as_history_note())

    def test_reason_only(self):
        self.assertEqual(Park(reason="oops").as_history_note(), "PARK RESOLVED: reason=oops")

    def test_needs_only(self):
        self.assertEqual(
            Park(needs="decide X").as_history_note(), "PARK RESOLVED: needs=decide X"
        )

    def test_tried_only(self):
        self.assertEqual(Park(tried="a,b").as_history_note(), "PARK RESOLVED: tried=a,b")

    def test_all_three_ordered_and_pipe_joined(self):
        p = Park(reason="oops", needs="decide X", tried="a,b")
        self.assertEqual(
            p.as_history_note(), "PARK RESOLVED: reason=oops | needs=decide X | tried=a,b"
        )

    def test_collapses_internal_whitespace_and_newlines(self):
        p = Park(reason="line one\nline two", needs="  a   b  ")
        self.assertEqual(
            p.as_history_note(), "PARK RESOLVED: reason=line one line two | needs=a b"
        )


class TestParkAsBlockedNote(unittest.TestCase):
    def test_formats_the_needs_field(self):
        self.assertEqual(Park(needs="decide X").as_blocked_note(), "BLOCKED: decide X")


class TestParkStripBlockedNotes(unittest.TestCase):
    def test_empty_text_returns_empty_list(self):
        self.assertEqual(Park.strip_blocked_notes(None), [])
        self.assertEqual(Park.strip_blocked_notes(""), [])

    def test_drops_only_lines_starting_with_the_prefix(self):
        text = "keep this\nBLOCKED: drop this\nkeep this too"
        self.assertEqual(Park.strip_blocked_notes(text), ["keep this", "keep this too"])

    def test_strips_a_note_written_by_the_old_code(self):
        old_note = "BLOCKED: CLU landing GRID-059 by-hand; do not pool-spawn"
        self.assertEqual(Park.strip_blocked_notes(old_note), [])


if __name__ == "__main__":
    unittest.main()
