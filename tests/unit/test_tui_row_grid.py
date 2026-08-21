import unittest

from lightcycle.adapters.tui.row_grid import (
    FLEXIBLE_MINIMUM,
    GLYPH_WIDTHS,
    atomic_column_width,
    classify_grid,
    column_kind,
    compute_layout,
)


class TestColumnKind(unittest.TestCase):
    def test_glyph_columns(self):
        for name in ("cursor", "icon", "content"):
            self.assertEqual(column_kind(name), "glyph")

    def test_atomic_columns(self):
        for name in ("id", "project", "step", "role", "type", "time"):
            self.assertEqual(column_kind(name), "atomic")

    def test_flexible_columns(self):
        for name in ("title", "value"):
            self.assertEqual(column_kind(name), "flexible")


class TestClassifyGrid(unittest.TestCase):
    def test_splits_columns_by_kind(self):
        glyphs, atomics, flexibles = classify_grid(
            ("cursor", "icon", "id", "project", "title", "step", "time")
        )
        self.assertEqual(glyphs, ["cursor", "icon"])
        self.assertEqual(atomics, ["id", "project", "step", "time"])
        self.assertEqual(flexibles, ["title"])


class TestAtomicColumnWidth(unittest.TestCase):
    def test_uses_the_longest_value(self):
        self.assertEqual(atomic_column_width(["a", "bbbbb", "cc"]), 5)

    def test_ignores_where_the_longest_value_sits_in_the_list(self):
        front_loaded = atomic_column_width(["LIGHTCYCLE-3.1.1", "a", "b"])
        back_loaded = atomic_column_width(["a", "b", "LIGHTCYCLE-3.1.1"])
        self.assertEqual(front_loaded, back_loaded)
        self.assertEqual(front_loaded, len("LIGHTCYCLE-3.1.1"))

    def test_empty_list_is_zero(self):
        self.assertEqual(atomic_column_width([]), 0)

    def test_blank_values_are_ignored(self):
        self.assertEqual(atomic_column_width(["", "abc", ""]), 3)


class TestComputeLayout(unittest.TestCase):
    def test_unstacked_when_plenty_of_room(self):
        layout = compute_layout(
            80, ["cursor", "icon"], {"id": ["LC-1"], "project": ["lc"]}, indent=2 + 4 + 4 + 2
        )
        self.assertFalse(layout.stacked)
        self.assertFalse(layout.floor)
        self.assertEqual(layout.flexible_width, 80 - (2 + 4) - (4 + 2))

    def test_atomic_width_is_never_capped_however_long_the_value(self):
        long_id = "LIGHTCYCLE-3.1.1"
        layout = compute_layout(200, ["cursor"], {"id": [long_id]}, indent=2 + len(long_id))
        self.assertEqual(layout.atomic_widths["id"], len(long_id))
        self.assertGreaterEqual(layout.atomic_widths["id"], len(long_id))

    def test_stacks_when_the_flexible_minimum_no_longer_fits(self):
        glyph_total = GLYPH_WIDTHS["icon"] + GLYPH_WIDTHS["content"]
        id_width = 10
        role_width = 5
        indent = glyph_total + id_width
        first_line_width = indent + role_width
        row_budget = first_line_width + FLEXIBLE_MINIMUM - 1
        layout = compute_layout(
            row_budget, ["icon", "content"],
            {"id": ["x" * id_width], "role": ["y" * role_width]}, indent=indent,
        )
        self.assertTrue(layout.stacked)
        self.assertFalse(layout.floor)
        self.assertEqual(layout.flexible_width, row_budget - indent)

    def test_stacked_flexible_width_spans_the_row_past_trailing_atomic_columns(self):
        glyph_total = GLYPH_WIDTHS["icon"] + GLYPH_WIDTHS["content"]
        id_width = 10
        role_width = 19
        indent = glyph_total + id_width
        first_line_width = glyph_total + id_width + role_width
        row_budget = first_line_width + FLEXIBLE_MINIMUM - 1
        layout = compute_layout(
            row_budget, ["icon", "content"],
            {"id": ["x" * id_width], "role": ["y" * role_width]}, indent=indent,
        )
        self.assertTrue(layout.stacked)
        self.assertFalse(layout.floor)
        self.assertEqual(layout.flexible_width, row_budget - indent)
        self.assertGreaterEqual(layout.flexible_width, FLEXIBLE_MINIMUM)
        self.assertGreater(layout.flexible_width, row_budget - first_line_width)

    def test_hits_the_floor_when_the_first_line_does_not_fit(self):
        glyph_total = GLYPH_WIDTHS["cursor"] + GLYPH_WIDTHS["icon"]
        atomic_total = 10
        first_line_width = glyph_total + atomic_total
        indent = first_line_width
        layout = compute_layout(
            first_line_width - 1, ["cursor", "icon"], {"id": ["x" * atomic_total]}, indent=indent
        )
        self.assertTrue(layout.floor)
        self.assertFalse(layout.stacked)
        self.assertEqual(layout.floor_width, max(first_line_width, indent + FLEXIBLE_MINIMUM))

    def test_hits_the_floor_when_the_continuation_line_cannot_reach_the_flexible_minimum(self):
        glyph_total = GLYPH_WIDTHS["icon"] + GLYPH_WIDTHS["content"]
        id_width = 10
        role_width = 19
        indent = glyph_total + id_width
        first_line_width = glyph_total + id_width + role_width
        row_budget = indent + FLEXIBLE_MINIMUM - 1
        self.assertGreaterEqual(row_budget, first_line_width)
        layout = compute_layout(
            row_budget, ["icon", "content"],
            {"id": ["x" * id_width], "role": ["y" * role_width]}, indent=indent,
        )
        self.assertTrue(layout.floor)
        self.assertFalse(layout.stacked)
        self.assertEqual(layout.floor_width, indent + FLEXIBLE_MINIMUM)

    def test_floor_message_reports_the_terminal_width_not_the_internal_budget(self):
        glyph_total = GLYPH_WIDTHS["icon"] + GLYPH_WIDTHS["content"]
        id_width = 10
        role_width = 19
        indent = glyph_total + id_width
        row_budget = indent + FLEXIBLE_MINIMUM - 1
        layout = compute_layout(
            row_budget, ["icon", "content"],
            {"id": ["x" * id_width], "role": ["y" * role_width]}, indent=indent,
        )
        self.assertEqual(layout.floor_width, indent + FLEXIBLE_MINIMUM)
        self.assertGreater(layout.floor_width, glyph_total + id_width + role_width)

    def test_flexible_minimum_is_24(self):
        self.assertEqual(FLEXIBLE_MINIMUM, 24)

    def test_unknown_row_budget_defers_to_a_degenerate_unstacked_layout(self):
        layout = compute_layout(None, ["cursor"], {"id": ["fake-1234"]}, indent=2 + 9)
        self.assertFalse(layout.stacked)
        self.assertFalse(layout.floor)
        self.assertEqual(layout.flexible_width, 1)
