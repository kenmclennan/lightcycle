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


if __name__ == "__main__":
    unittest.main()
