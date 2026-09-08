import json
import unittest

from lightcycle.domain.pool import parse_attribution_chunk, parse_attribution_event


def _assistant(message_id, blocks, usage=None):
    message = {"id": message_id, "content": blocks}
    if usage is not None:
        message["usage"] = usage
    return json.dumps({"type": "assistant", "message": message})


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


class TestRecoveredUsage(unittest.TestCase):
    def test_two_distinct_message_ids_each_carrying_usage_sum_into_recovered_totals(self):
        lines = [
            _assistant("msg-1", [], usage={
                "input_tokens": 10, "output_tokens": 20,
                "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40,
            }),
            _assistant("msg-2", [], usage={
                "input_tokens": 1, "output_tokens": 2,
                "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4,
            }),
        ]
        event = parse_attribution_event(lines)
        self.assertEqual(event.recovered_input_tokens, 11)
        self.assertEqual(event.recovered_output_tokens, 22)
        self.assertEqual(event.recovered_cache_read_tokens, 33)
        self.assertEqual(event.recovered_cache_creation_tokens, 44)

    def test_a_repeated_message_id_contributes_its_usage_once_not_per_line(self):
        usage = {
            "input_tokens": 10, "output_tokens": 20,
            "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40,
        }
        lines = [
            _assistant("msg-1", [], usage=usage),
            _assistant("msg-1", [], usage=usage),
            _assistant("msg-1", [], usage=usage),
        ]
        event = parse_attribution_event(lines)
        self.assertEqual(event.recovered_input_tokens, 10)
        self.assertEqual(event.recovered_output_tokens, 20)
        self.assertEqual(event.recovered_cache_read_tokens, 30)
        self.assertEqual(event.recovered_cache_creation_tokens, 40)

    def test_an_assistant_line_with_no_usage_key_contributes_nothing(self):
        lines = [_assistant("msg-1", [])]
        event = parse_attribution_event(lines)
        self.assertEqual(event.recovered_input_tokens, 0)
        self.assertEqual(event.recovered_output_tokens, 0)
        self.assertEqual(event.recovered_cache_read_tokens, 0)
        self.assertEqual(event.recovered_cache_creation_tokens, 0)

    def test_no_assistant_lines_returns_all_recovered_fields_as_zero(self):
        event = parse_attribution_event([])
        self.assertEqual(event.recovered_input_tokens, 0)
        self.assertEqual(event.recovered_output_tokens, 0)
        self.assertEqual(event.recovered_cache_read_tokens, 0)
        self.assertEqual(event.recovered_cache_creation_tokens, 0)


class TestParseAttributionChunk(unittest.TestCase):
    def test_a_message_ids_lines_split_across_two_chunk_calls_credits_it_once(self):
        usage = {
            "input_tokens": 10, "output_tokens": 20,
            "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40,
        }
        first_lines = [_assistant("msg-1", [_tool_use("tu-1", "Read")], usage=usage)]
        second_lines = [_assistant("msg-1", [_tool_use("tu-2", "Bash")])]

        delta1, message_ids, pending = parse_attribution_chunk(first_lines, set(), {})
        self.assertEqual(delta1.turn_count, 1)
        self.assertEqual(delta1.recovered_input_tokens, 10)

        delta2, message_ids, pending = parse_attribution_chunk(second_lines, message_ids, pending)
        self.assertEqual(delta2.turn_count, 0)
        self.assertEqual(delta2.recovered_input_tokens, 0)
        self.assertEqual(delta2.recovered_output_tokens, 0)

    def test_a_tool_use_and_tool_result_pair_split_across_two_chunk_calls_attributes_correctly(self):
        first_lines = [_assistant("msg-1", [_tool_use("tu-1", "Bash")])]
        second_lines = [_user([_tool_result("tu-1", "hello")])]

        delta1, message_ids, pending = parse_attribution_chunk(first_lines, set(), {})
        self.assertEqual(delta1.tool_usage, {})
        self.assertEqual(pending, {"tu-1": "Bash"})

        delta2, message_ids, pending = parse_attribution_chunk(second_lines, message_ids, pending)
        self.assertEqual(delta2.tool_usage["Bash"].calls, 1)
        self.assertEqual(delta2.tool_usage["Bash"].bytes, len(b"hello"))
        self.assertEqual(pending, {})

    def test_chunked_from_empty_state_matches_the_one_call_wrapper_on_the_same_lines(self):
        lines = [
            _assistant("msg-1", [_tool_use("tu-1", "Read"), _tool_use("tu-2", "Bash")],
                       usage={"input_tokens": 5, "output_tokens": 7}),
            _user([_tool_result("tu-1", "abc")]),
            _assistant("msg-2", [_tool_use("tu-3", "Grep")]),
            _user([_tool_result("tu-2", "de"), _tool_result("tu-3", "f")]),
        ]
        whole = parse_attribution_event(lines)
        delta, _, _ = parse_attribution_chunk(lines, set(), {})
        self.assertEqual(delta.turn_count, whole.turn_count)
        self.assertEqual(delta.tool_usage, whole.tool_usage)
        self.assertEqual(delta.recovered_input_tokens, whole.recovered_input_tokens)
        self.assertEqual(delta.recovered_output_tokens, whole.recovered_output_tokens)

    def test_a_chunk_ending_mid_line_is_left_for_the_caller_to_re_read_whole(self):
        complete = _assistant("msg-1", [_tool_use("tu-1", "Read")])
        partial = '{"type":"assistant","message":{"id":"msg-2"'
        text = complete + "\n" + partial
        last_newline = text.rfind("\n")
        first_pass_lines = text[: last_newline + 1].splitlines(keepends=True)

        delta1, message_ids, pending = parse_attribution_chunk(first_pass_lines, set(), {})
        self.assertEqual(delta1.turn_count, 1)

        full_partial_line = json.dumps({
            "type": "assistant", "message": {"id": "msg-2", "content": []},
        })
        delta2, message_ids, pending = parse_attribution_chunk(
            [full_partial_line], message_ids, pending
        )
        self.assertEqual(delta2.turn_count, 1)
        self.assertEqual(len(message_ids), 2)


if __name__ == "__main__":
    unittest.main()
