
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle.adapters.tui.design_system import (
    COLOURS,
)
from lightcycle.adapters.tui.hub import _format_item_cost
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    compute_layout,
    floor_message,
    render_screen_row_budget,
    screen_row_budget_for,
)
from lightcycle.adapters.tui.views.tables import STACKED_COLUMN_KEY, _update_cell_if_changed, CursorGlyphTable
from lightcycle.adapters.tui.views.done import DONE_COLUMNS, DONE_CONTINUATION_INDENT, _done_row_cells, _done_stacked_cell_builder

AUTOMATION_EMPTY_MESSAGE = "No automation has run yet."


class AutomationTable(CursorGlyphTable):
    def on_resize(self, event: events.Resize) -> None:
        view = self.parent
        if isinstance(view, AutomationView):
            view.refresh_column_width()

    def on_show(self, event: events.Show) -> None:
        view = self.parent
        if isinstance(view, AutomationView):
            view.refresh_column_width()




class AutomationView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rows = ()
        self._floor = False
        self._last_shape = None
        self._needs_rebuild = False
        self._stacked = False

    def compose(self) -> ComposeResult:
        yield Static(id="automation-tally")
        yield AutomationTable(id="automation-table")
        yield Static(id="automation-floor")
        yield Static(AUTOMATION_EMPTY_MESSAGE, id="automation-empty")

    def on_mount(self) -> None:
        table = self.query_one(AutomationTable)
        table.cursor_type = "row"
        table.show_header = False

    def apply_response(self, response, rows) -> None:
        self.query_one("#automation-tally", Static).update(_automation_tally_text(response))
        shape = tuple(r.id for r in rows)
        layout = self._layout(self.query_one(AutomationTable), rows)
        if shape == self._last_shape and not self._needs_rebuild and layout.stacked == self._stacked:
            self._rows = rows
            self._update_cells(rows)
        else:
            self._rebuild_table(rows)
            self._last_shape = shape
        self._toggle_state()

    def refresh_column_width(self) -> None:
        self._rebuild_table(self._rows)
        self._toggle_state()

    def _selected_row_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def _layout(self, table, rows):
        atomic_values = {
            "id": [row.id for row in rows],
            "project": [row.project for row in rows],
            "cost": [row.cost for row in rows],
            "time": [row.time for row in rows],
        }
        row_budget = screen_row_budget_for(table, len(DONE_COLUMNS))
        return compute_layout(row_budget, ["cursor"], atomic_values, DONE_CONTINUATION_INDENT)

    def _rebuild_table(self, rows) -> None:
        self._rows = rows
        table = self.query_one(AutomationTable)
        layout = self._layout(table, rows)
        self._stacked = layout.stacked
        self._floor = bool(rows) and layout.floor
        if self._floor:
            self._needs_rebuild = True
            self.query_one("#automation-floor", Static).update(
                Text(floor_message(layout, table, len(DONE_COLUMNS)), style=COLOURS["dim"])
            )
            return
        self._needs_rebuild = False
        selected_id = self._selected_row_id(table)

        table.clear(columns=True)
        row_budget = render_screen_row_budget(table, layout, len(DONE_COLUMNS))
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {
                "cursor": GLYPH_WIDTHS["cursor"],
                "id": layout.atomic_widths["id"],
                "project": layout.atomic_widths["project"],
                "title": layout.flexible_width,
                "cost": layout.atomic_widths["cost"],
                "time": layout.atomic_widths["time"],
            }
            for key in DONE_COLUMNS:
                table.add_column(key, width=widths[key], key=key)

        ids = [row.id for row in rows]
        new_index = ids.index(selected_id) if selected_id in ids else 0
        table._stacked_mode = layout.stacked
        table._stacked_layout = layout
        table._stacked_row_budget = row_budget
        table._stacked_cell_builder = _done_stacked_cell_builder
        stacked_rows = {}
        for index, row in enumerate(rows):
            cells = _done_row_cells(row, layout, row_budget, cursor=index == new_index)
            if layout.stacked:
                stacked_rows[row.id] = (row, None)
            table.add_row(*cells, height=None, key=row.id)
        table._stacked_rows = stacked_rows
        if rows:
            table.move_cursor(row=new_index)

    def _update_cells(self, rows) -> None:
        table = self.query_one(AutomationTable)
        layout = self._layout(table, rows)
        row_budget = render_screen_row_budget(table, layout, len(DONE_COLUMNS))
        selected_id = self._selected_row_id(table)
        for row in rows:
            cells = _done_row_cells(row, layout, row_budget, cursor=(row.id == selected_id))
            if layout.stacked:
                _update_cell_if_changed(table, row.id, STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(DONE_COLUMNS, cells):
                if key == "cursor":
                    continue
                _update_cell_if_changed(table, row.id, key, value)

    def _toggle_state(self) -> None:
        empty = not self._rows
        showing_floor = self._floor
        self.query_one(AutomationTable).display = not empty and not showing_floor
        self.query_one("#automation-floor", Static).display = showing_floor
        self.query_one("#automation-empty", Static).display = empty

    @property
    def row_count(self) -> int:
        return len(self._rows)


def _automation_tally_text(response):
    lines = list(response.tallies) + [response.total]
    label_width = max(len(t.label) for t in lines)
    count_width = max(len(str(t.count)) for t in lines)
    text = Text()
    for index, tally in enumerate(lines):
        if index:
            text.append("\n")
        text.append(tally.label.ljust(label_width), style=COLOURS["dim"])
        text.append("  ")
        text.append(str(tally.count).rjust(count_width), style=COLOURS["text"])
        text.append("  ")
        text.append(_format_item_cost(tally.spend), style=COLOURS["text"])
    return text


