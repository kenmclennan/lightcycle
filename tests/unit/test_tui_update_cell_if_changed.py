import asyncio
import unittest

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from lightcycle.adapters.tui.app import _update_cell_if_changed


class _ProbeApp(App):
    def compose(self) -> ComposeResult:
        yield DataTable(id="probe")


def _run(coro):
    return asyncio.run(coro)


class TestUpdateCellIfChanged(unittest.TestCase):
    def test_unchanged_refresh_leaves_the_update_count_alone(self):
        async def scenario():
            app = _ProbeApp()
            async with app.run_test():
                table = app.query_one(DataTable)
                keys = [table.add_column("id"), table.add_column("title")]
                table.add_row(Text("a"), Text("one"), key="r1")
                table.add_row(Text("b"), Text("two"), key="r2")
                before = table._update_count
                for row_key, cells in (("r1", ("a", "one")), ("r2", ("b", "two"))):
                    for column_key, value in zip(keys, cells):
                        _update_cell_if_changed(table, row_key, column_key, Text(value))
                return before, table._update_count

        before, after = _run(scenario())

        self.assertEqual(before, after)

    def test_one_changed_cell_updates_only_that_cell(self):
        async def scenario():
            app = _ProbeApp()
            async with app.run_test():
                table = app.query_one(DataTable)
                keys = [table.add_column("id"), table.add_column("title")]
                table.add_row(Text("a"), Text("one"), key="r1")
                table.add_row(Text("b"), Text("two"), key="r2")
                before = table._update_count
                for row_key, cells in (("r1", ("a", "one")), ("r2", ("b", "TWO"))):
                    for column_key, value in zip(keys, cells):
                        _update_cell_if_changed(table, row_key, column_key, Text(value))
                return before, table._update_count, table.get_cell("r2", keys[1]), table.get_cell("r1", keys[1])

        before, after, changed, untouched = _run(scenario())

        self.assertEqual(after, before + 1)
        self.assertEqual(changed.plain, "TWO")
        self.assertEqual(untouched.plain, "one")
