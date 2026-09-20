import unittest

from lightcycle.adapters.tui.design_system import SEARCH_MIN_WIDTH
from lightcycle.adapters.tui.filter_row import flow_filter_row

PROJECT = ("PROJECT", "All")
DAY = ("DAY", "2026-09-20")
COUNT = "149 items"


def _shape(layout):
    return [(tuple(line.segments), line.count) for line in layout.lines]


class TestFlowFilterRow(unittest.TestCase):
    def test_backlog_at_80_is_one_line_with_the_count(self):
        layout = flow_filter_row(80, [PROJECT], COUNT)

        self.assertEqual(_shape(layout), [((PROJECT,), COUNT)])
        self.assertEqual(layout.search_width, 46)

    def test_done_at_70_is_one_line(self):
        layout = flow_filter_row(70, [PROJECT, DAY], COUNT)

        self.assertEqual(_shape(layout), [((PROJECT, DAY), COUNT)])
        self.assertEqual(layout.search_width, 20)

    def test_done_at_60_puts_the_count_alone_on_line_two(self):
        layout = flow_filter_row(60, [PROJECT, DAY], COUNT)

        self.assertEqual(_shape(layout), [((PROJECT, DAY), None), ((), COUNT)])
        self.assertEqual(layout.search_width, 21)

    def test_done_at_50_moves_day_and_the_count_to_line_two(self):
        layout = flow_filter_row(50, [PROJECT, DAY], COUNT)

        self.assertEqual(_shape(layout), [((PROJECT,), None), ((DAY,), COUNT)])
        self.assertEqual(layout.search_width, 27)

    def test_backlog_count_boundary_with_a_column_either_side(self):
        at = flow_filter_row(50, [PROJECT], COUNT)
        wider = flow_filter_row(51, [PROJECT], COUNT)
        narrower = flow_filter_row(49, [PROJECT], COUNT)

        self.assertEqual((_shape(at)[0][1], at.search_width), (COUNT, SEARCH_MIN_WIDTH))
        self.assertEqual(wider.search_width, SEARCH_MIN_WIDTH + 1)
        self.assertEqual(_shape(narrower), [((PROJECT,), None), ((), COUNT)])
        self.assertEqual(narrower.search_width, 26)

    def test_done_day_boundary_with_a_column_either_side(self):
        at = flow_filter_row(55, [PROJECT, DAY], COUNT)
        wider = flow_filter_row(56, [PROJECT, DAY], COUNT)
        narrower = flow_filter_row(54, [PROJECT, DAY], COUNT)

        self.assertEqual(at.search_width, SEARCH_MIN_WIDTH)
        self.assertEqual(_shape(at)[0][0], (PROJECT, DAY))
        self.assertEqual(wider.search_width, SEARCH_MIN_WIDTH + 1)
        self.assertEqual(_shape(narrower)[0][0], (PROJECT,))
        self.assertEqual(narrower.search_width, 31)

    def test_box_takes_what_a_longer_value_leaves_at_the_same_width(self):
        short = flow_filter_row(80, [PROJECT], COUNT)
        long = flow_filter_row(80, [("PROJECT", "lightcycle-workflows")], COUNT)

        self.assertEqual(len(short.lines), len(long.lines))
        self.assertEqual(short.search_width, 46)
        self.assertEqual(long.search_width, 80 - 10 - 2 - 28 - 11)

    def test_segment_wider_than_a_line_is_truncated_not_dropped(self):
        layout = flow_filter_row(30, [("PROJECT", "x" * 60)], COUNT)

        (label, value), = layout.lines[1].segments
        self.assertEqual(label, "PROJECT")
        self.assertEqual(len(label) + 1 + len(value), 30)
        self.assertTrue(value.endswith("…"))
        self.assertEqual(layout.lines[-1].count, COUNT)

    def test_no_segments_and_no_count_is_the_search_box_alone(self):
        layout = flow_filter_row(80, [], None)

        self.assertEqual(_shape(layout), [((), None)])
        self.assertEqual(layout.search_width, 70)

    def test_zero_items_count_is_kept(self):
        layout = flow_filter_row(80, [PROJECT], "0 items")

        self.assertEqual(layout.lines[0].count, "0 items")

    def test_later_segments_follow_a_moved_one_even_if_they_would_fit(self):
        wide = ("PROJECT", "y" * 30)
        layout = flow_filter_row(60, [wide, ("DAY", "A"), ("X", "b")], None)

        self.assertEqual(_shape(layout)[0][0], ())
        self.assertEqual(_shape(layout)[1][0][0], wide)
