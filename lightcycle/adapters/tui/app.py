import datetime
import time

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Input, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle.adapters.tui.backlog_list import build_backlog_rows
from lightcycle.adapters.tui.design_system import (
    ACTIVE_GLYPH_FRAMES,
    ACTIVE_GLYPH_REST_INDEX,
    ACTIVE_GLYPH_TICKS_PER_SECOND,
    BACKLOG_EMPTY_SHORTCUTS,
    BACKLOG_FILTERED_EMPTY_SHORTCUTS,
    BACKLOG_SEARCH_EMPTY_SHORTCUTS,
    BACKLOG_SEARCH_SHORTCUTS,
    BACKLOG_SHORTCUTS,
    COLOURS,
    COLUMN_GRIDS,
    CURSOR_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    DONE_EMPTY_SHORTCUTS,
    DONE_FILTERED_EMPTY_SHORTCUTS,
    DONE_SEARCH_EMPTY_SHORTCUTS,
    DONE_SEARCH_SHORTCUTS,
    DONE_SHORTCUTS,
    GLOBAL_SHORTCUTS,
    MODAL_OVERLAY_ALPHA,
    STATS_SHORTCUTS,
    next_active_glyph_frame,
)
from lightcycle.adapters.tui.done_list import build_done_rows
from lightcycle.adapters.tui.footer import DashboardFooter, ShortcutBar, StatusBar
from lightcycle.adapters.tui.hub import NodeHubScreen, _format_item_cost
from lightcycle.adapters.tui.priority_list import assemble_rows, build_priority_rows
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    apply_widths,
    atomic_column_width,
    compute_layout,
    floor_message,
    pad_atomic_field,
    pad_field,
    pad_field_right,
    render_screen_row_budget,
    screen_row_budget_for,
    stacked_cell,
)
from lightcycle.application.pool import (
    BreakerStatusUseCase,
    LiveWorkerCountUseCase,
    PoolHoldStatusUseCase,
    PoolRunningUseCase,
    StartPoolUseCase,
    StopPoolSignalUseCase,
)
from lightcycle.application.setup import UpgradeNoticeUseCase, upgrade
from lightcycle.application.work import (
    BacklogInput,
    BacklogUseCase,
    DoneInput,
    DoneUseCase,
    StatsInput,
    StatsUseCase,
    StatusUseCase,
)
from lightcycle.ports.workers import RegistryUnreadable

POLL_INTERVAL_SECONDS = 10
FILTER_DEBOUNCE_SECONDS = 0.15
POOL_TRANSITION_POLL_SECONDS = 1
POOL_START_TIMEOUT_SECONDS = 15

DATA_COLUMNS = ("cursor", "icon", "id", "project", "title", "step", "cost", "time")
BACKLOG_COLUMNS = ("cursor", "id", "project", "title")
DONE_COLUMNS = ("cursor", "id", "project", "title", "cost", "time")
STATS_COLUMNS = COLUMN_GRIDS["stats"]

EMPTY_STATE_MESSAGE = "Nothing needs attention. Nothing's active. Nothing's queued."

PICKER_CANCELLED = object()

POOL_PROMPT_CANCELLED = object()
POOL_PROMPT_STOP = "stop"
POOL_PROMPT_QUIT_LEAVE = "quit-leave"
POOL_PROMPT_QUIT_STOP = "quit-stop"
POOL_PROMPT_MIN_WIDTH = 52

_VIEW_CYCLE = ("priority", "backlog", "done", "stats")

STACKED_COLUMN_KEY = "row"
PRIORITY_CONTINUATION_INDENT = GLYPH_WIDTHS["cursor"] + GLYPH_WIDTHS["icon"]
BACKLOG_CONTINUATION_INDENT = GLYPH_WIDTHS["cursor"]
DONE_CONTINUATION_INDENT = GLYPH_WIDTHS["cursor"]
STATS_CONTINUATION_INDENT = 2

FILTER_ROW_LABEL_WIDTH = 10
FILTER_ROW_COUNT_GAP = 2


class TabStrip(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("Current work", id="tab-current-work", classes="tab-active")
        yield Static(" · ", classes="tab-separator")
        yield Static("Backlog", id="tab-backlog", classes="tab-dim")
        yield Static(" · ", classes="tab-separator")
        yield Static("Done", id="tab-done", classes="tab-dim")
        yield Static(" · ", classes="tab-separator")
        yield Static("Stats", id="tab-stats", classes="tab-dim")

    def set_active(self, view) -> None:
        widgets = {
            "priority": self.query_one("#tab-current-work", Static),
            "backlog": self.query_one("#tab-backlog", Static),
            "done": self.query_one("#tab-done", Static),
            "stats": self.query_one("#tab-stats", Static),
        }
        for key, widget in widgets.items():
            widget.set_class(key == view, "tab-active")
            widget.set_class(key != view, "tab-dim")


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


class PriorityTable(PagingTable):
    def on_resize(self, event: events.Resize) -> None:
        app = self.app
        if isinstance(app, LightcycleApp):
            app.refresh_priority_layout()

    def on_show(self, event: events.Show) -> None:
        app = self.app
        if isinstance(app, LightcycleApp):
            app.refresh_priority_layout()

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate) -> None:
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if old_coordinate.row != new_coordinate.row:
            self._paint_cursor_glyph(old_coordinate.row, False)
            self._paint_cursor_glyph(new_coordinate.row, True)

    def _paint_cursor_glyph(self, row_index, show) -> None:
        if row_index < 0 or row_index >= len(self.ordered_rows):
            return
        row_key = self.ordered_rows[row_index].key
        if row_key.value is None:
            return
        if getattr(self, "_stacked_mode", False):
            _repaint_stacked_cursor(self, row_key, show)
            return
        value = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if show else ""
        try:
            self.update_cell(row_key, "cursor", value)
        except CellDoesNotExist:
            pass


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
            self.update_cell(row_key, "cursor", value)
        except CellDoesNotExist:
            pass


class DoneTable(PagingTable):
    def on_resize(self, event: events.Resize) -> None:
        view = self.parent
        if isinstance(view, DoneView):
            view.refresh_column_width()

    def on_show(self, event: events.Show) -> None:
        view = self.parent
        if isinstance(view, DoneView):
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
            self.update_cell(row_key, "cursor", value)
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
        table.update_cell(row_key, STACKED_COLUMN_KEY, cells[0])
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


def _backlog_row_cells(row, layout, row_budget, cursor=False):
    if layout.stacked:
        first_line = _backlog_stacked_first_line(row, cursor, layout)
        return (stacked_cell(first_line, BACKLOG_CONTINUATION_INDENT, row.title, row_budget),)
    cursor_cell = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else ""
    project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else ""
    return (cursor_cell, row.id, project_cell, row.title)


