import unittest
from unittest.mock import patch

import lightcycle.adapters.tui.app as app_module
from lightcycle.adapters.tui.app import (
    BACKLOG_COLUMNS, DATA_COLUMNS, BacklogTable, BacklogView, PriorityTable,
)
from lightcycle.adapters.tui.row_grid import (
    FLEXIBLE_MINIMUM, GLYPH_WIDTHS, atomic_column_width, scrollbar_reservation_width,
)
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

_BACKLOG_ID_A = "LC-100"
_BACKLOG_ID_B = "LC-200"
_BACKLOG_PROJECT = "lightcycle"


def _backlog_stack_terminal_width():
    glyph_total = GLYPH_WIDTHS["cursor"]
    atomic_values = {"id": [_BACKLOG_ID_A, _BACKLOG_ID_B], "project": [_BACKLOG_PROJECT]}
    atomic_total = sum(max(1, atomic_column_width(v)) for v in atomic_values.values())
    first_line_width = glyph_total + atomic_total
    breakpoint_width = first_line_width + FLEXIBLE_MINIMUM
    row_budget = breakpoint_width - 1
    return row_budget + 2 + 2 * len(BACKLOG_COLUMNS) + scrollbar_reservation_width(BacklogTable)


class TestBacklogStackedRebuildRendersEachRowOnce(unittest.TestCase):
    def _launch(self):
        store = FakeStore()
        a = store.create_item("first title long enough for a continuation line", "a description", id=_BACKLOG_ID_A)
        store.add_artifact(a, "repo", _BACKLOG_PROJECT)
        b = store.create_item("second title long enough for a continuation line", "a description", id=_BACKLOG_ID_B)
        store.add_artifact(b, "repo", _BACKLOG_PROJECT)
        width = _backlog_stack_terminal_width()
        session = launch(make_test_container(store=store), size=(width, 24))
        self.addCleanup(session.close)
        return session

    def test_rebuild_calls_the_cell_builder_once_per_row_not_twice(self):
        session = self._launch()
        session.press("tab")
        view = session.app.query_one(BacklogView)
        table = session.app.query_one(BacklogTable)
        self.assertTrue(table._stacked_mode)

        with patch.object(app_module, "_backlog_row_cells", wraps=app_module._backlog_row_cells) as spy:
            session.run(lambda: view._rebuild_table(view._rows))
            session.pause()

        self.assertEqual(spy.call_count, 2)

    def test_moving_the_cursor_repaints_only_the_two_affected_rows(self):
        session = self._launch()
        session.press("tab")
        table = session.app.query_one(BacklogTable)
        self.assertTrue(table._stacked_mode)

        self.assertIn("❯", table.get_cell(_BACKLOG_ID_A, "row").plain)
        self.assertNotIn("❯", table.get_cell(_BACKLOG_ID_B, "row").plain)

        calls = []
        original = app_module._repaint_stacked_cursor

        def spy(table_arg, row_key, show):
            calls.append(row_key.value)
            return original(table_arg, row_key, show)

        with patch.object(app_module, "_repaint_stacked_cursor", spy):
            session.press("down")

        self.assertEqual(set(calls), {_BACKLOG_ID_A, _BACKLOG_ID_B})
        self.assertEqual(len(calls), 2)

        self.assertNotIn("❯", table.get_cell(_BACKLOG_ID_A, "row").plain)
        self.assertIn("❯", table.get_cell(_BACKLOG_ID_B, "row").plain)


_PRIORITY_ID_A = "LC-300.1"
_PRIORITY_ID_B = "LC-400.1"
_PRIORITY_PROJECT = "lightcycle"
_PRIORITY_STEP = "code-review-rounds"


def _priority_stack_terminal_width():
    glyph_total = GLYPH_WIDTHS["cursor"] + GLYPH_WIDTHS["icon"]
    atomic_values = {
        "id": [_PRIORITY_ID_A, _PRIORITY_ID_B],
        "project": [_PRIORITY_PROJECT],
        "step": [_PRIORITY_STEP],
        "time": [""],
    }
    atomic_total = sum(max(1, atomic_column_width(v)) for v in atomic_values.values())
    first_line_width = glyph_total + atomic_total
    breakpoint_width = first_line_width + FLEXIBLE_MINIMUM
    row_budget = breakpoint_width - 1
    return row_budget + 2 + 2 * len(DATA_COLUMNS) + scrollbar_reservation_width(PriorityTable)


