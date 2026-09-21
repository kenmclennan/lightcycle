import textwrap

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.geometry import Region
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
    CURSOR_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    FILTER_DEBOUNCE_SECONDS,
    GOAL_LOG_SEARCH_SHORTCUTS,
    GOAL_LOG_SHORTCUTS,
    HEADING_STYLE,
    HUB_SHORTCUTS,
    SEARCH_BAR_CSS,
    STATE_GLYPHS,
)
from lightcycle.adapters.tui.footer import DashboardFooter, ShortcutBar
from lightcycle.adapters.tui.hub import (
    HUB_TAB_STRIP_CSS,
    POLL_INTERVAL_SECONDS,
    DescriptionPane,
    pane_text_width,
    HubTabStrip,
    NodeHubScreen,
)
from lightcycle.adapters.tui.prose_text import prose_text, resolve_titles
from lightcycle.adapters.tui.priority_list import (
    PriorityRow,
    assemble_rows,
    build_priority_rows_from_selection,
)
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    apply_widths,
    compute_layout,
    wrap_continuation,
)
from lightcycle.application.goals import GoalItemsUseCase, ShowGoalUseCase, log_entry_matches
from lightcycle.application.work.suspended_steps import suspended_step_ids
from lightcycle.domain.goals import goal_log_stamp

GOAL_TAB_ORDER = ("overview", "log", "items")

GOAL_DESCRIPTION_EMPTY_MESSAGE = "No description written yet."
GOAL_LOG_EMPTY_MESSAGE = "No decisions logged yet."
GOAL_LOG_NO_MATCH_MESSAGE = "No entries match."
LOG_TITLE_STAMP_GAP = 2
GOAL_ITEMS_EMPTY_MESSAGE = "No items linked to this goal."
GOAL_ITEMS_NO_MATCH_MESSAGE = "No items match."
ITEMS_COLUMNS = COLUMN_GRIDS["goal-items"]
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


class GoalItemsList(VerticalScroll, can_focus=False):
    pass


class GoalItemsTable(DataTable):
    _BASE_BINDINGS = [b for b in DataTable.BINDINGS if b.key != "right"]

    BINDINGS = _BASE_BINDINGS + [
        Binding("right", "select_cursor", "Open", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def action_cursor_down(self) -> None:
        self.screen.step_items_cursor(1)

    def action_cursor_up(self) -> None:
        self.screen.step_items_cursor(-1)

    def action_page_down(self) -> None:
        self.screen.page_items_cursor(1)

    def action_page_up(self) -> None:
        self.screen.page_items_cursor(-1)

    def action_scroll_home(self) -> None:
        self.screen.jump_items_cursor(first=True)

    def action_scroll_top(self) -> None:
        self.screen.jump_items_cursor(first=True)

    def action_scroll_end(self) -> None:
        self.screen.jump_items_cursor(first=False)

    def action_scroll_bottom(self) -> None:
        self.screen.jump_items_cursor(first=False)

    def set_active(self, active) -> None:
        self.show_cursor = active
        self._paint_cursor(self.cursor_coordinate.row, active)

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate) -> None:
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if old_coordinate.row != new_coordinate.row:
            self._paint_cursor(old_coordinate.row, False)
            self._paint_cursor(new_coordinate.row, self.show_cursor)

    def _paint_cursor(self, row_index, show) -> None:
        if row_index < 0 or row_index >= len(self.ordered_rows):
            return
        row_key = self.ordered_rows[row_index].key
        if row_key.value is None:
            return
        value = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if show else ""
        try:
            self.update_cell(row_key, "cursor", value)
        except CellDoesNotExist:
            pass


def _item_cells(icon, item_id, title, title_width, step=None, step_colour="dim", stacked=False):
    lines = wrap_continuation(title or "", title_width)
    title_cell = Text("\n".join(lines), style=COLOURS["text"])
    if step and stacked:
        title_cell = title_cell + Text("\n") + Text(step, style=COLOURS[step_colour])
    step_cell = Text(step, style=COLOURS[step_colour]) if step and not stacked else Text("")
    return [
        Text(""), icon, Text(item_id, style=COLOURS["cyan"]), title_cell, step_cell,
    ]


def _row_icon(row):
    icon = Text(row.icon, style=COLOURS[row.icon_colour])
    if row.dependency_icon:
        icon = icon + Text(row.dependency_icon, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour])
    return icon


