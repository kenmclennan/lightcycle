import textwrap

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle.adapters.tui.design_system import (
    COLOURS,
    CURSOR_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    FILTER_DEBOUNCE_SECONDS,
    GOAL_LOG_SEARCH_SHORTCUTS,
    GOAL_LOG_SHORTCUTS,
    HUB_SHORTCUTS,
    ROW_SPACER,
    STATE_GLYPHS,
)
from lightcycle.adapters.tui.footer import DashboardFooter, ShortcutBar
from lightcycle.adapters.tui.hub import (
    HUB_TAB_STRIP_CSS,
    POLL_INTERVAL_SECONDS,
    DescriptionPane,
    HubTabStrip,
    NodeHubScreen,
)
from lightcycle.adapters.tui.priority_list import (
    PriorityRow,
    assemble_rows,
    build_priority_rows_from_selection,
)
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    pad_field,
    pad_field_right,
    wrap_continuation,
)
from lightcycle.application.goals import GoalItemsUseCase, ShowGoalUseCase, log_entry_matches
from lightcycle.application.work.suspended_steps import suspended_step_ids
from lightcycle.domain.goals import goal_log_stamp

GOAL_TAB_ORDER = ("overview", "log", "items")

STATE_OF_PLAY_TITLE = "State of play"
GOAL_DESCRIPTION_EMPTY_MESSAGE = "No description written yet."
GOAL_LOG_EMPTY_MESSAGE = "No decisions logged yet."
GOAL_LOG_NO_MATCH_MESSAGE = "No entries match."
LOG_TITLE_STAMP_GAP = 2
LOG_FALLBACK_WIDTH = 80
GOAL_ITEMS_EMPTY_MESSAGE = "No items linked to this goal."
GOAL_ITEMS_NO_MATCH_MESSAGE = "No items match."
ITEMS_FALLBACK_WIDTH = 80
ITEMS_ID_TITLE_GAP = 2
HEADER_KEY_PREFIX = "header:"
GROUP_HEADERS = (("current", "CURRENT WORK"), ("backlog", "BACKLOG"), ("done", "DONE"))


def _header_lines(title, stamp, width):
    if not title:
        return [" " * max(width - len(stamp), 0) + stamp]
    available = max(width - len(stamp) - LOG_TITLE_STAMP_GAP, 1)
    if len(title) <= available:
        parts = [title]
    else:
        parts = textwrap.wrap(title, available) or [title]
    first = parts[0]
    padding = max(width - len(first) - len(stamp), LOG_TITLE_STAMP_GAP)
    return [first + " " * padding + stamp] + parts[1:]


class GoalFilterInput(Input):
    BINDINGS = [
        Binding("escape", "leave_filter", "Back", show=False),
        Binding("tab", "leave_filter", "Back", show=False),
        Binding("down", "leave_filter", "Log", show=False),
        Binding("up", "leave_filter", "Log", show=False),
        Binding("enter", "leave_filter", "Log", show=False),
    ]



class GoalLogFilterInput(GoalFilterInput):
    def action_leave_filter(self) -> None:
        self.screen.leave_log_filter()


class GoalItemsFilterInput(GoalFilterInput):
    def action_leave_filter(self) -> None:
        self.screen.leave_items_filter()


def _is_header_row(table, row_index):
    if row_index < 0 or row_index >= len(table.ordered_rows):
        return False
    value = table.ordered_rows[row_index].key.value
    return value is not None and value.startswith(HEADER_KEY_PREFIX)


