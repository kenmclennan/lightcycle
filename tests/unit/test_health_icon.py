import unittest

from lightcycle.domain.pool import (
    HEALTH_IMAGE_IDS, icon_columns, placeholder_rows, png_size,
)
from lightcycle.domain.pool.health_icon import DIACRITICS, MAX_COLUMNS, PLACEHOLDER
from tests.support.png_bytes import png_bytes


class TestPngSize(unittest.TestCase):
    def test_reads_the_header_dimensions(self):
        self.assertEqual(png_size(png_bytes(24, 30)), (24, 30))

    def test_rejects_anything_that_is_not_a_png_header(self):
        good = png_bytes(24, 30)
        for data in (b"", None, b"not a png at all, just text bytes", good[:20], good[:8]):
            self.assertIsNone(png_size(data))

    def test_rejects_a_zero_dimension(self):
        self.assertIsNone(png_size(png_bytes(0, 30)))
        self.assertIsNone(png_size(png_bytes(24, 0)))

    def test_rejects_a_first_chunk_that_is_not_ihdr(self):
        good = png_bytes(24, 30)
        self.assertIsNone(png_size(good[:12] + b"IDAT" + good[16:]))


class TestIconColumns(unittest.TestCase):
    def test_24_by_30_is_three_columns(self):
        self.assertEqual(icon_columns(24, 30), 3)

    def test_half_rounds_up(self):
        self.assertEqual(icon_columns(5, 8), 3)

    def test_clamped_at_both_ends(self):
        self.assertEqual(icon_columns(1, 1000), 1)
        self.assertEqual(icon_columns(1000, 1), MAX_COLUMNS)


class TestPlaceholderRows(unittest.TestCase):
    def test_two_rows_of_cells_each_with_two_marks(self):
        rgb, rows = placeholder_rows(0x4C0003, 3)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row), 9)
            self.assertEqual(row.count(PLACEHOLDER), 3)
        self.assertEqual(rgb[0] << 16 | rgb[1] << 8 | rgb[2], 0x4C0003)

    def test_diacritics_match_the_kitty_table_prefix(self):
        self.assertEqual(
            [ord(c) for c in DIACRITICS],
            [0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F],
        )

    def test_each_state_has_its_own_fixed_id(self):
        self.assertEqual(len(set(HEALTH_IMAGE_IDS.values())), 6)
