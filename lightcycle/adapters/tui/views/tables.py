
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle.adapters.tui.design_system import (
    COLOURS,
    CURSOR_GLYPH,
)
from lightcycle.adapters.tui.filter_row import FILTER_ROW_GAP, flow_filter_row, segment_width

STACKED_COLUMN_KEY = "row"


class FilterLineRest(Static):
    pass


class FilterBlock(Vertical):
    def __init__(self, prefix, search_input, **kwargs) -> None:
        super().__init__(**kwargs)
        self._prefix = prefix
        self._search_input = search_input

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("SEARCH", id=f"{self._prefix}-search-label", classes="filter-row-label"),
            self._search_input,
            Static(id=f"{self._prefix}-filter-line-one", classes="filter-line-one"),
            id=f"{self._prefix}-search-bar",
            classes="search-bar",
        )
        yield FilterLineRest(id=f"{self._prefix}-filter-line-rest")

    def reflow(self, segments, count_text) -> None:
        width = self.screen.size.width
        layout = flow_filter_row(width, segments, count_text)
        first, *rest = layout.lines
        line_one = Text()
        for segment in first.segments:
            line_one.append(" " * FILTER_ROW_GAP)
            self._append_segment(line_one, segment)
        if first.count:
            line_one.append(" " * FILTER_ROW_GAP)
            line_one.append(first.count, style=COLOURS["text"])
        self.query_one(f"#{self._prefix}-filter-line-one", Static).update(line_one)
        line_rest = Text()
        for index, line in enumerate(rest):
            if index:
                line_rest.append("\n")
            used = 0
            for position, segment in enumerate(line.segments):
                if position:
                    line_rest.append(" " * FILTER_ROW_GAP)
                    used += FILTER_ROW_GAP
                self._append_segment(line_rest, segment)
                used += segment_width(segment)
            if line.count:
                line_rest.append(" " * max(width - used - len(line.count), 0))
                line_rest.append(line.count, style=COLOURS["text"])
        self.query_one(FilterLineRest).update(line_rest)
        self.query_one(FilterLineRest).display = bool(rest)

    @staticmethod
    def _append_segment(text, segment) -> None:
        label, value = segment
        text.append(label, style=COLOURS["dim"])
        text.append(" ")
        text.append(value, style=COLOURS["text"])



def _update_cell_if_changed(table, row_key, column_key, value) -> None:
    if table.get_cell(row_key, column_key) == value:
        return
    table.update_cell(row_key, column_key, value)


class PagingTable(DataTable):
    _BASE_BINDINGS = [b for b in DataTable.BINDINGS if b.key != "right"]

    BINDINGS = _BASE_BINDINGS + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("right", "select_cursor", "Open", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)



class CursorGlyphTable(PagingTable):
    def watch_cursor_coordinate(self, old_coordinate, new_coordinate) -> None:
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if old_coordinate.row != new_coordinate.row:
            self._paint_cursor_glyph(old_coordinate.row, False)
            self._paint_cursor_glyph(new_coordinate.row, True)

    def _paint_cursor_glyph(self, row_index, show) -> None:
        if row_index < 0 or row_index >= len(self.ordered_rows):
            return
        row_key = self.ordered_rows[row_index].key
        if getattr(self, "_stacked_mode", False):
            _repaint_stacked_cursor(self, row_key, show)
            return
        value = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if show else ""
        try:
            _update_cell_if_changed(self, row_key, "cursor", value)
        except CellDoesNotExist:
            pass




def _repaint_stacked_cursor(table, row_key, show) -> None:
    entry = getattr(table, "_stacked_rows", {}).get(row_key.value)
    if entry is None:
        return
    row, icon_override = entry
    cells = table._stacked_cell_builder(
        row, table._stacked_layout, table._stacked_row_budget, show, icon_override
    )
    try:
        _update_cell_if_changed(table, row_key, STACKED_COLUMN_KEY, cells[0])
    except CellDoesNotExist:
        pass