def _backlog_stacked_cell_builder(row, layout, row_budget, cursor, icon_override):
    return _backlog_row_cells(row, layout, row_budget, cursor=cursor)


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
        yield Horizontal(
            Static("SEARCH", id="backlog-search-label", classes="filter-row-label"),
            BacklogFilterInput(id="backlog-filter-text"),
            id="backlog-search-bar",
        )
        yield Horizontal(
            Static("PROJECT", id="backlog-filter-label", classes="filter-row-label"),
            Static(id="backlog-filter-left"),
            Static(id="backlog-filter-right"),
            id="backlog-filter-bar",
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
        value = project_filter or "All"
        count_text = "%d items" % count
        left = self.query_one("#backlog-filter-left", Static)
        right = self.query_one("#backlog-filter-right", Static)
        left.update(Text(value, style=COLOURS["text"]))
        available = self.screen.size.width
        fits = FILTER_ROW_LABEL_WIDTH + len(value) + FILTER_ROW_COUNT_GAP + len(count_text) <= available
        right.display = fits
        if fits:
            right.update(Text(count_text, style=COLOURS["text"]))

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
                table.update_cell(row.id, STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(BACKLOG_COLUMNS, cells):
                if key == "cursor":
                    continue
                table.update_cell(row.id, key, value)

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


class DoneView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rows = ()
        self._floor = False
        self._total = 0
        self._project_filter = None
        self._text_filter = None
        self._day_filter = None
        self._last_shape = None
        self._backlog_needs_rebuild = False
        self._backlog_stacked = False

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("SEARCH", id="done-search-label", classes="filter-row-label"),
            DoneFilterInput(id="done-filter-text"),
            id="done-search-bar",
        )
        yield Horizontal(
            Static("PROJECT", id="done-filter-label", classes="filter-row-label"),
            Static(id="done-filter-left"),
            Static(id="done-filter-right"),
            id="done-filter-bar",
        )
        yield Horizontal(
            Static("DAY", id="done-day-filter-label", classes="filter-row-label"),
            Static(id="done-day-filter-left"),
            Static(id="done-day-filter-right"),
            id="done-day-filter-bar",
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

    def apply_rows(self, rows, total, project_filter, text_filter, day_filter) -> None:
        shape = (tuple(r.id for r in rows), total, project_filter, text_filter, day_filter)
        self._render_filter_bar(project_filter, len(rows))
        self._render_day_filter_bar(day_filter)
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
        self._text_filter = text_filter
        self._day_filter = day_filter
        self._toggle_state(total, len(rows), project_filter, text_filter, day_filter)

    def refresh_column_width(self) -> None:
        self._rebuild_table(self._rows)
        self._render_filter_bar(self._project_filter, len(self._rows))
        self._render_day_filter_bar(self._day_filter)
        self._toggle_state(
            self._total, len(self._rows), self._project_filter, self._text_filter, self._day_filter
        )

    def _render_filter_bar(self, project_filter, count) -> None:
        value = project_filter or "All"
        count_text = "%d items" % count
        left = self.query_one("#done-filter-left", Static)
        right = self.query_one("#done-filter-right", Static)
        left.update(Text(value, style=COLOURS["text"]))
        available = self.screen.size.width
        fits = FILTER_ROW_LABEL_WIDTH + len(value) + FILTER_ROW_COUNT_GAP + len(count_text) <= available
        right.display = fits
        if fits:
            right.update(Text(count_text, style=COLOURS["text"]))

    def _render_day_filter_bar(self, day_filter) -> None:
        value = day_filter.isoformat() if day_filter else "All"
        left = self.query_one("#done-day-filter-left", Static)
        right = self.query_one("#done-day-filter-right", Static)
        left.update(Text(value, style=COLOURS["text"]))
        right.display = False

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
                table.update_cell(row.id, STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(DONE_COLUMNS, cells):
                if key == "cursor":
                    continue
                table.update_cell(row.id, key, value)

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


def _stats_rows(response):
    delta = response.backlog_delta
    delta_text = "+%d" % delta if delta >= 0 else str(delta)
    return (
        ("Items Completed", str(response.completed)),
        ("Items Closed", str(response.completed + response.abandoned)),
        ("Spend", _format_item_cost(response.spend)),
        ("Escalations", str(response.escalations)),
        ("Audits", str(response.audits)),
        ("Backlog Size", str(response.backlog_size)),
        ("Backlog Delta", delta_text),
    )


def _stats_row_cells(field, layout, row_budget):
    key, value = field
    if layout.stacked:
        key_field = pad_field(Text(key, style=COLOURS["dim"]), layout.atomic_widths["key"])
        return (
            stacked_cell(key_field, STATS_CONTINUATION_INDENT, value, row_budget, prose_style=COLOURS["text"]),
        )
    return (Text(key, style=COLOURS["dim"]), Text(value, style=COLOURS["text"]))


class StatsTable(PagingTable):
    def on_resize(self, event: events.Resize) -> None:
        view = self.parent
        if isinstance(view, StatsView):
            view.refresh_column_width()

    def on_show(self, event: events.Show) -> None:
        view = self.parent
        if isinstance(view, StatsView):
            view.refresh_column_width()


class StatsView(Vertical):
    can_focus = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._day = None
        self._rows = ()
        self._floor = False
        self._stats_stacked = False

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("DAY", id="stats-day-filter-label", classes="filter-row-label"),
            Static(id="stats-day-filter-left"),
            Static(id="stats-day-filter-right"),
            id="stats-day-filter-bar",
        )
        yield StatsTable(id="stats-table")
        yield Static(id="stats-floor")

    def on_mount(self) -> None:
        table = self.query_one(StatsTable)
        table.cursor_type = "none"
        table.show_header = False
        table.display = False

    def apply_stats(self, response) -> None:
        self._day = response.day
        self.query_one("#stats-day-filter-left", Static).update(
            Text(response.day.isoformat(), style=COLOURS["text"])
        )
        self.query_one("#stats-day-filter-right", Static).display = False
        self._rebuild_table(_stats_rows(response))

    def refresh_column_width(self) -> None:
        self._rebuild_table(self._rows)

    def _layout(self, table):
        atomic_values = {"key": [key for key, _value in self._rows]}
        row_budget = screen_row_budget_for(table, len(STATS_COLUMNS))
        return compute_layout(row_budget, [], atomic_values, indent=STATS_CONTINUATION_INDENT)

    def _rebuild_table(self, rows) -> None:
        table = self.query_one(StatsTable)
        self._rows = rows
        layout = self._layout(table)
        self._stats_stacked = layout.stacked
        self._floor = layout.floor
        floor_widget = self.query_one("#stats-floor", Static)
        if self._floor:
            table.display = False
            floor_widget.display = True
            floor_widget.update(
                Text(floor_message(layout, table, len(STATS_COLUMNS)), style=COLOURS["dim"])
            )
            return
        table.display = True
        floor_widget.display = False

        table.clear(columns=True)
        row_budget = render_screen_row_budget(table, layout, len(STATS_COLUMNS))
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {"key": layout.atomic_widths["key"], "value": layout.flexible_width}
            for key in STATS_COLUMNS:
                table.add_column(key, width=widths[key], key=key)

        for field in rows:
            table.add_row(*_stats_row_cells(field, layout, row_budget), height=None, key=field[0])


PICKER_MIN_WIDTH = 40
PICKER_BORDER_WIDTH = 2
PICKER_PADDING_WIDTH = 2
PICKER_CURSOR_PREFIX_WIDTH = 2
PICKER_COLUMN_GAP = 1


class ProjectFilterPicker(ModalScreen):
    CSS = f"""
    ProjectFilterPicker {{
        align: center top;
        background: {COLOURS["bg"]} {int(MODAL_OVERLAY_ALPHA * 100)}%;
        border: none;
    }}
    #picker {{
        width: {PICKER_MIN_WIDTH};
        height: auto;
        margin-top: 4;
        background: {COLOURS["panel"]};
        border: solid {COLOURS["cyan"]};
    }}
    #picker-head {{
        height: 2;
        padding: 0 1;
        color: {COLOURS["cyan"]};
        border-bottom: solid {COLOURS["border"]};
    }}
    .picker-option {{
        height: 1;
        padding: 0 1;
    }}
    #picker-option-label {{
        width: 1fr;
    }}
    .picker-option-count {{
        content-align: right middle;
        color: {COLOURS["dim"]};
    }}
    .picker-option-selected {{
        background: {COLOURS["selected-bg"]};
    }}
    #picker-foot {{
        height: 2;
        padding: 0 1;
        color: {COLOURS["dim"]};
        border-top: solid {COLOURS["border"]};
    }}
    """

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "apply", "Apply", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, options, heading="Filter by project"):
        super().__init__()
        self._options = options
        self._heading = heading
        self._index = 0
        self._count_width = max(
            1, atomic_column_width([str(count) for _, _, count in options])
        )
        label_width = atomic_column_width([label for _, label, _ in options])
        computed_width = (
            PICKER_BORDER_WIDTH
            + PICKER_PADDING_WIDTH
            + PICKER_CURSOR_PREFIX_WIDTH
            + label_width
            + PICKER_COLUMN_GAP
            + self._count_width
        )
        self._picker_width = max(computed_width, PICKER_MIN_WIDTH)

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static(self._heading, id="picker-head")
            for index, (_, label, count) in enumerate(self._options):
                yield PickerOption(label, count, self._count_width, id="picker-option-%d" % index)
            yield Static("↑↓ move · enter apply · esc cancel", id="picker-foot")

    def on_mount(self) -> None:
        self.query_one("#picker").styles.width = self._picker_width
        self._paint_highlight()

    def _paint_highlight(self) -> None:
        for index, option in enumerate(self.query(PickerOption)):
            option.set_highlighted(index == self._index)

    def action_move_down(self) -> None:
        self._index = min(self._index + 1, len(self._options) - 1)
        self._paint_highlight()

    def action_move_up(self) -> None:
        self._index = max(self._index - 1, 0)
        self._paint_highlight()

    def action_apply(self) -> None:
        self.dismiss(self._options[self._index][0])

    def action_cancel(self) -> None:
        self.dismiss(PICKER_CANCELLED)


class PoolPromptScreen(ModalScreen):
    CSS = f"""
    PoolPromptScreen {{
        align: center top;
        background: {COLOURS["bg"]} {int(MODAL_OVERLAY_ALPHA * 100)}%;
        border: none;
    }}
    #pool-prompt {{
        width: {POOL_PROMPT_MIN_WIDTH};
        height: auto;
        margin-top: 4;
        background: {COLOURS["panel"]};
        border: solid {COLOURS["cyan"]};
    }}
    #pool-prompt-head {{
        height: 1;
        padding: 0 1;
        color: {COLOURS["cyan"]};
    }}
    #pool-prompt-body {{
        height: auto;
        padding: 0 1;
        color: {COLOURS["text"]};
        border-bottom: solid {COLOURS["border"]};
    }}
    .pool-prompt-option {{
        height: 1;
        padding: 0 1;
    }}
    .pool-prompt-option-selected {{
        background: {COLOURS["selected-bg"]};
    }}
    #pool-prompt-foot {{
        height: 2;
        padding: 0 1;
        color: {COLOURS["dim"]};
        border-top: solid {COLOURS["border"]};
    }}
    """

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "apply", "Apply", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, heading, body, options):
        super().__init__()
        self._heading = heading
        self._body = body
        self._options = options
        self._index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="pool-prompt"):
            yield Static(self._heading, id="pool-prompt-head")
            yield Static(self._body, id="pool-prompt-body")
            for index, (_, label) in enumerate(self._options):
                yield Static(label, classes="pool-prompt-option", id="pool-prompt-option-%d" % index)
            yield Static("↑↓ move · enter apply · esc cancel", id="pool-prompt-foot")

    def on_mount(self) -> None:
        self._paint_highlight()

    def _paint_highlight(self) -> None:
        for index, option in enumerate(self.query(".pool-prompt-option")):
            option.set_class(index == self._index, "pool-prompt-option-selected")
            option.update("%s %s" % (
                CURSOR_GLYPH.glyph if index == self._index else " ", self._options[index][1]))

    def action_move_down(self) -> None:
        self._index = min(self._index + 1, len(self._options) - 1)
        self._paint_highlight()

    def action_move_up(self) -> None:
        self._index = max(self._index - 1, 0)
        self._paint_highlight()

    def action_apply(self) -> None:
        self.dismiss(self._options[self._index][0])

    def action_cancel(self) -> None:
        self.dismiss(POOL_PROMPT_CANCELLED)


