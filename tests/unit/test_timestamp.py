import datetime
import unittest

from lightcycle.domain.work import parse_timestamp


class TestParseTimestamp(unittest.TestCase):
    def test_naive_input_returns_an_aware_result_with_the_local_offset_attached(self):
        result = parse_timestamp("2026-01-01T10:00:00")
        self.assertIsNotNone(result.tzinfo)
        expected = datetime.datetime.fromisoformat("2026-01-01T10:00:00").astimezone()
        self.assertEqual(result, expected)

    def test_aware_input_passes_through_unchanged(self):
        result = parse_timestamp("2026-01-01T10:00:00+09:00")
        self.assertEqual(
            result, datetime.datetime.fromisoformat("2026-01-01T10:00:00+09:00")
        )

    def test_none_returns_none(self):
        self.assertIsNone(parse_timestamp(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_timestamp(""))


if __name__ == "__main__":
    unittest.main()