class GoalItemsTable(DataTable):
    _BASE_BINDINGS = [b for b in DataTable.BINDINGS if b.key != "right"]

    BINDINGS = _BASE_BINDINGS + [
        Binding("right", "select_cursor", "Open", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def validate_cursor_coordinate(self, value):
        value = super().validate_cursor_coordinate(value)
        if not _is_header_row(self, value.row):
            return value
        direction = 1 if value.row >= self.cursor_coordinate.row else -1
        for step in (direction, -direction):
            row = value.row
            while 0 <= row < len(self.ordered_rows) and _is_header_row(self, row):
                row += step
            if 0 <= row < len(self.ordered_rows):
                return value._replace(row=row)
        return value

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate) -> None:
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if old_coordinate.row != new_coordinate.row:
            self._paint_cursor(old_coordinate.row, False)
            self._paint_cursor(new_coordinate.row, True)

    def _paint_cursor(self, row_index, show) -> None:
        if row_index < 0 or row_index >= len(self.ordered_rows):
            return
        row_key = self.ordered_rows[row_index].key
        if row_key.value is None or row_key.value.startswith(HEADER_KEY_PREFIX):
            return
        value = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if show else ""
        try:
            self.update_cell(row_key, "cursor", value)
        except CellDoesNotExist:
            pass


def _item_cells(icon, item_id, title, id_width, width, step=None, step_colour="dim"):
    icon_field = pad_field(icon, GLYPH_WIDTHS["icon"])
    id_field = pad_field(Text(item_id, style=COLOURS["cyan"]), id_width + ITEMS_ID_TITLE_GAP)
    indent = GLYPH_WIDTHS["icon"] + id_width + ITEMS_ID_TITLE_GAP
    lines = wrap_continuation(title or "", width - indent)
    cell = icon_field + id_field + Text(lines[0], style=COLOURS["text"])
    for line in lines[1:]:
        cell = cell + Text("\n" + " " * indent) + Text(line, style=COLOURS["text"])
    if step:
        cell = cell + Text("\n") + pad_field_right(Text(step, style=COLOURS[step_colour]), width)
    return cell


def _row_icon(row):
    icon = Text(row.icon, style=COLOURS[row.icon_colour])
    if row.dependency_icon:
        icon = icon + Text(row.dependency_icon, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour])
    return icon