def pool_prompt_body(worker_count):
    if worker_count == 0:
        return "No workers are running."
    return "%d worker%s running; %s steps will be reclaimed and re-run." % (
        worker_count, "" if worker_count == 1 else "s",
        "its" if worker_count == 1 else "their")


def _tui_metric_line(wall_seconds, rss_kb, now):
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    rss = str(rss_kb) if rss_kb is not None else "?"
    return "%s  %-7s  wall_ms=%d rss_kb=%s\n" % (ts, "tui", round(wall_seconds * 1000), rss)


class PickerOption(Horizontal):
    def __init__(self, label, count, count_width, *, id=None):
        super().__init__(id=id, classes="picker-option")
        self.label_text = label
        self.count = count
        self.count_width = count_width

    def compose(self) -> ComposeResult:
        yield Static(id="picker-option-label")
        yield Static(str(self.count), classes="picker-option-count")

    def on_mount(self) -> None:
        self.query_one(".picker-option-count", Static).styles.width = self.count_width

    def set_highlighted(self, highlighted) -> None:
        cursor = Text(
            "%s " % CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]
        ) if highlighted else Text("  ")
        label = cursor + Text(self.label_text, style=COLOURS["text"])
        self.query_one("#picker-option-label", Static).update(label)
        self.set_class(highlighted, "picker-option-selected")


class MainScreen(Screen, inherit_bindings=False):
    BINDINGS = [b for b in Screen.BINDINGS if b.key != "tab"]


