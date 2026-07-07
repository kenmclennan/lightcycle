import unittest

from lightcycle.domain.pool import parse_rate_limit_event


class TestParseRateLimitEvent(unittest.TestCase):
    def test_rejected_status_is_the_limit_signal(self):
        text = (
            '{"type":"rate_limit_event","rate_limit_info":'
            '{"status":"rejected","resetsAt":1751500862,"rateLimitType":"five_hour"}}'
        )
        event = parse_rate_limit_event(text)
        self.assertEqual(event.status, "rejected")
        self.assertTrue(event.is_rejected)
        self.assertEqual(event.reset_at, 1751500862)

    def test_allowed_status_is_not_a_limit(self):
        text = (
            '{"type":"rate_limit_event","rate_limit_info":'
            '{"status":"allowed","resetsAt":1751500862}}'
        )
        event = parse_rate_limit_event(text)
        self.assertFalse(event.is_rejected)

    def test_ignores_other_json_lines(self):
        text = "\n".join(
            [
                '{"type":"assistant","message":"hello"}',
                '{"type":"result","subtype":"success"}',
            ]
        )
        self.assertIsNone(parse_rate_limit_event(text))

    def test_ignores_non_json_lines(self):
        self.assertIsNone(parse_rate_limit_event("not json at all\n{broken"))

    def test_empty_or_none_text_is_none(self):
        self.assertIsNone(parse_rate_limit_event(""))
        self.assertIsNone(parse_rate_limit_event(None))

    def test_last_event_wins_when_several_are_present(self):
        text = "\n".join(
            [
                '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}',
                '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":42}}',
            ]
        )
        event = parse_rate_limit_event(text)
        self.assertTrue(event.is_rejected)
        self.assertEqual(event.reset_at, 42)

    def test_missing_status_is_not_an_event(self):
        text = '{"type":"rate_limit_event","rate_limit_info":{"resetsAt":42}}'
        self.assertIsNone(parse_rate_limit_event(text))


if __name__ == "__main__":
    unittest.main()