class TestPriorityStackedRebuildRendersEachRowOnce(unittest.TestCase):
    def _launch(self):
        store = FakeStore()
        store.create_step(
            "first title long enough for a continuation line",
            step=_PRIORITY_STEP, role="agent", id=_PRIORITY_ID_A,
        )
        store.add_artifact(_PRIORITY_ID_A, "repo", _PRIORITY_PROJECT)
        store.create_step(
            "second title long enough for a continuation line",
            step=_PRIORITY_STEP, role="agent", id=_PRIORITY_ID_B,
        )
        store.add_artifact(_PRIORITY_ID_B, "repo", _PRIORITY_PROJECT)
        width = _priority_stack_terminal_width()
        session = launch(make_test_container(store=store), size=(width, 24))
        self.addCleanup(session.close)
        return session

    def test_rebuild_calls_the_cell_builder_once_per_row_not_twice(self):
        session = self._launch()
        table = session.app.query_one(PriorityTable)
        self.assertTrue(table._stacked_mode)
        rows = session.app._last_priority_rows

        with patch.object(session.app, "_row_cells", wraps=session.app._row_cells) as spy:
            session.run(lambda: session.app._rebuild_table(table, rows))
            session.pause()

        self.assertEqual(spy.call_count, 2)


class TestPriorityStackedCursorGlyphSurvivesCheapPaths(unittest.TestCase):
    def _launch(self, *, active_ids=()):
        store = FakeStore()
        store.create_step(
            "first title long enough for a continuation line",
            step=_PRIORITY_STEP, role="agent", id=_PRIORITY_ID_A,
        )
        store.add_artifact(_PRIORITY_ID_A, "repo", _PRIORITY_PROJECT)
        store.create_step(
            "second title long enough for a continuation line",
            step=_PRIORITY_STEP, role="agent", id=_PRIORITY_ID_B,
        )
        store.add_artifact(_PRIORITY_ID_B, "repo", _PRIORITY_PROJECT)
        for tid in active_ids:
            store.assign(tid, "worker-1")
            store.update_state(tid, State.IN_PROGRESS)
        width = _priority_stack_terminal_width()
        session = launch(make_test_container(store=store), size=(width, 24))
        self.addCleanup(session.close)
        return session

    def test_cheap_poll_leaves_the_cursor_glyph_on_the_selected_row(self):
        session = self._launch()
        table = session.app.query_one(PriorityTable)
        self.assertTrue(table._stacked_mode)
        selected_id = session.app._selected_row_id(table)
        self.assertIn("❯", table.get_cell(selected_id, "row").plain)

        session.poll_tick()

        self.assertIn("❯", table.get_cell(selected_id, "row").plain)

    def test_active_glyph_tick_leaves_the_cursor_glyph_on_the_selected_row(self):
        session = self._launch(active_ids=(_PRIORITY_ID_A,))
        table = session.app.query_one(PriorityTable)
        self.assertTrue(table._stacked_mode)
        selected_id = session.app._selected_row_id(table)
        self.assertEqual(selected_id, _PRIORITY_ID_A)
        self.assertIn("❯", table.get_cell(_PRIORITY_ID_A, "row").plain)

        session.run(session.app._tick_active_glyph)

        self.assertIn("❯", table.get_cell(_PRIORITY_ID_A, "row").plain)

    def test_active_glyph_tick_paints_the_glyph_only_on_the_selected_row(self):
        session = self._launch(active_ids=(_PRIORITY_ID_A, _PRIORITY_ID_B))
        table = session.app.query_one(PriorityTable)
        self.assertTrue(table._stacked_mode)
        session.press("down")
        selected_id = session.app._selected_row_id(table)
        self.assertEqual(selected_id, _PRIORITY_ID_B)

        session.run(session.app._tick_active_glyph)

        self.assertNotIn("❯", table.get_cell(_PRIORITY_ID_A, "row").plain)
        self.assertIn("❯", table.get_cell(_PRIORITY_ID_B, "row").plain)


if __name__ == "__main__":
    unittest.main()
