import datetime

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
    CURSOR_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    GLOBAL_SHORTCUTS,
)
from lightcycle.adapters.tui.priority_list import assemble_rows, build_priority_rows, is_gap_key
from lightcycle.application.pool import BreakerStatusUseCase, PoolRunningUseCase
from lightcycle.application.work import StatusUseCase

POLL_INTERVAL_SECONDS = 10

DATA_COLUMNS = ("cursor", "icon", "id", "project", "title", "step", "time")

EMPTY_STATE_MESSAGE = "Nothing needs attention. Nothing's active. Nothing's queued."


class StatusBar(Static):
    status_text = ""

    def report(self, *, running, is_open, reset_at):
        pool_text = "pool: running" if running else "pool: stopped"
        if is_open:
            breaker_text = "breaker: open (resets %s)" % reset_at
        else:
            breaker_text = "breaker: closed"
        self.status_text = "%s   %s" % (pool_text, breaker_text)
        self.update(self.status_text)


class TabStrip(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("Current work", id="tab-current-work", classes="tab-active")
        yield Static(" · ", classes="tab-separator")
        yield Static("Backlog", id="tab-backlog", classes="tab-dim")


class ShortcutBar(Horizontal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shortcuts = ()

    def set_shortcuts(self, shortcuts):
        self._shortcuts = tuple(shortcuts)
        for child in list(self.children):
            child.remove()
        for key, action in self._shortcuts:
            self.mount(Static(key, classes="shortcut-key"))
            self.mount(Static(action, classes="shortcut-action"))

    @property
    def shortcuts(self):
        return self._shortcuts


class DashboardFooter(Vertical):
    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        yield ShortcutBar(id="shortcut-bar")

    def on_mount(self) -> None:
        self.query_one(ShortcutBar).set_shortcuts(GLOBAL_SHORTCUTS)


class PriorityTable(DataTable):
    BINDINGS = DataTable.BINDINGS + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate) -> None:
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if old_coordinate.row != new_coordinate.row:
            self._paint_cursor_glyph(old_coordinate.row, False)
            self._paint_cursor_glyph(new_coordinate.row, True)

    def _paint_cursor_glyph(self, row_index, show) -> None:
        if row_index < 0 or row_index >= len(self.ordered_rows):
            return
        row_key = self.ordered_rows[row_index].key
        if row_key.value is None or is_gap_key(row_key.value):
            return
        value = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if show else ""
        try:
            self.update_cell(row_key, "cursor", value)
        except CellDoesNotExist:
            pass


class LightcycleApp(App):
    CSS = f"""
    Screen {{
        border: solid {COLOURS["border"]};
        background: {COLOURS["bg"]};
    }}

    TabStrip {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    TabStrip Static {{
        width: auto;
        height: 1;
    }}
    .tab-active {{
        color: {COLOURS["cyan"]};
        text-style: bold;
    }}
    .tab-dim {{
        color: {COLOURS["dim"]};
    }}
    .tab-separator {{
        color: {COLOURS["dim"]};
    }}

    DataTable > .datatable--cursor {{
        background: {COLOURS["selected-bg"]};
    }}

    #empty-state {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}

    DashboardFooter {{
        dock: bottom;
        height: 3;
        border-top: solid {COLOURS["border"]};
        background: {COLOURS["bg"]};
    }}
    StatusBar {{
        height: 1;
    }}
    ShortcutBar {{
        height: 1;
    }}
    ShortcutBar Static {{
        width: auto;
    }}
    .shortcut-key {{
        color: {COLOURS["text"]};
        text-style: bold;
        margin-right: 1;
    }}
    .shortcut-action {{
        color: {COLOURS["dim"]};
        margin-right: 2;
    }}
    """

    def __init__(self, container, now=None):
        super().__init__()
        self._container = container
        self._now = now or datetime.datetime.now
        self._last_shape = None
        self._last_attention_ids = None
        self._selected_flat_index = 0

    @property
    def container(self):
        return self._container

    def compose(self) -> ComposeResult:
        yield TabStrip(id="tab-strip")
        yield PriorityTable(id="priority-list")
        yield Static(EMPTY_STATE_MESSAGE, id="empty-state")
        yield DashboardFooter(id="footer")

    def on_mount(self) -> None:
        table = self.query_one(PriorityTable)
        table.cursor_type = "row"
        table.show_header = False
        self.call_after_refresh(self._refresh)
        self.set_interval(POLL_INTERVAL_SECONDS, self._refresh)

    def _refresh(self) -> None:
        lanes = StatusUseCase(self._container.store).execute().lanes
        now = self._now().isoformat()
        attention_rows, active_rows, queued_rows = build_priority_rows(
            self._container.store, lanes, now
        )
        shape = (
            tuple(r.id for r in attention_rows),
            tuple(r.id for r in active_rows),
            tuple(r.id for r in queued_rows),
        )
        rows = assemble_rows(attention_rows, active_rows, queued_rows)

        table = self.query_one(PriorityTable)
        self._toggle_empty_state(not rows)

        if shape == self._last_shape:
            self._update_cells(table, rows)
        else:
            self._rebuild_table(table, rows)
        had_prior_attention = self._last_attention_ids is not None
        newly_attention = set(shape[0]) - (self._last_attention_ids or set())
        self._last_shape = shape
        self._last_attention_ids = set(shape[0])
        if had_prior_attention and newly_attention:
            self.bell()

        running = PoolRunningUseCase(self._container.lock).execute().running
        breaker = BreakerStatusUseCase(self._container.breaker).execute()
        self.query_one(StatusBar).report(
            running=running, is_open=breaker.is_open, reset_at=breaker.reset_at
        )

    def _toggle_empty_state(self, empty) -> None:
        self.query_one(PriorityTable).display = not empty
        self.query_one("#empty-state", Static).display = empty

    def _title_width(self, table) -> int:
        grid = dict(COLUMN_GRIDS["priority-list"])
        padding = 2 * table.cell_padding * len(DATA_COLUMNS)
        fixed = sum(int(grid[key][:-2]) for key in DATA_COLUMNS if key != "title") + padding
        width = table.size.width - fixed
        return width if width > 0 else 1

    def _add_columns(self, table, title_width) -> None:
        grid = dict(COLUMN_GRIDS["priority-list"])
        for key in DATA_COLUMNS:
            width = title_width if key == "title" else int(grid[key][:-2])
            table.add_column(key, width=width, key=key)

    def _row_cells(self, row, cursor=False):
        if row.group == "gap":
            return ("", "", "", "", "", "", "")
        cursor_cell = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else ""
        icon_cell = Text(row.icon, style=COLOURS[row.icon_colour])
        if row.dependency_icon:
            icon_cell = icon_cell + Text(
                row.dependency_icon, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
            )
        step_cell = Text(row.step, style=COLOURS[row.step_colour])
        project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else ""
        time_cell = Text(row.time, style=COLOURS["dim"]) if row.time else ""
        return (cursor_cell, icon_cell, row.id, project_cell, row.title, step_cell, time_cell)

    def _update_cells(self, table, rows) -> None:
        for row in rows:
            if row.group == "gap":
                continue
            for key, value in zip(DATA_COLUMNS, self._row_cells(row)):
                if key == "cursor":
                    continue
                table.update_cell(row.id, key, value)

    def _selected_row_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        row_id = cell_key.row_key.value
        if row_id is None or is_gap_key(row_id):
            return None
        return row_id

    def _nearest_real_index(self, rows, index):
        if rows[index].group != "gap":
            return index
        i = index - 1
        while i >= 0:
            if rows[i].group != "gap":
                return i
            i -= 1
        i = index + 1
        while i < len(rows):
            if rows[i].group != "gap":
                return i
            i += 1
        return index

    def _rebuild_table(self, table, rows) -> None:
        has_prior = self._last_shape is not None
        selected_id = self._selected_row_id(table) if has_prior else None

        title_width = self._title_width(table)
        table.clear(columns=True)
        self._add_columns(table, title_width)

        new_index = 0
        if has_prior and rows:
            ids = [row.id for row in rows]
            if selected_id is not None and selected_id in ids:
                new_index = ids.index(selected_id)
            else:
                clamped = min(max(self._selected_flat_index, 0), len(rows) - 1)
                new_index = self._nearest_real_index(rows, clamped)

        for index, row in enumerate(rows):
            table.add_row(*self._row_cells(row, cursor=index == new_index), height=None, key=row.id)

        self._selected_flat_index = new_index
        if rows:
            table.move_cursor(row=new_index)


def run(container):
    LightcycleApp(container).run()
