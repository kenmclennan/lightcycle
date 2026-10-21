
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle.adapters.tui.design_system import (
    COLOURS,
    CURSOR_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
)
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    compute_layout,
    floor_message,
    pad_atomic_field,
    pad_field,
    render_screen_row_budget,
    screen_row_budget_for,
    stacked_cell,
)
from lightcycle.adapters.tui.views.tables import STACKED_COLUMN_KEY, FilterBlock, _update_cell_if_changed, PagingTable, _repaint_stacked_cursor

BACKLOG_COLUMNS = ("cursor", "id", "project", "title")
BACKLOG_CONTINUATION_INDENT = GLYPH_WIDTHS["cursor"]


class BacklogTable(PagingTable):
    def on_resize(self, event: events.Resize) -> None:
        view = self.parent
        if isinstance(view, BacklogView):
            view.refresh_column_width()

    def on_show(self, event: events.Show) -> None:
        view = self.parent
        if isinstance(view, BacklogView):
            view.refresh_column_width()

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




def _backlog_stacked_first_line(row, cursor, layout):
    cursor_field = pad_field(
        Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else Text(""),
        GLYPH_WIDTHS["cursor"],
    )
    id_field = pad_atomic_field(row.id, layout.atomic_widths["id"])
    project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else Text("")
    project_field = pad_atomic_field(project_cell, layout.atomic_widths["project"])
    return cursor_field + id_field + project_field


def _backlog_title_prose(row):
    if not row.blocked_by:
        return row.title
    return "%s %s" % (DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph, row.title)


def _backlog_title_cell(row):
    if not row.blocked_by:
        return row.title
    glyph = Text(
        DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph + " ", style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
    )
    return glyph + Text(row.title)


def _backlog_row_cells(row, layout, row_budget, cursor=False):
    if layout.stacked:
        first_line = _backlog_stacked_first_line(row, cursor, layout)
        return (
            stacked_cell(
                first_line, BACKLOG_CONTINUATION_INDENT, _backlog_title_prose(row), row_budget
            ),
        )
    cursor_cell = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else ""
    project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else ""
    return (cursor_cell, row.id, project_cell, _backlog_title_cell(row))


def _backlog_stacked_cell_builder(row, layout, row_budget, cursor, icon_override):
    return _backlog_row_cells(row, layout, row_budget, cursor=cursor)


class BacklogFilterInput(Input):
    BINDINGS = [
        Binding("escape", "leave_filter", "Back", show=False),
        Binding("tab", "leave_filter", "Back", show=False),
        Binding("down", "leave_filter", "Results", show=False),
        Binding("up", "leave_filter", "Results", show=False),
        Binding("enter", "open_result", "Open", show=False),
    ]

    def action_leave_filter(self) -> None:
        if self.app._backlog_filter_timer is not None:
            self.app._backlog_filter_timer.stop()
            self.app._backlog_filter_timer = None
        self.app.set_focus(self.app.query_one(BacklogTable))
        self.app.stylesheet.update(self.app.screen, animate=False)
        self.app._sync_footer_shortcuts()

    def action_open_result(self) -> None:
        self.app.query_one(BacklogTable).action_select_cursor()


