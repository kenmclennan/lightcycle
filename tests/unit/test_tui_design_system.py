import unittest

from lightcycle.adapters.tui.design_system import COLUMN_GRIDS, CURSOR_GLYPH, FOOTER_GLYPHS


class TestSelectionCursor(unittest.TestCase):
    def test_selection_cursor_glyph_and_colour(self):
        self.assertEqual(CURSOR_GLYPH, ("❯", "cyan"))


class TestFooterGlyphs(unittest.TestCase):
    def test_pool_running(self):
        self.assertEqual(FOOTER_GLYPHS["pool-running"], ("●", "cyan"))

    def test_pool_stopped(self):
        self.assertEqual(FOOTER_GLYPHS["pool-stopped"], ("○", "dim"))

    def test_claude_available(self):
        self.assertEqual(FOOTER_GLYPHS["claude-available"], ("●", "cyan"))

    def test_claude_unavailable(self):
        self.assertEqual(FOOTER_GLYPHS["claude-unavailable"], ("⊘", "red"))

    def test_upgrade_available(self):
        self.assertEqual(FOOTER_GLYPHS["upgrade-available"], ("⬆", "amber"))


class TestColumnGridOrder(unittest.TestCase):
    def test_priority_list_grid_order(self):
        self.assertEqual(
            COLUMN_GRIDS["priority-list"],
            ("cursor", "icon", "id", "project", "title", "step", "time"),
        )

    def test_backlog_grid_order(self):
        self.assertEqual(COLUMN_GRIDS["backlog"], ("cursor", "id", "project", "title"))

    def test_hierarchy_grid_order(self):
        self.assertEqual(
            COLUMN_GRIDS["hierarchy"], ("icon", "content", "id", "title", "role")
        )

    def test_artifacts_grid_order(self):
        self.assertEqual(COLUMN_GRIDS["artifacts"], ("type", "value"))