class GoalHubScreen(Screen, inherit_bindings=False):
    BINDINGS = [b for b in Screen.BINDINGS if b.key != "tab"] + [
        Binding("escape", "close_hub", "Back", show=False),
        Binding("left", "close_hub", "Back", show=False),
        Binding("/", "focus_search", "Search", show=False),
    ]

    CSS = f"""
    {HUB_TAB_STRIP_CSS}
    #goal-hub-identity {{
        height: auto;
    }}
    #goal-description-view {{
        height: 1fr;
        display: none;
    }}
    #goal-description-empty {{
        height: 1fr;
        color: {COLOURS["dim"]};
        display: none;
    }}
    #goal-log-view, GoalItemsTable {{
        height: 1fr;
        display: none;
    }}
    #goal-log-search-bar, #goal-items-search-bar {{
        height: 1;
        margin-top: 1;
        display: none;
    }}
    #goal-log-search-bar:focus-within .filter-row-label,
    #goal-items-search-bar:focus-within .filter-row-label {{
        color: {COLOURS["cyan"]};
    }}
    GoalFilterInput {{
        border: none;
        padding: 0;
        height: 1;
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
    }}
    GoalFilterInput:focus {{
        background: {COLOURS["bg"]};
        background-tint: 0%;
    }}
    GoalFilterInput > .input--placeholder {{
        color: {COLOURS["dim"]};
    }}
    GoalFilterInput > .input--cursor {{
        background: {COLOURS["cyan"]};
        color: {COLOURS["bg"]};
    }}
    GoalFilterInput > .input--selection {{
        background: {COLOURS["selected-bg"]};
    }}
    #goal-log-empty, #goal-items-empty {{
        content-align: center middle;
        height: 1fr;
        display: none;
        color: {COLOURS["dim"]};
    }}
    """

    def __init__(self, container, goal_id, now):
        super().__init__()
        self._container = container
        self._goal_id = goal_id
        self._now = now
        self._active_tab = GOAL_TAB_ORDER[0]
        self._view = None
        self._last_key = None
        self._poll_timer = None
        self._log_filter = ""
        self._items_filter = ""
        self._items_result = None
        self._items_rows = ()
        self._items_step_ids = {}
        self._filter_timer = None
        self._items_filter_timer = None

    def compose(self) -> ComposeResult:
        yield Static(id="goal-hub-identity")
        yield HubTabStrip(GOAL_TAB_ORDER, self._active_tab, id="hub-tabs")
        yield DescriptionPane(
            id="goal-description-view", highlight=False, markup=False, wrap=True,
            auto_scroll=False,
        )
        yield Static(GOAL_DESCRIPTION_EMPTY_MESSAGE, id="goal-description-empty")
        yield Horizontal(
            Static("SEARCH", id="goal-log-search-label", classes="filter-row-label"),
            GoalLogFilterInput(id="goal-log-filter-text"),
            id="goal-log-search-bar",
        )
        yield DescriptionPane(
            id="goal-log-view", highlight=False, markup=False, wrap=True, auto_scroll=False
        )
        yield Static(GOAL_LOG_EMPTY_MESSAGE, id="goal-log-empty")
        yield Horizontal(
            Static("SEARCH", id="goal-items-search-label", classes="filter-row-label"),
            GoalItemsFilterInput(id="goal-items-filter-text"),
            id="goal-items-search-bar",
        )
        yield GoalItemsTable(id="goal-items-table")
        yield Static(GOAL_ITEMS_EMPTY_MESSAGE, id="goal-items-empty")
        yield DashboardFooter(id="hub-footer", shortcuts=HUB_SHORTCUTS)

    def on_mount(self) -> None:
        table = self.query_one(GoalItemsTable)
        table.cursor_type = "row"
        table.show_header = False
        table.add_column("cursor", width=GLYPH_WIDTHS["cursor"], key="cursor")
        table.add_column("row", width=ITEMS_FALLBACK_WIDTH, key="row")
        self._refresh()
        self._apply_tab_visibility()
        self.call_after_refresh(self._initial_refresh)
        self._poll_timer = self.set_interval(POLL_INTERVAL_SECONDS, self.poll_refresh)

    def on_screen_suspend(self) -> None:
        self._stop_filter_timer()
        self._stop_items_filter_timer()
        if self._poll_timer is not None:
            self._poll_timer.pause()

    def on_screen_resume(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.resume()

    def on_resize(self, event: events.Resize) -> None:
        self._last_key = None
        self.call_after_refresh(self._refresh)

    def _initial_refresh(self) -> None:
        self._refresh()
        self._apply_tab_visibility()
        self._focus_active_tab()

    def poll_refresh(self) -> None:
        self._refresh()
        self._apply_tab_visibility()

    def _refresh(self) -> None:
        view = ShowGoalUseCase(self._container.store).execute(self._goal_id)
        result = GoalItemsUseCase(self._container.store, self._container.flow_service()).execute(
            self._goal_id, self._items_filter or None
        )
        rows = self._current_rows(result)
        width = self._items_width()
        key = (
            view.goal, tuple(view.log), tuple(view.items), self._log_filter, self._log_width(),
            self._items_filter, width, tuple(rows), tuple(result.backlog), tuple(result.done),
            result.total,
        )
        if key == self._last_key:
            return
        self._last_key = key
        self._view = view
        self._items_result = result
        self._items_rows = rows
        self._render_identity()
        self._render_overview()
        self._render_log()
        self._render_items()

    def _current_rows(self, result):
        suspended = suspended_step_ids(self._container.workers)
        attention, active, queued = build_priority_rows_from_selection(
            self._container.store, result.selection, suspended
        )
        rows = assemble_rows(attention, active, queued)
        queued_glyph = STATE_GLYPHS["queued"]
        for ref in result.stepless:
            rows.append(
                PriorityRow(
                    id=ref.id, step_id=ref.id, group="queued", icon=queued_glyph.glyph,
                    icon_colour=queued_glyph.colour, dependency_icon="", project="",
                    title=ref.title or "", step="", step_colour="dim", cost="", time="",
                )
            )
        return rows

    def _items_width(self) -> int:
        table = self.query_one(GoalItemsTable)
        if not table.size.width:
            return ITEMS_FALLBACK_WIDTH
        padding = 2 * table.cell_padding * 2
        return max(
            table.size.width - table.scrollbar_size_vertical - padding - GLYPH_WIDTHS["cursor"], 1
        )

    def _log_width(self) -> int:
        pane = self.query_one("#goal-log-view", DescriptionPane)
        if not pane.size.width:
            return LOG_FALLBACK_WIDTH
        return pane.size.width - pane.styles.scrollbar_size_vertical

    def _render_identity(self) -> None:
        goal = self._view.goal
        text = Text(goal.title, style=COLOURS["text"])
        text.append("  ")
        text.append(goal.status, style=COLOURS["text"])
        if goal.project:
            text.append("  ")
            text.append(goal.project, style=COLOURS["dim"])
        self.query_one("#goal-hub-identity", Static).update(text)

    def _render_overview(self) -> None:
        pane = self.query_one("#goal-description-view", DescriptionPane)
        pane.clear()
        description = self._view.goal.description
        if description:
            pane.write(Text(description, style=COLOURS["text"]))
        state_of_play = self._view.goal.state_of_play
        if state_of_play:
            width = pane.size.width - pane.styles.scrollbar_size_vertical
            if width <= 0:
                width = LOG_FALLBACK_WIDTH
            if description:
                pane.write(Text(""), width=width)
            stamp = goal_log_stamp(self._view.goal.state_of_play_at)
            for text in _header_lines(STATE_OF_PLAY_TITLE, stamp, width):
                split = len(text) - len(stamp)
                header = Text(text[:split], style=COLOURS["text"])
                header.append(text[split:], style=COLOURS["dim"])
                pane.write(header, width=width)
            pane.write(Text(""), width=width)
            pane.write(Text(state_of_play, style=COLOURS["text"]), width=width)

    def _render_log(self) -> None:
        pane = self.query_one("#goal-log-view", DescriptionPane)
        pane.clear()
        width = self._log_width()
        entries = [e for e in self._view.log if log_entry_matches(e, self._log_filter)]
        no_match = bool(self._view.log) and not entries
        self.query_one("#goal-log-empty", Static).update(
            GOAL_LOG_NO_MATCH_MESSAGE if no_match else GOAL_LOG_EMPTY_MESSAGE
        )
        for entry in entries:
            stamp = goal_log_stamp(entry.created_at)
            lines = _header_lines(entry.title, stamp, width)
            for index, text in enumerate(lines):
                if index == 0:
                    split = len(text) - len(stamp)
                    header = Text(text[:split], style=COLOURS["text"])
                    header.append(text[split:], style=COLOURS["dim"])
                    pane.write(header, width=width)
                else:
                    pane.write(Text(text, style=COLOURS["text"]), width=width)
            pane.write(Text(""), width=width)
            pane.write(Text(entry.body, style=COLOURS["text"]), width=width)
            pane.write(Text(""), width=width)

    def _render_items(self) -> None:
        table = self.query_one(GoalItemsTable)
        previous = None
        if table.row_count and 0 <= table.cursor_coordinate.row < len(table.ordered_rows):
            previous = table.ordered_rows[table.cursor_coordinate.row].key.value
        table.clear()
        result = self._items_result
        width = self._items_width()
        table.columns["row"].width = width
        table.columns["cursor"].width = GLYPH_WIDTHS["cursor"]
        rows = self._items_rows
        groups = {
            "current": [(r.id, r.step_id, r) for r in rows],
            "backlog": result.backlog,
            "done": result.done,
        }
        every = [r.id for r in rows] + [r.id for r in result.backlog] + [r.id for r in result.done]
        id_width = max((len(i) for i in every), default=0)
        first = True
        for name, label in GROUP_HEADERS:
            entries = groups[name]
            if not entries:
                continue
            header = Text(label, style=COLOURS["dim"])
            if not first:
                header = Text("\n") + header
            first = False
            table.add_row(Text(""), header, height=None, key=HEADER_KEY_PREFIX + name)
            if name == "current":
                for index, row in enumerate(rows):
                    cell = _item_cells(
                        _row_icon(row), row.id, row.title, id_width, width, row.step, row.step_colour
                    )
                    if index < len(rows) - 1:
                        cell = cell + Text(ROW_SPACER)
                    table.add_row(Text(""), cell, height=None, key=row.id)
                continue
            for index, ref in enumerate(entries):
                cell = _item_cells(Text(""), ref.id, ref.title, id_width, width)
                if index < len(entries) - 1:
                    cell = cell + Text(ROW_SPACER)
                table.add_row(Text(""), cell, height=None, key=ref.id)
        self._items_step_ids = {r.id: r.step_id for r in rows}
        self._restore_items_cursor(table, previous)

    def _restore_items_cursor(self, table, previous) -> None:
        keys = [row.key.value for row in table.ordered_rows]
        if previous in keys and not previous.startswith(HEADER_KEY_PREFIX):
            index = keys.index(previous)
        else:
            index = next(
                (i for i, k in enumerate(keys) if not k.startswith(HEADER_KEY_PREFIX)), 0
            )
        if not keys:
            return
        table.move_cursor(row=index, animate=False)
        table._paint_cursor(index, True)

    def _apply_tab_visibility(self) -> None:
        if self._view is None:
            return
        tab = self._active_tab
        overview = tab == "overview"
        has_description = bool(self._view.goal.description or self._view.goal.state_of_play)
        self.query_one("#goal-description-view", DescriptionPane).display = (
            overview and has_description
        )
        self.query_one("#goal-description-empty", Static).display = (
            overview and not has_description
        )
        has_log = bool(self._view.log)
        has_matches = any(log_entry_matches(e, self._log_filter) for e in self._view.log)
        self.query_one("#goal-log-search-bar", Horizontal).display = tab == "log" and has_log
        self.query_one("#goal-log-view", DescriptionPane).display = tab == "log" and has_matches
        self.query_one("#goal-log-empty", Static).display = tab == "log" and not has_matches
        has_items = bool(self._view.items)
        has_shown = has_items and (
            self._items_result is not None
            and bool(
                self._items_rows or self._items_result.backlog or self._items_result.done
            )
        )
        self.query_one("#goal-items-search-bar", Horizontal).display = tab == "items" and has_items
        self.query_one(GoalItemsTable).display = tab == "items" and has_shown
        self.query_one("#goal-items-empty", Static).update(
            GOAL_ITEMS_NO_MATCH_MESSAGE if has_items else GOAL_ITEMS_EMPTY_MESSAGE
        )
        self.query_one("#goal-items-empty", Static).display = tab == "items" and not has_shown
        self._sync_footer()
        if tab in ("log", "items"):
            self.call_after_refresh(self._refresh)

    def _focus_active_tab(self) -> None:
        if self._view is None:
            return
        tab = self._active_tab
        if tab == "overview" and (
            self._view.goal.description or self._view.goal.state_of_play
        ):
            self.set_focus(self.query_one("#goal-description-view", DescriptionPane))
        elif tab == "log" and self._view.log:
            self.set_focus(self.query_one("#goal-log-view", DescriptionPane))
        elif tab == "items" and self._view.items:
            self.set_focus(self.query_one(GoalItemsTable))
        else:
            self.set_focus(None)

    def _sync_footer(self) -> None:
        if self._view is None:
            return
        searchable = (
            (self._active_tab == "log" and self._view.log)
            or (self._active_tab == "items" and self._view.items)
        )
        if not searchable:
            desired = HUB_SHORTCUTS
        elif isinstance(self.focused, GoalFilterInput):
            desired = GOAL_LOG_SEARCH_SHORTCUTS
        else:
            desired = GOAL_LOG_SHORTCUTS
        bar = self.query_one(ShortcutBar)
        if bar.shortcuts != desired:
            bar.set_shortcuts(desired)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self._sync_footer()

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        self._sync_footer()

    def _stop_filter_timer(self) -> None:
        if self._filter_timer is not None:
            self._filter_timer.stop()
            self._filter_timer = None

    def _stop_items_filter_timer(self) -> None:
        if self._items_filter_timer is not None:
            self._items_filter_timer.stop()
            self._items_filter_timer = None

    def action_focus_search(self) -> None:
        if self._view is None:
            return
        if self._active_tab == "log" and self._view.log:
            self.set_focus(self.query_one(GoalLogFilterInput))
        elif self._active_tab == "items" and self._view.items:
            self.set_focus(self.query_one(GoalItemsFilterInput))

    def leave_items_filter(self) -> None:
        self._stop_items_filter_timer()
        self.on_items_filter_settled()
        self.set_focus(self.query_one(GoalItemsTable))

    def leave_log_filter(self) -> None:
        self._stop_filter_timer()
        self.on_log_filter_settled()
        self.set_focus(self.query_one("#goal-log-view", DescriptionPane))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "goal-items-filter-text":
            self._stop_items_filter_timer()
            self._items_filter_timer = self.set_timer(
                FILTER_DEBOUNCE_SECONDS, self.on_items_filter_settled
            )
            return
        if event.input.id != "goal-log-filter-text":
            return
        self._stop_filter_timer()
        self._filter_timer = self.set_timer(FILTER_DEBOUNCE_SECONDS, self.on_log_filter_settled)

    def on_items_filter_settled(self) -> None:
        self._items_filter_timer = None
        self._items_filter = self.query_one(GoalItemsFilterInput).value
        self._refresh()
        self._apply_tab_visibility()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        row_id = event.row_key.value
        if row_id is None or row_id.startswith(HEADER_KEY_PREFIX):
            return
        target = self._items_step_ids.get(row_id, row_id)
        self.app.push_screen(NodeHubScreen(self._container, target, self._now))

    def on_log_filter_settled(self) -> None:
        self._filter_timer = None
        self._log_filter = self.query_one(GoalLogFilterInput).value
        self._refresh()
        self._apply_tab_visibility()

    def _switch_tab(self, step) -> None:
        index = GOAL_TAB_ORDER.index(self._active_tab)
        self._active_tab = GOAL_TAB_ORDER[(index + step) % len(GOAL_TAB_ORDER)]
        self.query_one(HubTabStrip).set_active(self._active_tab)
        self._apply_tab_visibility()
        self._focus_active_tab()

    def action_next_tab(self) -> None:
        self._switch_tab(1)

    def action_prev_tab(self) -> None:
        self._switch_tab(-1)

    def action_close_hub(self) -> None:
        self.app.pop_screen()
