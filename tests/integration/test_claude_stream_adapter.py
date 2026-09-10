import pathlib
import unittest

from lightcycle.adapters.claude_stream import ClaudeStreamAdapter

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "support" / "sample_stream.jsonl"


class TestClaudeStreamAdapterOverARecordedLog(unittest.TestCase):
    def setUp(self):
        self.lines = FIXTURE.read_text().splitlines(keepends=True)
        self.adapter = ClaudeStreamAdapter()

    def test_extract_claimed_step_recovers_the_id_from_the_tool_result(self):
        self.assertEqual(self.adapter.extract_claimed_step(self.lines), "LC-999.1")

    def test_parse_usage_event_recovers_non_zero_token_counts_from_the_result_line(self):
        usage = self.adapter.parse_usage_event(self.lines)
        self.assertTrue(usage.has_result_line)
        self.assertGreater(usage.input_tokens, 0)
        self.assertGreater(usage.output_tokens, 0)

    def test_parse_attribution_event_recovers_matching_turn_and_tool_counts(self):
        attribution = self.adapter.parse_attribution_event(self.lines)
        self.assertEqual(attribution.turn_count, 2)
        self.assertIn("Bash", attribution.tool_usage)
        self.assertEqual(attribution.tool_usage["Bash"].calls, 1)

    def test_parse_attribution_chunk_agrees_with_parse_attribution_event(self):
        delta, message_ids, pending_tool_use = self.adapter.parse_attribution_chunk(
            self.lines, set(), {}
        )
        self.assertEqual(delta.turn_count, 2)
        self.assertEqual(len(message_ids), 2)
        self.assertIn("Bash", delta.tool_usage)

    def test_saw_session_activity_is_true(self):
        self.assertTrue(self.adapter.saw_session_activity(self.lines))

    def test_saw_terminal_command_is_false(self):
        self.assertFalse(self.adapter.saw_terminal_command(self.lines))


if __name__ == "__main__":
    unittest.main()
