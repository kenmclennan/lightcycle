import unittest
from unittest.mock import patch

from lightcycle.adapters.tui.app import BACKLOG_COLUMNS, BACKLOG_CONTINUATION_INDENT, BacklogTable, BacklogView
from lightcycle.adapters.tui.backlog_list import BacklogRow
from lightcycle.adapters.tui.row_grid import FLEXIBLE_MINIMUM, atomic_column_width
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container


def _row(id, project="", title="title"):
    return BacklogRow(id=id, project=project, title=title)


class TestBacklogViewCheapPathOnUnchangedShape(unittest.TestCase):
    def _launch(self):
        store = FakeStore()
        store.create_item("seed")
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        session.press("tab")
        return session

    def _apply(self, session, view, rows, total, project_filter):
        session.run(lambda: view.apply_rows(rows, total, project_filter))
        session.pause()

    def test_identical_shape_takes_update_cells_not_rebuild(self):
        session = self._launch()
        view = session.app.query_one(BacklogView)
        rows = [_row("a"), _row("b")]
        self._apply(session, view, rows, 2, None)

        with patch.object(BacklogView, "_rebuild_table") as rebuild, \
                patch.object(BacklogView, "_update_cells") as update:
            self._apply(session, view, rows, 2, None)
            rebuild.assert_not_called()
            update.assert_called_once()

    def test_changed_row_ids_rebuilds(self):
        session = self._launch()
        view = session.app.query_one(BacklogView)
        self._apply(session, view, [_row("a")], 1, None)

        with patch.object(BacklogView, "_rebuild_table") as rebuild, \
                patch.object(BacklogView, "_update_cells") as update:
            self._apply(session, view, [_row("b")], 1, None)
            rebuild.assert_called_once()
            update.assert_not_called()

    def test_changed_total_rebuilds(self):
        session = self._launch()
        view = session.app.query_one(BacklogView)
        rows = [_row("a")]
        self._apply(session, view, rows, 1, None)

        with patch.object(BacklogView, "_rebuild_table") as rebuild, \
                patch.object(BacklogView, "_update_cells") as update:
            self._apply(session, view, rows, 2, None)
            rebuild.assert_called_once()
            update.assert_not_called()

    def test_changed_project_filter_rebuilds(self):
        session = self._launch()
        view = session.app.query_one(BacklogView)
        rows = [_row("a")]
        self._apply(session, view, rows, 1, None)

        with patch.object(BacklogView, "_rebuild_table") as rebuild, \
                patch.object(BacklogView, "_update_cells") as update:
            self._apply(session, view, rows, 1, "proj-a")
            rebuild.assert_called_once()
            update.assert_not_called()

    def test_cheap_path_still_reflects_a_title_change_on_the_cursor_row(self):
        session = self._launch()
        view = session.app.query_one(BacklogView)
        self._apply(session, view, [_row("a", title="old title")], 1, None)

        self._apply(session, view, [_row("a", title="new title")], 1, None)

        table = session.app.query_one(BacklogTable)
        cell = table.get_cell("a", "title")
        self.assertEqual(cell, "new title")


class TestBacklogViewRebuildGapAtZeroWidth(unittest.TestCase):
    def _launch(self):
        session = launch(make_test_container(store=FakeStore()))
        self.addCleanup(session.close)
        return session

    def _apply(self, session, view, rows, total, project_filter):
        session.run(lambda: view.apply_rows(rows, total, project_filter))
        session.pause()

    def test_zero_width_then_real_width_with_same_shape_still_rebuilds(self):
        session = self._launch()
        view = session.app.query_one(BacklogView)
        rows = [_row("a"), _row("b")]

        self._apply(session, view, rows, 2, None)
        self.assertTrue(view._backlog_needs_rebuild)

        with patch.object(BacklogView, "refresh_column_width"):
            session.press("tab")

        table = session.app.query_one(BacklogTable)
        self.assertGreater(table.size.width, 0)

        self._apply(session, view, rows, 2, None)

        self.assertEqual(table.row_count, len(rows))

    def test_zero_width_both_times_does_not_raise_or_render(self):
        session = self._launch()
        view = session.app.query_one(BacklogView)
        rows = [_row("a")]

        self._apply(session, view, rows, 1, None)
        self.assertTrue(view._backlog_needs_rebuild)

        self._apply(session, view, rows, 1, None)
        self.assertTrue(view._backlog_needs_rebuild)

        table = session.app.query_one(BacklogTable)
        self.assertEqual(table.row_count, 0)


class TestBacklogViewRebuildGapAtFloorWidth(unittest.TestCase):
    def _floor_terminal_width(self):
        glyph_total = BACKLOG_CONTINUATION_INDENT
        atomic_values = {"id": ["a", "b"], "project": [""]}
        atomic_total = sum(max(1, atomic_column_width(v)) for v in atomic_values.values())
        first_line_width = glyph_total + atomic_total
        floor_width = max(first_line_width, BACKLOG_CONTINUATION_INDENT + FLEXIBLE_MINIMUM)
        row_budget = floor_width - 1
        return row_budget + 2 + 2 * len(BACKLOG_COLUMNS)

    def _launch(self):
        store = FakeStore()
        store.create_item("seed")
        width = self._floor_terminal_width()
        session = launch(make_test_container(store=store), size=(width, 24))
        self.addCleanup(session.close)
        return session

    def _apply(self, session, view, rows, total, project_filter):
        session.run(lambda: view.apply_rows(rows, total, project_filter))
        session.pause()

    def test_two_consecutive_polls_at_floor_width_do_not_raise(self):
        session = self._launch()
        view = session.app.query_one(BacklogView)
        rows = [_row("a"), _row("b")]

        with patch.object(BacklogView, "refresh_column_width"):
            session.press("tab")

        self._apply(session, view, rows, 2, None)
        self.assertTrue(view._floor)
        self.assertTrue(view._backlog_needs_rebuild)

        self._apply(session, view, rows, 2, None)

        self.assertTrue(view._floor)
        self.assertTrue(view._backlog_needs_rebuild)
        table = session.app.query_one(BacklogTable)
        self.assertEqual(table.row_count, 0)


if __name__ == "__main__":
    unittest.main()
