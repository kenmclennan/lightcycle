import unittest

from lightcycle.adapters.tui import tokens


class TestStateGlyphs(unittest.TestCase):
    def test_attention_is_a_red_dot(self):
        self.assertEqual(tokens.STATE_GLYPHS["attention"], (("●", tokens.RED),))

    def test_active_is_a_cyan_triangle(self):
        self.assertEqual(tokens.STATE_GLYPHS["active"], (("▸", tokens.CYAN),))

    def test_queued_is_a_dim_circle(self):
        self.assertEqual(tokens.STATE_GLYPHS["queued"], (("○", tokens.DIM),))

    def test_attention_blocked_keeps_the_red_dot_and_adds_an_amber_chain_link(self):
        blocked = tokens.STATE_GLYPHS["attention_blocked"]
        self.assertEqual(blocked[0], tokens.STATE_GLYPHS["attention"][0])
        self.assertEqual(blocked[1], ("⛓", tokens.AMBER))


class TestColumnGrids(unittest.TestCase):
    def test_priority_list_grid(self):
        self.assertEqual(
            tokens.PRIORITY_LIST_GRID,
            (
                ("cursor", 2), ("icon", 4), ("id", 9), ("project", 10),
                ("title", "1fr"), ("step", 16), ("time", 8),
            ),
        )

    def test_backlog_grid(self):
        self.assertEqual(
            tokens.BACKLOG_GRID,
            (("cursor", 2), ("id", 9), ("project", 10), ("title", "1fr")),
        )
