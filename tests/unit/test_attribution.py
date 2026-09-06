import json
import unittest

from lightcycle.domain.pool import parse_attribution_event


def _assistant(message_id, blocks):
    return json.dumps({"type": "assistant", "message": {"id": message_id, "content": blocks}})


def _user(blocks):
    return json.dumps({"type": "user", "message": {"content": blocks}})


def _tool_use(tool_use_id, name, command=None):
    block = {"type": "tool_use", "id": tool_use_id, "name": name}
    if command is not None:
        block["input"] = {"command": command}
    return block


def _tool_result(tool_use_id, content):
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


class TestParseAttributionEvent(unittest.TestCase):
    def test_turn_count_is_distinct_message_ids_not_line_count(self):
        lines = [
            _assistant("msg-1", [_tool_use("tu-1", "Read"), _tool_use("tu-2", "Bash")]),
            _assistant("msg-1", [_tool_use("tu-3", "Grep")]),
            _assistant("msg-2", [_tool_use("tu-4", "Read")]),
        ]
        event = parse_attribution_event(lines)
        self.assertEqual(event.turn_count, 2)

    def test_per_tool_calls_and_bytes_across_different_tools(self):
        lines = [
            _assistant("msg-1", [_tool_use("tu-1", "Read"), _tool_use("tu-2", "Grep")]),
            _user([_tool_result("tu-1", "hello"), _tool_result("tu-2", "hi")]),
        ]
        event = parse_attribution_event(lines)
        self.assertEqual(event.tool_usage["Read"].calls, 1)
        self.assertEqual(event.tool_usage["Read"].bytes, len(b"hello"))
        self.assertEqual(event.tool_usage["Grep"].calls, 1)
        self.assertEqual(event.tool_usage["Grep"].bytes, len(b"hi"))

    def test_batched_tool_results_in_one_user_message_all_attributed(self):
        lines = [
            _assistant("msg-1", [_tool_use("tu-1", "Read"), _tool_use("tu-2", "Read")]),
            _user([_tool_result("tu-1", "aaaa"), _tool_result("tu-2", "bbbb")]),
        ]
        event = parse_attribution_event(lines)
        self.assertEqual(event.tool_usage["Read"].calls, 2)
        self.assertEqual(event.tool_usage["Read"].bytes, len(b"aaaa") + len(b"bbbb"))

    def test_list_of_blocks_content_joins_text_fields_for_byte_count(self):
        lines = [
            _assistant("msg-1", [_tool_use("tu-1", "Read")]),
            _user([_tool_result("tu-1", [{"type": "text", "text": "abc"}, {"type": "text", "text": "de"}])]),
        ]
        event = parse_attribution_event(lines)
        self.assertEqual(event.tool_usage["Read"].bytes, len(b"abcde"))

    def test_tool_result_with_no_tracked_tool_use_id_buckets_under_unknown(self):
        lines = [_user([_tool_result("tu-missing", "orphaned")])]
        event = parse_attribution_event(lines)
        self.assertEqual(event.tool_usage["unknown"].calls, 1)
        self.assertEqual(event.tool_usage["unknown"].bytes, len(b"orphaned"))

    def test_empty_log_returns_zeroed_event_not_none(self):
        event = parse_attribution_event([])
        self.assertEqual(event.turn_count, 0)
        self.assertEqual(event.tool_usage, {})

    def test_no_assistant_lines_returns_zeroed_event(self):
        event = parse_attribution_event(['{"type":"other"}'])
        self.assertEqual(event.turn_count, 0)
        self.assertEqual(event.tool_usage, {})


if __name__ == "__main__":
    unittest.main()
