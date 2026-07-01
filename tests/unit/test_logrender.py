import json
import unittest

from the_grid.logrender import render_log_line


class TestRenderLogLine(unittest.TestCase):
    def test_blank_is_skipped(self):
        self.assertIsNone(render_log_line("   \n"))

    def test_non_json_passes_through(self):
        self.assertEqual(render_log_line("plain run.log line"), "plain run.log line")

    def test_assistant_text(self):
        line = json.dumps({"type": "assistant",
                           "message": {"content": [{"type": "text", "text": "Claiming."}]}})
        self.assertEqual(render_log_line(line), "Claiming.")

    def test_assistant_bash_tool(self):
        line = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "tg claim coder"}}]}})
        self.assertEqual(render_log_line(line), "$ tg claim coder")

    def test_assistant_non_bash_tool_with_arg(self):
        line = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/x/y.py"}}]}})
        self.assertEqual(render_log_line(line), "[Read /x/y.py]")

    def test_assistant_non_bash_tool_without_arg(self):
        line = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "TodoWrite", "input": {}}]}})
        self.assertEqual(render_log_line(line), "[TodoWrite]")

    def test_tool_result(self):
        line = json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "first line\nsecond"}]}})
        self.assertEqual(render_log_line(line), "  -> first line")

    def test_result_event(self):
        line = json.dumps({"type": "result", "result": "done; fixed"})
        self.assertEqual(render_log_line(line), ">>> done; fixed")

    def test_unknown_type_is_none(self):
        self.assertIsNone(render_log_line(json.dumps({"type": "system", "subtype": "init"})))


if __name__ == "__main__":
    unittest.main()
