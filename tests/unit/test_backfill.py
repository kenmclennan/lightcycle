import json
import unittest

from lightcycle.adapters.claude_stream import extract_claimed_step


def _assistant(blocks):
    return json.dumps({"type": "assistant", "message": {"content": blocks}})


def _user(blocks):
    return json.dumps({"type": "user", "message": {"content": blocks}})


def _bash_tool_use(tool_use_id, command):
    return {"type": "tool_use", "id": tool_use_id, "name": "Bash", "input": {"command": command}}


def _tool_result(tool_use_id, content):
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


class TestExtractClaimedStep(unittest.TestCase):
    def test_valid_json_tool_result_with_id_field_recovers_it(self):
        lines = [
            _assistant([_bash_tool_use("tu-1", "lc claim agent")]),
            _user([_tool_result("tu-1", json.dumps({"id": "LC-468.4"}))]),
        ]
        self.assertEqual(extract_claimed_step(lines), "LC-468.4")

    def test_no_lc_claim_call_at_all_returns_none(self):
        lines = [
            _assistant([_bash_tool_use("tu-1", "git status")]),
            _user([_tool_result("tu-1", json.dumps({"id": "LC-468.4"}))]),
        ]
        self.assertIsNone(extract_claimed_step(lines))

    def test_non_json_content_falls_back_to_regex(self):
        lines = [
            _assistant([_bash_tool_use("tu-1", "lc claim agent")]),
            _user([_tool_result("tu-1", 'not json but has "id": "LC-468.4" in it')]),
        ]
        self.assertEqual(extract_claimed_step(lines), "LC-468.4")

    def test_non_json_content_with_no_id_match_returns_none(self):
        lines = [
            _assistant([_bash_tool_use("tu-1", "lc claim agent")]),
            _user([_tool_result("tu-1", "not json and no id here")]),
        ]
        self.assertIsNone(extract_claimed_step(lines))

    def test_claim_calls_own_tool_result_missing_within_limit_returns_none(self):
        lines = [_assistant([_bash_tool_use("tu-1", "lc claim agent")])]
        lines += ['{"type":"other"}'] * 65
        lines.append(_user([_tool_result("tu-1", json.dumps({"id": "LC-468.4"}))]))
        self.assertIsNone(extract_claimed_step(lines, limit=60))

    def test_id_looking_string_in_unrelated_tool_result_before_claim_is_ignored(self):
        lines = [
            _assistant([_bash_tool_use("tu-1", "some other command")]),
            _user([_tool_result("tu-1", json.dumps({"id": "LC-999.1"}))]),
            _assistant([_bash_tool_use("tu-2", "lc claim agent")]),
            _user([_tool_result("tu-2", json.dumps({"id": "LC-468.4"}))]),
        ]
        self.assertEqual(extract_claimed_step(lines), "LC-468.4")

    def test_empty_log_returns_none(self):
        self.assertIsNone(extract_claimed_step([]))


if __name__ == "__main__":
    unittest.main()
