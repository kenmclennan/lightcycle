import unittest

from lightcycle.adapters.tui.design_system import COLUMN_GRIDS, CURSOR_GLYPH


class TestSelectionCursor(unittest.TestCase):
    def test_selection_cursor_glyph_and_colour(self):
        self.assertEqual(CURSOR_GLYPH, ("❯", "cyan"))


class TestColumnGridWidths(unittest.TestCase):
    def test_priority_list_grid_widths(self):
        self.assertEqual(
            COLUMN_GRIDS["priority-list"],
            (
                ("cursor", "2ch"), ("icon", "4ch"), ("id", "9ch"), ("project", "10ch"),
                ("title", "1fr"), ("step", "16ch"), ("time", "8ch"),
            ),
        )

    def test_backlog_grid_widths(self):
        self.assertEqual(
            COLUMN_GRIDS["backlog"],
            (
                ("cursor", "2ch"), ("id", "9ch"), ("project", "10ch"), ("title", "1fr"),
            ),
        )