class LightcycleApp(App):
    CSS = f"""
    Screen {{
        border: solid {COLOURS["border"]};
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
        overflow-y: hidden;
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

    PriorityTable {{
        height: 1fr;
        display: none;
    }}

    DataTable {{
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
        scrollbar-background: {COLOURS["bg"]};
        scrollbar-background-hover: {COLOURS["bg"]};
        scrollbar-background-active: {COLOURS["bg"]};
        scrollbar-color: {COLOURS["dim"]};
        scrollbar-color-hover: {COLOURS["dim"]};
        scrollbar-color-active: {COLOURS["dim"]};
        scrollbar-corner-color: {COLOURS["bg"]};
        scrollbar-gutter: stable;
        overflow-x: hidden;
    }}
    DataTable:focus {{
        background-tint: transparent;
    }}
    DataTable > .datatable--cursor {{
        background: {COLOURS["selected-bg"]};
        color: {COLOURS["text"]};
    }}
    RichLog {{
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
        scrollbar-background: {COLOURS["bg"]};
        scrollbar-background-hover: {COLOURS["bg"]};
        scrollbar-background-active: {COLOURS["bg"]};
        scrollbar-color: {COLOURS["dim"]};
        scrollbar-color-hover: {COLOURS["dim"]};
        scrollbar-color-active: {COLOURS["dim"]};
        scrollbar-corner-color: {COLOURS["bg"]};
    }}
    RichLog:focus {{
        background-tint: transparent;
    }}

    #empty-state {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}

    #priority-list-floor {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}

    BacklogView {{
        display: none;
    }}
    #backlog-floor {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}
    .filter-row-label {{
        width: {FILTER_ROW_LABEL_WIDTH};
        color: {COLOURS["text"]};
    }}
    #backlog-search-bar {{
        height: 1;
        margin-top: 1;
    }}
    #backlog-search-bar:focus-within .filter-row-label {{
        color: {COLOURS["cyan"]};
    }}
    BacklogFilterInput {{
        border: none;
        padding: 0;
        height: 1;
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
    }}
    BacklogFilterInput:focus {{
        background: {COLOURS["bg"]};
        background-tint: 0%;
    }}
    BacklogFilterInput > .input--placeholder {{
        color: {COLOURS["dim"]};
    }}
    BacklogFilterInput > .input--cursor {{
        background: {COLOURS["cyan"]};
        color: {COLOURS["bg"]};
    }}
    BacklogFilterInput > .input--selection {{
        background: {COLOURS["selected-bg"]};
    }}
    #backlog-filter-bar {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    #backlog-filter-left {{
        width: auto;
    }}
    #backlog-filter-right {{
        width: 1fr;
        content-align: right middle;
        display: none;
    }}
    BacklogTable {{
        height: 1fr;
        display: none;
    }}
    #backlog-empty-overall {{
        content-align: center top;
        height: auto;
        margin-top: 4;
        display: none;
    }}
    #backlog-empty-filtered-message {{
        content-align: center top;
        height: auto;
        margin-top: 4;
        display: none;
    }}
    #backlog-empty-filtered-hint {{
        content-align: center top;
        height: auto;
        display: none;
    }}

    DoneView {{
        display: none;
    }}
    #done-floor {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}
    #done-search-bar {{
        height: 1;
        margin-top: 1;
    }}
    #done-search-bar:focus-within .filter-row-label {{
        color: {COLOURS["cyan"]};
    }}
    DoneFilterInput {{
        border: none;
        padding: 0;
        height: 1;
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
    }}
    DoneFilterInput:focus {{
        background: {COLOURS["bg"]};
        background-tint: 0%;
    }}
    DoneFilterInput > .input--placeholder {{
        color: {COLOURS["dim"]};
    }}
    DoneFilterInput > .input--cursor {{
        background: {COLOURS["cyan"]};
        color: {COLOURS["bg"]};
    }}
    DoneFilterInput > .input--selection {{
        background: {COLOURS["selected-bg"]};
    }}
    #done-filter-bar {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    #done-filter-left {{
        width: auto;
    }}
    #done-filter-right {{
        width: 1fr;
        content-align: right middle;
        display: none;
    }}
    #done-day-filter-bar {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    #done-day-filter-left {{
        width: auto;
    }}
    #done-day-filter-right {{
        width: 1fr;
        content-align: right middle;
        display: none;
    }}
    DoneTable {{
        height: 1fr;
        display: none;
    }}
    #done-empty-overall {{
        content-align: center top;
        height: auto;
        margin-top: 4;
        display: none;
    }}
    #done-empty-filtered-message {{
        content-align: center top;
        height: auto;
        margin-top: 4;
        display: none;
    }}
    #done-empty-filtered-hint {{
        content-align: center top;
        height: auto;
        display: none;
    }}

    StatsView {{
        display: none;
    }}
    #stats-day-filter-bar {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    #stats-day-filter-left {{
        width: auto;
    }}
    #stats-day-filter-right {{
        width: 1fr;
        content-align: right middle;
        display: none;
    }}
    StatsTable {{
        height: 1fr;
    }}
    #stats-floor {{
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
    StatusBar Static {{
        width: auto;
        margin-right: 2;
    }}
    StatusBar #status-version {{
        width: 1fr;
    }}
    StatusBar #status-upgrade {{
        margin-right: 0;
    }}
    #status-hold {{
        display: none;
    }}
    #status-upgrade {{
        display: none;
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

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("tab", "toggle_view", "Toggle view", show=False),
        Binding("[", "prev_strip", "Prev tab", show=False),
        Binding("]", "next_strip", "Next tab", show=False),
        Binding("f", "open_picker", "Filter", show=False),
        Binding("d", "open_day_picker", "Day", show=False),
        Binding("/", "focus_search", "Search", show=False),
        Binding("p", "toggle_pool", "Pool", show=False),
        Binding("enter", "open_done_for_stats_day", "Open", show=False),
        Binding("right", "open_done_for_stats_day", "Open", show=False),
    ]

    def __init__(self, container, now=None, upgrade_check=None):
        super().__init__()
        self._container = container
        self._now = now or (lambda: datetime.datetime.now().astimezone())
        self._upgrade_check = upgrade_check or (
            lambda: upgrade(
                self._container.config.version(), check_only=True,
                fetch=self._container.upgrade.fetch_remote_version)
        )
        self._upgrade_version = None
        self._upgrade_error = None
        self._last_shape = None
        self._last_attention_ids = None
        self._selected_flat_index = 0
        self._view = "priority"
        self._priority_empty = True
        self._priority_floor = False
        self._priority_stacked = False
        self._priority_needs_rebuild = False
        self._last_priority_rows = []
        self._active_row_ids = ()
        self._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX
        self._active_glyph_timer = None
        self._pool_transition_kind = None
        self._pool_transition_expired = False
        self._pool_transition_deadline = None
        self._pool_transition_timer = None
        self._priority_layout_cache = None
        self._priority_row_budget_cache = None
        self._backlog_project_filter = None
        self._backlog_text_filter = None
        self._backlog_total = 0
        self._backlog_filtered_count = 0
        self._backlog_filter_timer = None
        self._done_project_filter = None
        self._done_text_filter = None
        self._done_day_filter = None
        self._done_total = 0
        self._done_filtered_count = 0
        self._done_filter_timer = None
        self._upgrade_check_timer = None
        self._done_cost_time_cache = {}
        self._stats_cache = {}
        self._stats_day = None
        self._picker_open = False

    @property
    def container(self):
        return self._container

    @property
    def upgrade_version(self):
        return self._upgrade_version

    @property
    def upgrade_error(self):
        return self._upgrade_error

    def get_default_screen(self) -> Screen:
        return MainScreen(id="_default")

    def compose(self) -> ComposeResult:
        yield TabStrip(id="tab-strip")
        on_priority = self._view == "priority"
        showing_floor = on_priority and self._priority_floor and not self._priority_empty
        priority_table = PriorityTable(id="priority-list")
        priority_table.display = on_priority and not self._priority_empty and not showing_floor
        yield priority_table
        yield Static(EMPTY_STATE_MESSAGE, id="empty-state")
        priority_floor = Static(id="priority-list-floor")
        priority_floor.display = showing_floor
        yield priority_floor
        backlog_view = BacklogView(id="backlog-view")
        backlog_view.display = self._view == "backlog"
        yield backlog_view
        done_view = DoneView(id="done-view")
        done_view.display = self._view == "done"
        yield done_view
        stats_view = StatsView(id="stats-view")
        stats_view.display = self._view == "stats"
        yield stats_view
        yield DashboardFooter(id="footer")

    def on_mount(self) -> None:
        table = self.query_one(PriorityTable)
        table.cursor_type = "row"
        table.show_header = False
        self._start_upgrade_check()
        self.screen_change_signal.subscribe(self, lambda screen: self._sync_active_glyph_animation())
        self.call_after_refresh(self._refresh)
        self.set_interval(POLL_INTERVAL_SECONDS, self._refresh)
        upgrade_check_interval = self._container.config.tui_upgrade_check_seconds()
        if upgrade_check_interval > 0:
            self._upgrade_check_timer = self.set_interval(
                upgrade_check_interval, self._start_upgrade_check)
        if self._container.config.tui_autostart_pool():
            self._start_pool()

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._on_terminal_resized)

    def _on_terminal_resized(self) -> None:
        self.refresh_priority_layout()
        self.query_one(BacklogView).refresh_column_width()
        self.query_one(DoneView).refresh_column_width()

    def _check_upgrade(self):
        response = UpgradeNoticeUseCase(
            self._container.config.version(), check=self._upgrade_check).execute()
        return response.remote, response.error

    def _start_upgrade_check(self) -> None:
        self.run_worker(
            self._check_upgrade_worker, thread=True,
            group="upgrade-check", exclusive=True, exit_on_error=False,
        )

    def _check_upgrade_worker(self) -> None:
        version, error = self._check_upgrade()
        self.call_from_thread(self._apply_upgrade_result, version, error)

    def _apply_upgrade_result(self, version, error) -> None:
        if version is not None or error is None:
            self._upgrade_version = version
            self._upgrade_error = error
        elif self._upgrade_version is None:
            self._upgrade_error = error
        self._refresh_status_bar()

    def _refresh(self) -> None:
        metrics_enabled = self._container.config.tui_metrics()
        tick_start = time.perf_counter() if metrics_enabled else None

        lanes = StatusUseCase(self._container.store).execute().lanes
        try:
            suspended_steps = {
                w.step for w in self._container.workers.workers_state() if w.step and w.suspended
            }
        except RegistryUnreadable:
            suspended_steps = frozenset()
        attention_rows, active_rows, queued_rows = build_priority_rows(
            self._container.store, lanes, self._container.flow_service(),
            suspended_steps=suspended_steps,
        )
        shape = (
            tuple(r.id for r in attention_rows),
            tuple(r.id for r in active_rows),
            tuple(r.id for r in queued_rows),
        )
        rows = assemble_rows(attention_rows, active_rows, queued_rows)

        table = self.query_one(PriorityTable)
        self._priority_empty = not rows

        layout = self._priority_layout(table, rows)
        if (
            shape == self._last_shape
            and not self._priority_needs_rebuild
            and layout.stacked == self._priority_stacked
        ):
            self._update_cells(table, rows)
        else:
            self._rebuild_table(table, rows)
        had_prior_attention = self._last_attention_ids is not None
        newly_attention = set(shape[0]) - (self._last_attention_ids or set())
        self._last_shape = shape
        self._last_attention_ids = set(shape[0])
        if had_prior_attention and newly_attention:
            self.bell()

        self._active_row_ids = tuple(r.id for r in active_rows if not r.suspended)
        self._sync_active_glyph_animation()

        self._refresh_backlog_view()
        self._refresh_done_view()

        self._apply_view_visibility()
        self._sync_footer_shortcuts()

        self._refresh_status_bar()

        if tick_start is not None:
            wall_seconds = time.perf_counter() - tick_start
            rss_kb = self._container.machine.self_rss()
            self._container.worker_log.append_run_log(
                _tui_metric_line(wall_seconds, rss_kb, self._now().timestamp())
            )

    def _render_status_bar(self, status_bar, running, breaker, hold) -> None:
        status_bar.report(
            pool_running=running,
            pool_transition_kind=self._pool_transition_kind,
            pool_transition_expired=self._pool_transition_expired,
            breaker_is_open=breaker.is_open,
            breaker_is_probing=breaker.is_probing,
            breaker_reset_at=breaker.reset_at,
            version=self._container.config.version(),
            upgrade_version=self._upgrade_version,
            upgrade_error=self._upgrade_error,
            hold=hold,
        )

    def _refresh_status_bar(self) -> None:
        running = PoolRunningUseCase(self._container.lock).execute().running
        if self._pool_transition_kind == "start" and running:
            self._clear_pool_transition()
        elif self._pool_transition_kind == "stop" and not running:
            self._clear_pool_transition()
        breaker = BreakerStatusUseCase(self._container.breaker).execute(self._now().timestamp())
        hold = PoolHoldStatusUseCase(
            self._container.memory_gate_status, self._container.workers, self._container.config,
        ).execute(self._container.workers.pid_alive)
        for screen in self.screen_stack:
            try:
                status_bar = screen.query_one(StatusBar)
            except NoMatches:
                continue
            self._render_status_bar(status_bar, running, breaker, hold)

    def _begin_pool_transition(self, kind) -> None:
        self._pool_transition_kind = kind
        self._pool_transition_expired = False
        timeout = (
            POOL_START_TIMEOUT_SECONDS if kind == "start"
            else self._container.config.shutdown_grace_seconds()
        )
        self._pool_transition_deadline = self._now().timestamp() + timeout
        self._refresh_status_bar()
        self._sync_pool_transition_poll()

    def _clear_pool_transition(self) -> None:
        self._pool_transition_kind = None
        self._pool_transition_expired = False
        self._pool_transition_deadline = None
        self._sync_pool_transition_poll()

    def _sync_pool_transition_poll(self) -> None:
        should_run = self._pool_transition_kind is not None and not self._pool_transition_expired
        if should_run and self._pool_transition_timer is None:
            self._pool_transition_timer = self.set_interval(
                POOL_TRANSITION_POLL_SECONDS, self._tick_pool_transition
            )
        elif not should_run and self._pool_transition_timer is not None:
            self._pool_transition_timer.stop()
            self._pool_transition_timer = None

    def _tick_pool_transition(self) -> None:
        self._refresh_status_bar()
        if self._pool_transition_kind is None:
            return
        if self._now().timestamp() >= self._pool_transition_deadline:
            self._pool_transition_expired = True
            self._refresh_status_bar()
        self._sync_pool_transition_poll()

    def _refresh_backlog_view(self) -> None:
        backlog_uc = BacklogUseCase(self._container.store, None)
        backlog_resp = backlog_uc.execute(
            BacklogInput(project=self._backlog_project_filter, text=self._backlog_text_filter)
        )
        backlog_counts = backlog_uc.counts()
        backlog_rows = build_backlog_rows(backlog_resp.rows)
        self._backlog_total = backlog_counts.total
        self._backlog_filtered_count = len(backlog_rows)
        self.query_one(BacklogView).apply_rows(
            backlog_rows, self._backlog_total, self._backlog_project_filter, self._backlog_text_filter
        )

    def _refresh_done_view(self) -> None:
        done_uc = DoneUseCase(self._container.store)
        done_resp = done_uc.execute(DoneInput(
            project=self._done_project_filter, text=self._done_text_filter, day=self._done_day_filter,
        ))
        done_counts = done_uc.counts()
        self._done_total = done_counts.total
        self._done_filtered_count = len(done_resp.rows)
        if self._view != "done":
            return
        done_rows = build_done_rows(
            self._container.store, done_resp.rows, self._now(), self._done_cost_time_cache,
        )
        self.query_one(DoneView).apply_rows(
            done_rows, self._done_total, self._done_project_filter, self._done_text_filter,
            self._done_day_filter,
        )

    def _refresh_stats_view(self) -> None:
        if self._view != "stats":
            return
        day = self._stats_day or self._now().date()
        cached = self._stats_cache.get(day)
        if cached is None or day == self._now().date():
            cached = StatsUseCase(self._container.store).execute(StatsInput(day))
            self._stats_cache[day] = cached
        self.query_one(StatsView).apply_stats(cached)

    def _apply_view_visibility(self) -> None:
        on_priority = self._view == "priority"
        showing_floor = on_priority and self._priority_floor and not self._priority_empty
        self.query_one(PriorityTable).display = (
            on_priority and not self._priority_empty and not showing_floor
        )
        self.query_one("#empty-state", Static).display = on_priority and self._priority_empty
        self.query_one("#priority-list-floor", Static).display = showing_floor
        self.query_one(BacklogView).display = self._view == "backlog"
        self.query_one(DoneView).display = self._view == "done"
        self.query_one(StatsView).display = self._view == "stats"
        self._sync_active_glyph_animation()

    def _desired_shortcuts(self):
        if self._view == "priority":
            return GLOBAL_SHORTCUTS
        if self._view == "done":
            if self.focused is self.query_one(DoneFilterInput):
                return DONE_SEARCH_SHORTCUTS if self._done_filtered_count > 0 else DONE_SEARCH_EMPTY_SHORTCUTS
            if self._done_total == 0:
                return DONE_EMPTY_SHORTCUTS
            if self._done_filtered_count == 0:
                return DONE_FILTERED_EMPTY_SHORTCUTS
            return DONE_SHORTCUTS
        if self._view == "stats":
            return STATS_SHORTCUTS
        if self.focused is self.query_one(BacklogFilterInput):
            return BACKLOG_SEARCH_SHORTCUTS if self._backlog_filtered_count > 0 else BACKLOG_SEARCH_EMPTY_SHORTCUTS
        if self._backlog_total == 0:
            return BACKLOG_EMPTY_SHORTCUTS
        if self._backlog_filtered_count == 0:
            return BACKLOG_FILTERED_EMPTY_SHORTCUTS
        return BACKLOG_SHORTCUTS

    def _sync_footer_shortcuts(self) -> None:
        shortcut_bar = self.screen_stack[0].query_one(ShortcutBar)
        desired = self._desired_shortcuts()
        if shortcut_bar.shortcuts != desired:
            shortcut_bar.set_shortcuts(desired)

    def action_toggle_view(self) -> None:
        self._cycle_view(1)

    def action_prev_strip(self) -> None:
        if isinstance(self.screen, NodeHubScreen):
            self.screen.action_prev_tab()
            return
        self._cycle_view(-1)

    def action_next_strip(self) -> None:
        if isinstance(self.screen, NodeHubScreen):
            self.screen.action_next_tab()
            return
        self._cycle_view(1)

    def _cycle_view(self, direction: int) -> None:
        if self._backlog_filter_timer is not None:
            self._backlog_filter_timer.stop()
            self._backlog_filter_timer = None
        if self._done_filter_timer is not None:
            self._done_filter_timer.stop()
            self._done_filter_timer = None
        while len(self.screen_stack) > 1:
            self.pop_screen()
        index = _VIEW_CYCLE.index(self._view)
        self._cycle_view_to(_VIEW_CYCLE[(index + direction) % len(_VIEW_CYCLE)])

    def _cycle_view_to(self, view) -> None:
        self._view = view
        if self._view == "done":
            self._refresh_done_view()
        elif self._view == "stats":
            self._refresh_stats_view()
        self._apply_view_visibility()
        self.query_one(TabStrip).set_active(self._view)
        self._sync_footer_shortcuts()
        self._sync_active_glyph_animation()
        if self._view == "priority":
            self.set_focus(self.query_one(PriorityTable))
        elif self._view == "backlog":
            self.set_focus(self.query_one(BacklogTable))
        elif self._view == "stats":
            self.set_focus(self.query_one(StatsView))
        else:
            self.set_focus(self.query_one(DoneTable))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        table = event.data_table
        row_id = event.row_key.value
        if row_id is None:
            return
        if table.id == "priority-list":
            event.stop()
            rows_by_id = {row.id: row for row in self._last_priority_rows}
            row = rows_by_id.get(row_id)
            if row is None:
                return
            self.push_screen(NodeHubScreen(self._container, row.step_id, self._now))
        elif table.id in ("backlog-table", "done-table"):
            event.stop()
            self.push_screen(NodeHubScreen(self._container, row_id, self._now))

    def _start_pool(self):
        return StartPoolUseCase(self._container.lock, self._container.spawner).execute()

    def _live_worker_count(self):
        return LiveWorkerCountUseCase(self._container.workers).execute()

    def action_toggle_pool(self) -> None:
        if self._pool_transition_kind is not None and not self._pool_transition_expired:
            return
        if not PoolRunningUseCase(self._container.lock).execute().running:
            self._start_pool()
            self._begin_pool_transition("start")
            return
        self.push_screen(
            PoolPromptScreen(
                "Stop the pool?",
                pool_prompt_body(self._live_worker_count()),
                [(POOL_PROMPT_STOP, "Stop the pool"), (POOL_PROMPT_CANCELLED, "Cancel")],
            ),
            self._on_stop_prompt_dismiss,
        )

    def _on_stop_prompt_dismiss(self, result) -> None:
        if result != POOL_PROMPT_STOP:
            return
        StopPoolSignalUseCase(self._container.lock, self._container.workers).execute()
        self._begin_pool_transition("stop")

    def action_quit(self) -> None:
        if not PoolRunningUseCase(self._container.lock).execute().running:
            self.exit()
            return
        self.push_screen(
            PoolPromptScreen(
                "Quit lightcycle?",
                pool_prompt_body(self._live_worker_count()),
                [
                    (POOL_PROMPT_QUIT_LEAVE, "Quit and leave the pool running"),
                    (POOL_PROMPT_QUIT_STOP, "Quit and stop the pool"),
                    (POOL_PROMPT_CANCELLED, "Cancel"),
                ],
            ),
            self._on_quit_prompt_dismiss,
        )

    def _on_quit_prompt_dismiss(self, result) -> None:
        if result == POOL_PROMPT_CANCELLED:
            return
        if result == POOL_PROMPT_QUIT_STOP:
            StopPoolSignalUseCase(self._container.lock, self._container.workers).execute()
        self.exit()

    def action_open_picker(self) -> None:
        if self._view not in ("backlog", "done") or self._picker_open:
            return
        if self._view == "backlog":
            counts = BacklogUseCase(self._container.store, None).counts()
        else:
            counts = DoneUseCase(self._container.store).counts()
        options = [(None, "All", counts.total)] + [
            (pc.project, pc.project, pc.count) for pc in counts.projects
        ]
        self._picker_open = True
        self.push_screen(ProjectFilterPicker(options), self._on_picker_dismiss)

    def _on_picker_dismiss(self, result) -> None:
        self._picker_open = False
        if result is PICKER_CANCELLED:
            return
        if self._view == "backlog":
            self._backlog_project_filter = result
            self._refresh()
            self.set_focus(self.query_one(BacklogTable))
        else:
            self._done_project_filter = result
            self._refresh()
            self.set_focus(self.query_one(DoneTable))

    def action_open_day_picker(self) -> None:
        if self._view not in ("done", "stats") or self._picker_open:
            return
        done_uc = DoneUseCase(self._container.store)
        if self._view == "done":
            options = [(None, "All", done_uc.counts().total)] + [
                (dc.day, dc.day.isoformat(), dc.count) for dc in done_uc.day_counts()
            ]
            dismiss = self._on_done_day_picker_dismiss
        else:
            today = self._now().date()
            counts = {dc.day: dc.count for dc in done_uc.day_counts()}
            days = sorted({today} | set(counts), reverse=True)
            options = [(d, d.isoformat(), counts.get(d, 0)) for d in days]
            dismiss = self._on_stats_day_picker_dismiss
        self._picker_open = True
        self.push_screen(ProjectFilterPicker(options, heading="Filter by day"), dismiss)

    def _on_done_day_picker_dismiss(self, result) -> None:
        self._picker_open = False
        if result is PICKER_CANCELLED:
            return
        self._done_day_filter = result
        self._refresh()
        self.set_focus(self.query_one(DoneTable))

    def _on_stats_day_picker_dismiss(self, result) -> None:
        self._picker_open = False
        if result is PICKER_CANCELLED:
            return
        self._stats_day = result
        self._refresh_stats_view()
        self.set_focus(self.query_one(StatsView))

    def action_open_done_for_stats_day(self) -> None:
        if self._view != "stats":
            return
        self._done_day_filter = self._stats_day or self._now().date()
        self._cycle_view_to("done")

    def action_focus_search(self) -> None:
        if self._view == "backlog":
            self.set_focus(self.query_one(BacklogFilterInput))
        elif self._view == "done":
            self.set_focus(self.query_one(DoneFilterInput))
        else:
            return
        self.stylesheet.update(self.screen, animate=False)
        self._sync_footer_shortcuts()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "backlog-filter-text":
            self._backlog_text_filter = event.value or None
            if self._backlog_filter_timer is not None:
                self._backlog_filter_timer.stop()
            self._backlog_filter_timer = self.set_timer(FILTER_DEBOUNCE_SECONDS, self._on_backlog_filter_settled)
        elif event.input.id == "done-filter-text":
            self._done_text_filter = event.value or None
            if self._done_filter_timer is not None:
                self._done_filter_timer.stop()
            self._done_filter_timer = self.set_timer(FILTER_DEBOUNCE_SECONDS, self._on_done_filter_settled)

    def _on_backlog_filter_settled(self) -> None:
        self._backlog_filter_timer = None
        self._refresh_backlog_view()
        self._sync_footer_shortcuts()

    def _on_done_filter_settled(self) -> None:
        self._done_filter_timer = None
        self._refresh_done_view()
        self._sync_footer_shortcuts()

    def _priority_layout(self, table, rows):
        atomic_values = {
            "id": [row.id for row in rows],
            "project": [row.project for row in rows],
            "step": [row.step for row in rows],
            "cost": [row.cost for row in rows],
            "time": [row.time for row in rows],
        }
        row_budget = screen_row_budget_for(table, len(DATA_COLUMNS))
        return compute_layout(row_budget, ["cursor", "icon"], atomic_values, PRIORITY_CONTINUATION_INDENT)

    def _add_columns(self, table, layout, row_budget) -> None:
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
            return
        widths = {
            "cursor": GLYPH_WIDTHS["cursor"],
            "icon": GLYPH_WIDTHS["icon"],
            "id": layout.atomic_widths["id"],
            "project": layout.atomic_widths["project"],
            "step": layout.atomic_widths["step"],
            "cost": layout.atomic_widths["cost"],
            "time": layout.atomic_widths["time"],
            "title": layout.flexible_width,
        }
        for key in DATA_COLUMNS:
            table.add_column(key, width=widths[key], key=key)

    def _stacked_first_line(self, row, cursor, layout, row_budget, icon_override=None):
        cursor_field = pad_field(
            Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else Text(""),
            GLYPH_WIDTHS["cursor"],
        )
        icon_cell = Text(icon_override if icon_override is not None else row.icon, style=COLOURS[row.icon_colour])
        if row.dependency_icon:
            icon_cell = icon_cell + Text(
                row.dependency_icon, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
            )
        icon_field = pad_field(icon_cell, GLYPH_WIDTHS["icon"])
        id_field = pad_atomic_field(row.id, layout.atomic_widths["id"])
        project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else Text("")
        project_field = pad_atomic_field(project_cell, layout.atomic_widths["project"])
        step_field = pad_atomic_field(
            Text(row.step, style=COLOURS[row.step_colour]), layout.atomic_widths["step"]
        )
        cost_field = pad_atomic_field(
            Text(row.cost, style=COLOURS["dim"]) if row.cost else Text(""), layout.atomic_widths["cost"]
        )
        content_so_far = cursor_field + icon_field + id_field + project_field + step_field + cost_field
        time_cell = Text(row.time, style=COLOURS["dim"]) if row.time else Text("")
        time_area = max(0, row_budget - len(content_so_far.plain))
        return content_so_far + pad_field_right(time_cell, time_area)

    def _row_cells(self, row, layout, row_budget, cursor=False, icon_override=None):
        if layout.stacked:
            first_line = self._stacked_first_line(row, cursor, layout, row_budget, icon_override)
            cell = stacked_cell(first_line, PRIORITY_CONTINUATION_INDENT, row.title, row_budget)
            spacer = Text("\n" + " " * PRIORITY_CONTINUATION_INDENT + " ")
            return (cell + spacer,)
        cursor_cell = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else ""
        icon_cell = Text(icon_override if icon_override is not None else row.icon, style=COLOURS[row.icon_colour])
        if row.dependency_icon:
            icon_cell = icon_cell + Text(
                row.dependency_icon, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
            )
        step_cell = Text(row.step, style=COLOURS[row.step_colour])
        project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else ""
        cost_cell = Text(row.cost, style=COLOURS["dim"]) if row.cost else ""
        time_cell = Text(row.time, style=COLOURS["dim"]) if row.time else ""
        return (
            cursor_cell, icon_cell, row.id, project_cell, row.title + "\n ", step_cell, cost_cell, time_cell,
        )

    def _stacked_row_cell_builder(self, row, layout, row_budget, cursor, icon_override):
        return self._row_cells(row, layout, row_budget, cursor=cursor, icon_override=icon_override)

    def _update_cells(self, table, rows) -> None:
        self._last_priority_rows = rows
        layout = self._priority_layout(table, rows)
        row_budget = render_screen_row_budget(table, layout, len(DATA_COLUMNS))
        if not layout.stacked:
            apply_widths(
                table,
                {
                    "id": layout.atomic_widths["id"],
                    "project": layout.atomic_widths["project"],
                    "step": layout.atomic_widths["step"],
                    "cost": layout.atomic_widths["cost"],
                    "time": layout.atomic_widths["time"],
                    "title": layout.flexible_width,
                },
            )
        self._priority_layout_cache = layout
        self._priority_row_budget_cache = row_budget
        active_glyph = self._active_glyph_char()
        selected_id = self._selected_row_id(table)
        for row in rows:
            icon_override = active_glyph if row.group == "active" else None
            cells = self._row_cells(
                row, layout, row_budget, cursor=(row.id == selected_id), icon_override=icon_override
            )
            if layout.stacked:
                table.update_cell(row.id, STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(DATA_COLUMNS, cells):
                if key == "cursor":
                    continue
                table.update_cell(row.id, key, value)

    def _active_glyph_char(self) -> str:
        return ACTIVE_GLYPH_FRAMES[self._active_glyph_frame]

    def _priority_view_visible(self) -> bool:
        return self._view == "priority" and self.screen is self.screen_stack[0]

    def _sync_active_glyph_animation(self) -> None:
        should_run = (
            self._priority_view_visible()
            and bool(self._active_row_ids)
            and not self._priority_floor
            and not self._priority_needs_rebuild
        )
        if should_run and self._active_glyph_timer is None:
            self._active_glyph_timer = self.set_interval(
                1 / ACTIVE_GLYPH_TICKS_PER_SECOND, self._tick_active_glyph
            )
        elif not should_run and self._active_glyph_timer is not None:
            self._active_glyph_timer.stop()
            self._active_glyph_timer = None
            self._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX

    def _tick_active_glyph(self) -> None:
        self._active_glyph_frame = next_active_glyph_frame(self._active_glyph_frame)
        if not self._active_row_ids or self._priority_layout_cache is None:
            return
        try:
            table = self.query_one(PriorityTable)
        except NoMatches:
            return
        glyph = self._active_glyph_char()
        layout = self._priority_layout_cache
        row_budget = self._priority_row_budget_cache
        rows_by_id = {row.id: row for row in self._last_priority_rows}
        selected_id = self._selected_row_id(table)
        for row_id in self._active_row_ids:
            row = rows_by_id.get(row_id)
            if row is None:
                continue
            cells = self._row_cells(
                row, layout, row_budget, cursor=(row_id == selected_id), icon_override=glyph
            )
            try:
                if layout.stacked:
                    table.update_cell(row_id, STACKED_COLUMN_KEY, cells[0])
                else:
                    table.update_cell(row_id, "icon", cells[1])
            except CellDoesNotExist:
                pass

    def _selected_row_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        row_id = cell_key.row_key.value
        if row_id is None:
            return None
        return row_id

    def _rebuild_table(self, table, rows) -> None:
        self._last_priority_rows = rows
        layout = self._priority_layout(table, rows)
        self._priority_floor = bool(rows) and layout.floor
        self._priority_stacked = layout.stacked
        if self._priority_floor:
            self._priority_needs_rebuild = True
            self.query_one("#priority-list-floor", Static).update(
                Text(floor_message(layout, table, len(DATA_COLUMNS)), style=COLOURS["dim"])
            )
            return
        self._priority_needs_rebuild = False

        has_prior = self._last_shape is not None
        selected_id = self._selected_row_id(table) if has_prior else None

        table.clear(columns=True)
        row_budget = render_screen_row_budget(table, layout, len(DATA_COLUMNS))
        self._add_columns(table, layout, row_budget)
        self._priority_layout_cache = layout
        self._priority_row_budget_cache = row_budget

        new_index = 0
        if has_prior and rows:
            ids = [row.id for row in rows]
            if selected_id is not None and selected_id in ids:
                new_index = ids.index(selected_id)
            else:
                new_index = min(max(self._selected_flat_index, 0), len(rows) - 1)

        table._stacked_mode = layout.stacked
        table._stacked_layout = layout
        table._stacked_row_budget = row_budget
        table._stacked_cell_builder = self._stacked_row_cell_builder
        active_glyph = self._active_glyph_char()
        stacked_rows = {}
        for index, row in enumerate(rows):
            is_cursor = index == new_index
            icon_override = active_glyph if row.group == "active" else None
            cells = self._row_cells(row, layout, row_budget, cursor=is_cursor, icon_override=icon_override)
            if layout.stacked:
                stacked_rows[row.id] = (row, icon_override)
            table.add_row(*cells, height=None, key=row.id)
        table._stacked_rows = stacked_rows

        self._selected_flat_index = new_index
        if rows:
            table.move_cursor(row=new_index)

    def refresh_priority_layout(self) -> None:
        table = self.query_one(PriorityTable)
        if self._priority_empty or not self._last_priority_rows:
            return
        if self._priority_needs_rebuild:
            self._rebuild_table(table, self._last_priority_rows)
            self._apply_view_visibility()
            return
        layout = self._priority_layout(table, self._last_priority_rows)
        if bool(self._last_priority_rows) and layout.floor != self._priority_floor:
            self._rebuild_table(table, self._last_priority_rows)
            self._apply_view_visibility()
            return
        if layout.floor:
            self.query_one("#priority-list-floor", Static).update(
                Text(floor_message(layout, table, len(DATA_COLUMNS)), style=COLOURS["dim"])
            )
            return
        if layout.stacked or layout.stacked != self._priority_stacked:
            self._rebuild_table(table, self._last_priority_rows)
            return
        widths = {
            "id": layout.atomic_widths["id"],
            "project": layout.atomic_widths["project"],
            "step": layout.atomic_widths["step"],
            "cost": layout.atomic_widths["cost"],
            "time": layout.atomic_widths["time"],
            "title": layout.flexible_width,
        }
        apply_widths(table, widths)


def run(container):
    LightcycleApp(container).run()
