
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
)
from lightcycle.application.work.done import (
    CATEGORY_ALL,
    CATEGORY_AUTOMATION,
    CATEGORY_NO_AUTOMATION,
)
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    compute_layout,
    floor_message,
    pad_atomic_field,
    pad_field,
    pad_field_right,
    render_screen_row_budget,
    screen_row_budget_for,
    stacked_cell,
)
from lightcycle.adapters.tui.views.tables import STACKED_COLUMN_KEY, FilterBlock, _update_cell_if_changed, CursorGlyphTable

DONE_COLUMNS = ("cursor", "id", "project", "title", "cost", "time")
DONE_CONTINUATION_INDENT = GLYPH_WIDTHS["cursor"]


class DoneTable(CursorGlyphTable):
    def on_resize(self, event: events.Resize) -> None:
        view = self.parent
        if isinstance(view, DoneView):
            view.refresh_column_width()

    def on_show(self, event: events.Show) -> None:
        view = self.parent
        if isinstance(view, DoneView):
            view.refresh_column_width()




def _done_stacked_first_line(row, cursor, layout, row_budget):
    cursor_field = pad_field(
        Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else Text(""),
        GLYPH_WIDTHS["cursor"],
    )
    id_field = pad_atomic_field(row.id, layout.atomic_widths["id"])
    project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else Text("")
    project_field = pad_atomic_field(project_cell, layout.atomic_widths["project"])
    cost_field = pad_atomic_field(
        Text(row.cost, style=COLOURS["dim"]) if row.cost else Text(""), layout.atomic_widths["cost"]
    )
    content_so_far = cursor_field + id_field + project_field + cost_field
    time_cell = Text(row.time, style=COLOURS["dim"]) if row.time else Text("")
    time_area = max(0, row_budget - len(content_so_far.plain))
    return content_so_far + pad_field_right(time_cell, time_area)


def _done_row_cells(row, layout, row_budget, cursor=False):
    if layout.stacked:
        first_line = _done_stacked_first_line(row, cursor, layout, row_budget)
        return (stacked_cell(first_line, DONE_CONTINUATION_INDENT, row.title, row_budget),)
    cursor_cell = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else ""
    project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else ""
    cost_cell = Text(row.cost, style=COLOURS["dim"]) if row.cost else ""
    time_cell = Text(row.time, style=COLOURS["dim"]) if row.time else ""
    return (cursor_cell, row.id, project_cell, row.title, cost_cell, time_cell)


def _done_stacked_cell_builder(row, layout, row_budget, cursor, icon_override):
    return _done_row_cells(row, layout, row_budget, cursor=cursor)




class DoneFilterInput(Input):
    BINDINGS = [
        Binding("escape", "leave_filter", "Back", show=False),
        Binding("tab", "leave_filter", "Back", show=False),
        Binding("down", "leave_filter", "Results", show=False),
        Binding("up", "leave_filter", "Results", show=False),
        Binding("enter", "open_result", "Open", show=False),
    ]

    def action_leave_filter(self) -> None:
        if self.app._done_filter_timer is not None:
            self.app._done_filter_timer.stop()
            self.app._done_filter_timer = None
        self.app.set_focus(self.app.query_one(DoneTable))
        self.app.stylesheet.update(self.app.screen, animate=False)
        self.app._sync_footer_shortcuts()

    def action_open_result(self) -> None:
        self.app.query_one(DoneTable).action_select_cursor()


CATEGORY_LABELS = {
    CATEGORY_ALL: "All",
    CATEGORY_NO_AUTOMATION: "All (no automation)",
    CATEGORY_AUTOMATION: "Automations",
}


def _scope(project_filter, category):
    if project_filter:
        return project_filter
    if category != CATEGORY_NO_AUTOMATION:
        return CATEGORY_LABELS[category]
    return None


