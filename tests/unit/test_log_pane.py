import asyncio
import unittest

from rich.text import Text
from textual.app import App, ComposeResult

from lightcycle.adapters.tui.hub import LOG_CURSOR_GLYPH, LogPane


class _ProbeApp(App):
    def compose(self) -> ComposeResult:
        yield LogPane(id="probe-log", max_lines=3, wrap=True, min_width=0)


def _run(coro):
    return asyncio.run(coro)


class TestLogPaneAtCapacity(unittest.TestCase):
    def test_replace_last_entry_leaves_no_stale_cursor_row_once_at_cap(self):
        async def scenario():
            app = _ProbeApp()
            async with app.run_test():
                pane = app.query_one(LogPane)
                pane.write_entry(Text("line one"))
                pane.write_entry(Text("line two"))
                pane.write_entry(Text("line three"))

                cursor_content = Text.assemble(Text("line four"), (LOG_CURSOR_GLYPH, "cyan"))
                row_count = pane.write_entry(cursor_content)
                pane.replace_last_entry(row_count, Text("line four"))

                return [strip.text for strip in pane.lines]

        rows = _run(scenario())

        self.assertEqual(len(rows), 3)
        self.assertEqual([r for r in rows if "line four" in r], ["line four"])
        self.assertNotIn(LOG_CURSOR_GLYPH, "".join(rows))

    def test_write_entry_reports_a_trim_proof_row_count_once_at_cap(self):
        async def scenario():
            app = _ProbeApp()
            async with app.run_test():
                pane = app.query_one(LogPane)
                pane.write_entry(Text("line one"))
                pane.write_entry(Text("line two"))
                pane.write_entry(Text("line three"))
                return pane.write_entry(Text("line four"))

        row_count = _run(scenario())
        self.assertEqual(row_count, 1)


if __name__ == "__main__":
    unittest.main()