class BacklogView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rows = ()
        self._floor = False
        self._total = 0
        self._project_filter = None
        self._text_filter = None
        self._last_shape = None
        self._backlog_needs_rebuild = False
        self._backlog_stacked = False

    def compose(self) -> ComposeResult:
        yield FilterBlock(
            "backlog",
            BacklogFilterInput(id="backlog-filter-text", classes="search-input"),
            id="backlog-filter-block",
        )
        yield BacklogTable(id="backlog-table")
        yield Static(id="backlog-floor")
        yield Static(id="backlog-empty-overall")
        yield Static(id="backlog-empty-filtered-message")
        yield Static(id="backlog-empty-filtered-hint")

    def on_mount(self) -> None:
        table = self.query_one(BacklogTable)
        table.cursor_type = "row"
        table.show_header = False

    def apply_rows(self, rows, total, project_filter, text_filter) -> None:
        shape = (tuple(r.id for r in rows), total, project_filter, text_filter)
        self._render_filter_bar(project_filter, len(rows))
        table = self.query_one(BacklogTable)
        layout = self._layout(table)
        if (
            shape == self._last_shape
            and not self._backlog_needs_rebuild
            and layout.stacked == self._backlog_stacked
        ):
            self._update_cells(rows)
        else:
            self._rebuild_table(rows)
            self._last_shape = shape
        self._rows = rows
        self._total = total
        self._project_filter = project_filter
        self._text_filter = text_filter
        self._toggle_state(total, len(rows), project_filter, text_filter)

    def refresh_column_width(self) -> None:
        self._rebuild_table(self._rows)
        self._render_filter_bar(self._project_filter, len(self._rows))
        self._toggle_state(self._total, len(self._rows), self._project_filter, self._text_filter)

    def _render_filter_bar(self, project_filter, count) -> None:
        self.query_one("#backlog-filter-block", FilterBlock).reflow(
            [("PROJECT", project_filter or "All")], "%d items" % count
        )

    def _selected_row_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def _layout(self, table):
        atomic_values = {
            "id": [row.id for row in self._rows],
            "project": [row.project for row in self._rows],
        }
        row_budget = screen_row_budget_for(table, len(BACKLOG_COLUMNS))
        indent = BACKLOG_CONTINUATION_INDENT
        return compute_layout(row_budget, ["cursor"], atomic_values, indent)

    def _rebuild_table(self, rows) -> None:
        table = self.query_one(BacklogTable)
        layout = self._layout(table)
        self._backlog_stacked = layout.stacked
        self._floor = bool(rows) and layout.floor
        floor_widget = self.query_one("#backlog-floor", Static)
        if self._floor:
            self._backlog_needs_rebuild = True
            floor_widget.update(
                Text(floor_message(layout, table, len(BACKLOG_COLUMNS)), style=COLOURS["dim"])
            )
            return
        self._backlog_needs_rebuild = False
        selected_id = self._selected_row_id(table)

        table.clear(columns=True)
        row_budget = render_screen_row_budget(table, layout, len(BACKLOG_COLUMNS))
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {
                "cursor": GLYPH_WIDTHS["cursor"],
                "id": layout.atomic_widths["id"],
                "project": layout.atomic_widths["project"],
                "title": layout.flexible_width,
            }
            for key in BACKLOG_COLUMNS:
                table.add_column(key, width=widths[key], key=key)

        ids = [row.id for row in rows]
        new_index = ids.index(selected_id) if selected_id in ids else 0
        table._stacked_mode = layout.stacked
        table._stacked_layout = layout
        table._stacked_row_budget = row_budget
        table._stacked_cell_builder = _backlog_stacked_cell_builder
        stacked_rows = {}
        for index, row in enumerate(rows):
            is_cursor = index == new_index
            cells = _backlog_row_cells(row, layout, row_budget, cursor=is_cursor)
            if layout.stacked:
                stacked_rows[row.id] = (row, None)
            table.add_row(*cells, height=None, key=row.id)
        table._stacked_rows = stacked_rows
        if rows:
            table.move_cursor(row=new_index)

    def _update_cells(self, rows) -> None:
        table = self.query_one(BacklogTable)
        layout = self._layout(table)
        row_budget = render_screen_row_budget(table, layout, len(BACKLOG_COLUMNS))
        selected_id = self._selected_row_id(table)
        for row in rows:
            cells = _backlog_row_cells(row, layout, row_budget, cursor=(row.id == selected_id))
            if layout.stacked:
                _update_cell_if_changed(table, row.id, STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(BACKLOG_COLUMNS, cells):
                if key == "cursor":
                    continue
                _update_cell_if_changed(table, row.id, key, value)

    def _toggle_state(self, total, filtered_count, project_filter, text_filter) -> None:
        overall_empty = total == 0
        filtered_empty = not overall_empty and filtered_count == 0
        table = self.query_one(BacklogTable)
        showing_floor = self._floor and filtered_count > 0
        table.display = filtered_count > 0 and not showing_floor
        self.query_one("#backlog-floor", Static).display = showing_floor
        overall_widget = self.query_one("#backlog-empty-overall", Static)
        message_widget = self.query_one("#backlog-empty-filtered-message", Static)
        hint_widget = self.query_one("#backlog-empty-filtered-hint", Static)
        overall_widget.display = overall_empty
        message_widget.display = filtered_empty
        hint_widget.display = filtered_empty
        if overall_empty:
            overall_widget.update(Text("Nothing in the backlog.", style=COLOURS["dim"]))
        elif filtered_empty:
            message = Text("No backlog items", style=COLOURS["dim"])
            hints = []
            if project_filter:
                message.append(" for ", style=COLOURS["dim"])
                message.append(project_filter, style=COLOURS["text"])
                hints.append("f to check All")
            if text_filter:
                message.append(' matching "', style=COLOURS["dim"])
                message.append(text_filter, style=COLOURS["text"])
                message.append('"', style=COLOURS["dim"])
                hints.append("backspace to clear the search")
            message.append(".", style=COLOURS["dim"])
            message_widget.update(message)
            hint_widget.update(Text("Press %s." % ", or ".join(hints), style=COLOURS["dim"]))


