import datetime

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle import __version__
from lightcycle.adapters.tui.backlog_list import build_backlog_rows
from lightcycle.adapters.tui.design_system import (
    BACKLOG_EMPTY_SHORTCUTS,
    BACKLOG_FILTERED_EMPTY_SHORTCUTS,
    BACKLOG_SHORTCUTS,
    COLOURS,
    COLUMN_GRIDS,
    CURSOR_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    GLOBAL_SHORTCUTS,
)
from lightcycle.adapters.tui.footer import DashboardFooter, ShortcutBar, StatusBar
from lightcycle.adapters.tui.hub import NodeHubScreen
from lightcycle.adapters.tui.priority_list import assemble_rows, build_priority_rows, is_gap_key
from lightcycle.application.pool import BreakerStatusUseCase, PoolRunningUseCase
from lightcycle.application.setup import upgrade
from lightcycle.application.work import BacklogInput, BacklogUseCase, StatusUseCase

POLL_INTERVAL_SECONDS = 10

DATA_COLUMNS = ("cursor", "icon", "id", "project", "title", "step", "time")
BACKLOG_COLUMNS = ("cursor", "id", "project", "title")

EMPTY_STATE_MESSAGE = "Nothing needs attention. Nothing's active. Nothing's queued."

PICKER_CANCELLED = object()


class TabStrip(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("Current work", id="tab-current-work", classes="tab-active")
        yield Static(" · ", classes="tab-separator")
        yield Static("Backlog", id="tab-backlog", classes="tab-dim")

    def set_active(self, view) -> None:
        current_work = self.query_one("#tab-current-work", Static)
        backlog = self.query_one("#tab-backlog", Static)
        on_priority = view == "priority"
        current_work.set_class(on_priority, "tab-active")
        current_work.set_class(not on_priority, "tab-dim")
        backlog.set_class(not on_priority, "tab-active")
        backlog.set_class(on_priority, "tab-dim")


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
        value = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if show else ""
        try:
            self.update_cell(row_key, "cursor", value)
        except CellDoesNotExist:
            pass


def _backlog_row_cells(row, cursor=False):
    cursor_cell = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else ""
    project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else ""
    return (cursor_cell, row.id, project_cell, row.title)


class BacklogView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rows = ()

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static(id="backlog-filter-left"),
            Static(id="backlog-filter-right"),
            id="backlog-filter-bar",
        )
        yield BacklogTable(id="backlog-table")
        yield Static(id="backlog-empty-overall")
        yield Static(id="backlog-empty-filtered-message")
        yield Static(id="backlog-empty-filtered-hint")

    def on_mount(self) -> None:
        table = self.query_one(BacklogTable)
        table.cursor_type = "row"
        table.show_header = False

    def apply_rows(self, rows, total, project_filter) -> None:
        self._rows = rows
        self._render_filter_bar(project_filter, len(rows))
        self._rebuild_table(rows)
        self._toggle_state(total, len(rows), project_filter)

    def refresh_column_width(self) -> None:
        self._rebuild_table(self._rows)

    def _render_filter_bar(self, project_filter, count) -> None:
        left = self.query_one("#backlog-filter-left", Static)
        right = self.query_one("#backlog-filter-right", Static)
        left.update(Text("PROJECT: %s" % (project_filter or "All"), style=COLOURS["text"]))
        right.update(Text("%d items" % count, style=COLOURS["text"]))

    def _selected_row_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def _title_width(self, table):
        grid = dict(COLUMN_GRIDS["backlog"])
        padding = 2 * table.cell_padding * len(BACKLOG_COLUMNS)
        fixed = sum(int(grid[key][:-2]) for key in BACKLOG_COLUMNS if key != "title") + padding
        width = table.size.width - fixed
        return width if width > 0 else None

    def _rebuild_table(self, rows) -> None:
        table = self.query_one(BacklogTable)
        title_width = self._title_width(table)
        if title_width is None:
            return
        selected_id = self._selected_row_id(table)

        table.clear(columns=True)
        grid = dict(COLUMN_GRIDS["backlog"])
        for key in BACKLOG_COLUMNS:
            width = title_width if key == "title" else int(grid[key][:-2])
            table.add_column(key, width=width, key=key)

        ids = [row.id for row in rows]
        new_index = ids.index(selected_id) if selected_id in ids else 0
        for index, row in enumerate(rows):
            table.add_row(*_backlog_row_cells(row, cursor=index == new_index), key=row.id)
        if rows:
            table.move_cursor(row=new_index)

    def _toggle_state(self, total, filtered_count, project_filter) -> None:
        overall_empty = total == 0
        filtered_empty = not overall_empty and filtered_count == 0
        table = self.query_one(BacklogTable)
        table.display = filtered_count > 0
        overall_widget = self.query_one("#backlog-empty-overall", Static)
        message_widget = self.query_one("#backlog-empty-filtered-message", Static)
        hint_widget = self.query_one("#backlog-empty-filtered-hint", Static)
        overall_widget.display = overall_empty
        message_widget.display = filtered_empty
        hint_widget.display = filtered_empty
        if overall_empty:
            overall_widget.update(Text("Nothing in the backlog.", style=COLOURS["dim"]))
        elif filtered_empty:
            message = Text("No backlog items for ", style=COLOURS["dim"])
            message.append(project_filter, style=COLOURS["text"])
            message.append(".", style=COLOURS["dim"])
            message_widget.update(message)
            hint_widget.update(Text("Press f to check All.", style=COLOURS["dim"]))