class GoalHubScreen(Screen, inherit_bindings=False):
    BINDINGS = [b for b in Screen.BINDINGS if b.key != "tab"] + [
        Binding("escape", "close_hub", "Back", show=False),
        Binding("tab", "close_hub", "Back", show=False),
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
    #goal-log-view, #goal-items-list {{
        height: 1fr;
        display: none;
    }}
    #goal-items-list {{
        scrollbar-gutter: stable;
    }}
    GoalItemsTable {{
        height: auto;
        max-height: 1000;
        width: 100%;
        overflow: hidden hidden;
    }}
    .goal-items-header {{
        height: auto;
        padding: 1 0 1 1;
    }}
    .goal-items-header.first-visible {{
        padding: 0 0 1 1;
    }}
    {SEARCH_BAR_CSS}
    #goal-log-search-bar, #goal-items-search-bar {{
        display: none;
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
        self._titles = {}
        self._last_key = None
        self._poll_timer = None
        self._log_filter = ""
        self._items_filter = ""
        self._items_result = None
        self._items_rows = ()
        self._items_step_ids = {}
        self._items_active = None
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
            GoalLogFilterInput(id="goal-log-filter-text", classes="search-input"),
            id="goal-log-search-bar",
            classes="search-bar",
        )
        yield DescriptionPane(
            id="goal-log-view", highlight=False, markup=False, wrap=True, auto_scroll=False
        )
        yield Static(GOAL_LOG_EMPTY_MESSAGE, id="goal-log-empty")
        yield Horizontal(
            Static("SEARCH", id="goal-items-search-label", classes="filter-row-label"),
            GoalItemsFilterInput(id="goal-items-filter-text", classes="search-input"),
            id="goal-items-search-bar",
            classes="search-bar",
        )
        with GoalItemsList(id="goal-items-list"):
            for name, label in GROUP_HEADERS:
                yield Static(
                    Text(label, style=HEADING_STYLE),
                    id=f"goal-items-header-{name}",
                    classes="goal-items-header",
                )
                yield GoalItemsTable(id=f"goal-items-table-{name}", name=name)
        yield Static(GOAL_ITEMS_EMPTY_MESSAGE, id="goal-items-empty")
        yield DashboardFooter(id="hub-footer", shortcuts=HUB_SHORTCUTS)

    def on_mount(self) -> None:
        for table in self.query(GoalItemsTable):
            table.cursor_type = "row"
            table.show_header = False
            for column in ITEMS_COLUMNS:
                table.add_column(column, width=1, key=column)
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
        overview_width = pane_text_width(self.query_one("#goal-description-view", DescriptionPane))
        log_width = self._log_width()
        titles = self._reference_titles(view)
        key = (
            view.goal, tuple(view.log), tuple(view.items), self._log_filter, log_width,
            overview_width, self._items_filter, width, tuple(rows), tuple(result.backlog), tuple(result.done),
            result.total, tuple(sorted(titles.items())),
        )
        if key == self._last_key:
            return
        self._last_key = key
        self._view = view
        self._titles = titles
        self._items_result = result
        self._items_rows = rows
        self._render_identity()
        if overview_width:
            self._render_overview(overview_width)
        if log_width:
            self._render_log()
        if width:
            self._render_items()

    def _reference_titles(self, view):
        goal = view.goal
        texts = [goal.description] + [e.body for e in view.log]
        return resolve_titles(self._container.store, "\n".join(t for t in texts if t))

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
        items_list = self.query_one("#goal-items-list", GoalItemsList)
        if not items_list.size.width:
            return 0
        return max(items_list.size.width - items_list.scrollbar_gutter.width, 1)

    def _log_width(self) -> int:
        pane = self.query_one("#goal-log-view", DescriptionPane)
        return pane_text_width(pane)

    def _render_identity(self) -> None:
        goal = self._view.goal
        text = Text(goal.title, style=COLOURS["text"])
        text.append("  ")
        text.append(goal.status, style=COLOURS["text"])
        if goal.project:
            text.append("  ")
            text.append(goal.project, style=COLOURS["dim"])
        self.query_one("#goal-hub-identity", Static).update(text)

    def _render_overview(self, width: int) -> None:
        pane = self.query_one("#goal-description-view", DescriptionPane)
        pane.clear()
        description = self._view.goal.description
        if description:
            pane.write(prose_text(description, self._titles), width=width)

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
                    header = Text(text[:split], style=HEADING_STYLE)
                    header.append(text[split:], style=COLOURS["dim"])
                    pane.write(header, width=width)
                else:
                    pane.write(Text(text, style=HEADING_STYLE), width=width)
            pane.write(Text(""), width=width)
            pane.write(prose_text(entry.body, self._titles), width=width)
            pane.write(Text(""), width=width)

    def _items_tables(self):
        return list(self.query(GoalItemsTable))

    def _visible_items_tables(self):
        return [t for t in self._items_tables() if t.display and t.row_count]

    def _items_entries(self):
        return [(t, row) for t in self._visible_items_tables() for row in range(t.row_count)]

    def _active_items_table(self):
        for table in self._visible_items_tables():
            if table.name == self._items_active:
                return table
        return None

    def _items_position(self):
        table = self._active_items_table()
        if table is None:
            return None
        return self._items_entries().index((table, table.cursor_coordinate.row))

    def _activate_items_table(self, table) -> None:
        self._items_active = table.name
        for other in self._items_tables():
            other.set_active(other is table)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if isinstance(event.widget, GoalItemsTable) and event.widget.name != self._items_active:
            self._activate_items_table(event.widget)
        self._sync_footer()

    def step_items_cursor(self, delta) -> None:
        position = self._items_position()
        if position is not None:
            self._goto_items(position + delta)

    def jump_items_cursor(self, first) -> None:
        self._goto_items(0 if first else len(self._items_entries()) - 1)

    def page_items_cursor(self, direction) -> None:
        position = self._items_position()
        if position is None:
            return
        entries = self._items_entries()
        viewport = max(self.query_one("#goal-items-list", GoalItemsList).size.height, 1)
        travelled = 0
        target = position
        while 0 <= target + direction < len(entries) and travelled < viewport:
            target += direction
            table, row = entries[target]
            travelled += table.ordered_rows[row].height
        self._goto_items(target)

    def _goto_items(self, index) -> None:
        entries = self._items_entries()
        if not entries:
            return
        index = max(0, min(index, len(entries) - 1))
        table, row = entries[index]
        was_items_focus = isinstance(self.focused, GoalItemsTable)
        self._activate_items_table(table)
        table.move_cursor(row=row, animate=False, scroll=False)
        if was_items_focus and self.focused is not table:
            self.set_focus(table, scroll_visible=False)
        self._scroll_items_to(table, row, index)

    def _scroll_items_to(self, table, row, index) -> None:
        items_list = self.query_one("#goal-items-list", GoalItemsList)
        if index == 0:
            items_list.scroll_home(animate=False, immediate=True)
            return
        top = table.virtual_region.y + sum(r.height for r in table.ordered_rows[:row])
        bottom = top + table.ordered_rows[row].height
        if row == 0:
            top = self.query_one(f"#goal-items-header-{table.name}", Static).virtual_region.y
        items_list.scroll_to_region(
            Region(0, top, max(items_list.size.width, 1), bottom - top),
            animate=False,
            immediate=True,
        )

    def _items_layout(self, rows, result, width):
        ids = [r.id for r in rows] + [r.id for r in result.backlog] + [r.id for r in result.done]
        steps = [r.step for r in rows]
        padding = 2 * self.query_one(GoalItemsTable).cell_padding * len(ITEMS_COLUMNS)
        budget = max(width - padding, 1)
        id_width = max((len(i) for i in ids), default=0)
        layout = compute_layout(
            budget, ("cursor", "icon"), {"id": ids, "step": steps},
            GLYPH_WIDTHS["cursor"] + GLYPH_WIDTHS["icon"] + id_width,
        )
        stacked = layout.stacked or layout.floor
        widths = {
            "cursor": GLYPH_WIDTHS["cursor"],
            "icon": GLYPH_WIDTHS["icon"],
            "id": layout.atomic_widths["id"],
            "step": 1 if stacked else layout.atomic_widths["step"],
        }
        title_width = budget - sum(widths.values())
        widths["title"] = max(title_width, 1)
        return widths, stacked

    def _render_items(self) -> None:
        previous = None
        active = self._active_items_table()
        if active is not None and active.row_count:
            previous = active.ordered_rows[active.cursor_coordinate.row].key.value
        was_items_focus = isinstance(self.focused, GoalItemsTable)
        result = self._items_result
        rows = self._items_rows
        widths, stacked = self._items_layout(rows, result, self._items_width())
        groups = {"current": rows, "backlog": result.backlog, "done": result.done}
        first = True
        for name, _label in GROUP_HEADERS:
            table = self.query_one(f"#goal-items-table-{name}", GoalItemsTable)
            header = self.query_one(f"#goal-items-header-{name}", Static)
            entries = groups[name]
            table.clear()
            table.display = header.display = bool(entries)
            header.set_class(bool(entries) and first, "first-visible")
            first = first and not entries
            apply_widths(table, widths)
            for entry in entries:
                if name == "current":
                    cells = _item_cells(
                        _row_icon(entry), entry.id, entry.title, widths["title"], entry.step,
                        entry.step_colour, stacked,
                    )
                    key = entry.id
                else:
                    cells = _item_cells(Text(""), entry.id, entry.title, widths["title"])
                    key = entry.id
                table.add_row(*cells, height=None, key=key)
        self._items_step_ids = {r.id: r.step_id for r in rows}
        self._restore_items_cursor(previous, was_items_focus)

    def _restore_items_cursor(self, previous, was_items_focus) -> None:
        tables = self._visible_items_tables()
        if not tables:
            self._items_active = None
            for table in self._items_tables():
                table.set_active(False)
            return
        target, index = tables[0], 0
        for table in tables:
            keys = [row.key.value for row in table.ordered_rows]
            if previous in keys:
                target, index = table, keys.index(previous)
                break
        self._activate_items_table(target)
        target.move_cursor(row=index, animate=False, scroll=False)
        target._paint_cursor(index, True)
        if was_items_focus and self.focused is not target:
            self.set_focus(target, scroll_visible=False)

    def _apply_tab_visibility(self) -> None:
        if self._view is None:
            return
        tab = self._active_tab
        overview = tab == "overview"
        has_description = bool(self._view.goal.description)
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
        self.query_one("#goal-items-list", GoalItemsList).display = tab == "items" and has_shown
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
        if tab == "overview" and self._view.goal.description:
            self.set_focus(self.query_one("#goal-description-view", DescriptionPane))
        elif tab == "log" and self._view.log:
            self.set_focus(self.query_one("#goal-log-view", DescriptionPane))
        elif tab == "items" and self._view.items:
            self.set_focus(self._items_focus_target())
        else:
            self.set_focus(None)

    def _items_focus_target(self):
        return (
            self._active_items_table()
            or next(iter(self._visible_items_tables()), None)
            or self.query_one("#goal-items-table-current", GoalItemsTable)
        )

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
        self.set_focus(self._items_focus_target())

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
        if row_id is None:
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