class DoneView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rows = ()
        self._floor = False
        self._total = 0
        self._project_filter = None
        self._category = CATEGORY_NO_AUTOMATION
        self._text_filter = None
        self._day_filter = None
        self._last_shape = None
        self._backlog_needs_rebuild = False
        self._backlog_stacked = False

    def compose(self) -> ComposeResult:
        yield FilterBlock(
            "done",
            DoneFilterInput(id="done-filter-text", classes="search-input"),
            id="done-filter-block",
        )
        yield DoneTable(id="done-table")
        yield Static(id="done-floor")
        yield Static(id="done-empty-overall")
        yield Static(id="done-empty-filtered-message")
        yield Static(id="done-empty-filtered-hint")

    def on_mount(self) -> None:
        table = self.query_one(DoneTable)
        table.cursor_type = "row"
        table.show_header = False

    def apply_rows(
        self, rows, total, project_filter, text_filter, day_filter, category=CATEGORY_NO_AUTOMATION,
    ) -> None:
        shape = (tuple(r.id for r in rows), total, project_filter, category, text_filter, day_filter)
        self._render_filter_bar(project_filter, day_filter, len(rows), category)
        table = self.query_one(DoneTable)
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
        self._category = category
        self._text_filter = text_filter
        self._day_filter = day_filter
        self._toggle_state(total, len(rows), _scope(project_filter, category), text_filter, day_filter)

    def refresh_column_width(self) -> None:
        self._rebuild_table(self._rows)
        self._render_filter_bar(self._project_filter, self._day_filter, len(self._rows), self._category)
        self._toggle_state(
            self._total, len(self._rows), _scope(self._project_filter, self._category),
            self._text_filter, self._day_filter,
        )

    def _render_filter_bar(self, project_filter, day_filter, count, category=CATEGORY_NO_AUTOMATION) -> None:
        self.query_one("#done-filter-block", FilterBlock).reflow(
            [
                ("PROJECT", project_filter or CATEGORY_LABELS[category]),
                ("DAY", day_filter.isoformat() if day_filter else "All"),
            ],
            "%d items" % count,
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
            "cost": [row.cost for row in self._rows],
            "time": [row.time for row in self._rows],
        }
        row_budget = screen_row_budget_for(table, len(DONE_COLUMNS))
        indent = DONE_CONTINUATION_INDENT
        return compute_layout(row_budget, ["cursor"], atomic_values, indent)

    def _rebuild_table(self, rows) -> None:
        table = self.query_one(DoneTable)
        layout = self._layout(table)
        self._backlog_stacked = layout.stacked
        self._floor = bool(rows) and layout.floor
        floor_widget = self.query_one("#done-floor", Static)
        if self._floor:
            self._backlog_needs_rebuild = True
            floor_widget.update(
                Text(floor_message(layout, table, len(DONE_COLUMNS)), style=COLOURS["dim"])
            )
            return
        self._backlog_needs_rebuild = False
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
            is_cursor = index == new_index
            cells = _done_row_cells(row, layout, row_budget, cursor=is_cursor)
            if layout.stacked:
                stacked_rows[row.id] = (row, None)
            table.add_row(*cells, height=None, key=row.id)
        table._stacked_rows = stacked_rows
        if rows:
            table.move_cursor(row=new_index)

    def _update_cells(self, rows) -> None:
        table = self.query_one(DoneTable)
        layout = self._layout(table)
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

    def _toggle_state(self, total, filtered_count, project_filter, text_filter, day_filter) -> None:
        overall_empty = total == 0
        filtered_empty = not overall_empty and filtered_count == 0
        table = self.query_one(DoneTable)
        showing_floor = self._floor and filtered_count > 0
        table.display = filtered_count > 0 and not showing_floor
        self.query_one("#done-floor", Static).display = showing_floor
        overall_widget = self.query_one("#done-empty-overall", Static)
        message_widget = self.query_one("#done-empty-filtered-message", Static)
        hint_widget = self.query_one("#done-empty-filtered-hint", Static)
        overall_widget.display = overall_empty
        message_widget.display = filtered_empty
        hint_widget.display = filtered_empty
        if overall_empty:
            overall_widget.update(Text("Nothing is done yet.", style=COLOURS["dim"]))
        elif filtered_empty:
            message = Text("No done items", style=COLOURS["dim"])
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
            if day_filter:
                message.append(" on ", style=COLOURS["dim"])
                message.append(day_filter.isoformat(), style=COLOURS["text"])
                hints.append("d to check All days")
            message.append(".", style=COLOURS["dim"])
            message_widget.update(message)
            hint_widget.update(Text("Press %s." % ", or ".join(hints), style=COLOURS["dim"]))