class ProjectFilterPicker(ModalScreen):
    CSS = f"""
    ProjectFilterPicker {{
        align: center top;
    }}
    #picker {{
        width: 40;
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
    .picker-option-count {{
        width: 1fr;
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

    def __init__(self, options):
        super().__init__()
        self._options = options
        self._index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static("Filter by project", id="picker-head")
            for index, (_, label, count) in enumerate(self._options):
                yield PickerOption(label, count, id="picker-option-%d" % index)
            yield Static("↑↓ move · enter apply · esc cancel", id="picker-foot")

    def on_mount(self) -> None:
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


class PickerOption(Horizontal):
    def __init__(self, label, count, *, id=None):
        super().__init__(id=id, classes="picker-option")
        self.label_text = label
        self.count = count

    def compose(self) -> ComposeResult:
        yield Static(id="picker-option-label")
        yield Static(str(self.count), classes="picker-option-count")

    def set_highlighted(self, highlighted) -> None:
        cursor = Text(
            "%s " % CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]
        ) if highlighted else Text("  ")
        label = cursor + Text(self.label_text, style=COLOURS["text"])
        self.query_one("#picker-option-label", Static).update(label)
        self.set_class(highlighted, "picker-option-selected")


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

    BacklogView {{
        display: none;
    }}
    #backlog-filter-bar {{
        height: 1;
        border-bottom: solid {COLOURS["border"]};
    }}
    #backlog-filter-bar Static {{
        width: auto;
    }}
    #backlog-filter-right {{
        width: 1fr;
        content-align: right middle;
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
        Binding("tab", "toggle_view", "Toggle view", show=False, priority=True),
        Binding("f", "open_picker", "Filter", show=False),
    ]

    def __init__(self, container, now=None, upgrade_check=None):
        super().__init__()
        self._container = container
        self._now = now or datetime.datetime.now
        self._upgrade_check = upgrade_check or (lambda: upgrade(__version__, check_only=True))
        self._upgrade_version = None
        self._last_shape = None
        self._last_attention_ids = None
        self._selected_flat_index = 0
        self._view = "priority"
        self._priority_empty = True
        self._backlog_project_filter = None
        self._backlog_total = 0
        self._backlog_filtered_count = 0
        self._picker_open = False

    @property
    def container(self):
        return self._container

    @property
    def upgrade_version(self):
        return self._upgrade_version

    def compose(self) -> ComposeResult:
        yield TabStrip(id="tab-strip")
        yield PriorityTable(id="priority-list")
        yield Static(EMPTY_STATE_MESSAGE, id="empty-state")
        yield BacklogView(id="backlog-view")
        yield DashboardFooter(id="footer")

    def on_mount(self) -> None:
        table = self.query_one(PriorityTable)
        table.cursor_type = "row"
        table.show_header = False
        self._upgrade_version = self._check_upgrade()
        self.call_after_refresh(self._refresh)
        self.set_interval(POLL_INTERVAL_SECONDS, self._refresh)

    def _check_upgrade(self):
        try:
            response = self._upgrade_check()
        except Exception:
            return None
        if not response.available:
            return None
        return response.remote

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
        self._priority_empty = not rows

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

        backlog_uc = BacklogUseCase(self._container.store, None)
        backlog_resp = backlog_uc.execute(BacklogInput(project=self._backlog_project_filter))
        backlog_counts = backlog_uc.counts()
        backlog_rows = build_backlog_rows(backlog_resp.rows)
        self._backlog_total = backlog_counts.total
        self._backlog_filtered_count = len(backlog_rows)
        self.query_one(BacklogView).apply_rows(
            backlog_rows, self._backlog_total, self._backlog_project_filter
        )

        self._apply_view_visibility()
        self._sync_footer_shortcuts()

        if isinstance(self.screen, NodeHubScreen):
            self.screen.poll_refresh()

        running = PoolRunningUseCase(self._container.lock).execute().running
        breaker = BreakerStatusUseCase(self._container.breaker).execute()
        self.screen_stack[0].query_one(StatusBar).report(
            pool_running=running,
            breaker_is_open=breaker.is_open,
            breaker_reset_at=breaker.reset_at,
            version=__version__,
            upgrade_version=self._upgrade_version,
        )

    def _apply_view_visibility(self) -> None:
        on_priority = self._view == "priority"
        self.query_one(PriorityTable).display = on_priority and not self._priority_empty
        self.query_one("#empty-state", Static).display = on_priority and self._priority_empty
        self.query_one(BacklogView).display = not on_priority

    def _desired_shortcuts(self):
        if self._view == "priority":
            return GLOBAL_SHORTCUTS
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
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self._view = "backlog" if self._view == "priority" else "priority"
        self._apply_view_visibility()
        self.query_one(TabStrip).set_active(self._view)
        self._sync_footer_shortcuts()
        if self._view == "priority":
            self.set_focus(self.query_one(PriorityTable))
        else:
            self.set_focus(self.query_one(BacklogTable))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        table = event.data_table
        row_id = event.row_key.value
        if row_id is None:
            return
        if table.id == "priority-list":
            event.stop()
            if is_gap_key(row_id):
                return
            node = self._container.store.get_node(row_id)
            owning_id = node.parent if node.type == "step" else node.id
            self.push_screen(NodeHubScreen(self._container, owning_id, self._now))
        elif table.id == "backlog-table":
            event.stop()
            self.push_screen(NodeHubScreen(self._container, row_id, self._now))

    def action_open_picker(self) -> None:
        if self._view != "backlog" or self._picker_open:
            return
        counts = BacklogUseCase(self._container.store, None).counts()
        options = [(None, "All", counts.total)] + [
            (pc.project, pc.project, pc.count) for pc in counts.projects
        ]
        self._picker_open = True
        self.push_screen(ProjectFilterPicker(options), self._on_picker_dismiss)

    def _on_picker_dismiss(self, result) -> None:
        self._picker_open = False
        if result is PICKER_CANCELLED:
            return
        self._backlog_project_filter = result
        self._refresh()
        self.set_focus(self.query_one(BacklogTable))

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
