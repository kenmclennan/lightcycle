import textwrap

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static

from lightcycle.adapters.tui.design_system import (
    COLOURS,
    FILTER_DEBOUNCE_SECONDS,
    GOAL_LOG_SEARCH_SHORTCUTS,
    GOAL_LOG_SHORTCUTS,
    HUB_SHORTCUTS,
)
from lightcycle.adapters.tui.footer import DashboardFooter, ShortcutBar
from lightcycle.adapters.tui.hub import (
    HUB_TAB_STRIP_CSS,
    POLL_INTERVAL_SECONDS,
    DescriptionPane,
    HubTabStrip,
)
from lightcycle.application.goals import ShowGoalUseCase, log_entry_matches
from lightcycle.domain.goals import goal_log_stamp

GOAL_TAB_ORDER = ("overview", "log", "items")

GOAL_DESCRIPTION_EMPTY_MESSAGE = "No description written yet."
GOAL_LOG_EMPTY_MESSAGE = "No decisions logged yet."
GOAL_LOG_NO_MATCH_MESSAGE = "No entries match."
LOG_TITLE_STAMP_GAP = 2
LOG_FALLBACK_WIDTH = 80
GOAL_ITEMS_EMPTY_MESSAGE = "No items linked to this goal."


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


class GoalLogFilterInput(Input):
    BINDINGS = [
        Binding("escape", "leave_filter", "Back", show=False),
        Binding("tab", "leave_filter", "Back", show=False),
        Binding("down", "leave_filter", "Log", show=False),
        Binding("up", "leave_filter", "Log", show=False),
        Binding("enter", "leave_filter", "Log", show=False),
    ]

    def action_leave_filter(self) -> None:
        self.screen.leave_log_filter()


class GoalItemsTable(DataTable):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)


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
    #goal-log-search-bar {{
        height: 1;
        margin-top: 1;
        display: none;
    }}
    #goal-log-search-bar:focus-within .filter-row-label {{
        color: {COLOURS["cyan"]};
    }}
    GoalLogFilterInput {{
        border: none;
        padding: 0;
        height: 1;
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
    }}
    GoalLogFilterInput:focus {{
        background: {COLOURS["bg"]};
        background-tint: 0%;
    }}
    GoalLogFilterInput > .input--placeholder {{
        color: {COLOURS["dim"]};
    }}
    GoalLogFilterInput > .input--cursor {{
        background: {COLOURS["cyan"]};
        color: {COLOURS["bg"]};
    }}
    GoalLogFilterInput > .input--selection {{
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
        self._filter_timer = None

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
        yield GoalItemsTable(id="goal-items-table")
        yield Static(GOAL_ITEMS_EMPTY_MESSAGE, id="goal-items-empty")
        yield DashboardFooter(id="hub-footer", shortcuts=HUB_SHORTCUTS)

    def on_mount(self) -> None:
        table = self.query_one(GoalItemsTable)
        table.cursor_type = "row"
        table.show_header = False
        table.add_column("id", key="id")
        table.add_column("title", key="title")
        self._refresh()
        self._apply_tab_visibility()
        self.call_after_refresh(self._initial_refresh)
        self._poll_timer = self.set_interval(POLL_INTERVAL_SECONDS, self.poll_refresh)

    def on_screen_suspend(self) -> None:
        self._stop_filter_timer()
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
        key = (view.goal, tuple(view.log), tuple(view.items), self._log_filter, self._log_width())
        if key == self._last_key:
            return
        self._last_key = key
        self._view = view
        self._render_identity()
        self._render_overview()
        self._render_log()
        self._render_items()

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
        table.clear()
        for ref in self._view.items:
            table.add_row(
                Text(ref.id, style=COLOURS["cyan"]),
                Text(ref.title or "", style=COLOURS["text"]),
                key=ref.id,
            )

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
        self.query_one(GoalItemsTable).display = tab == "items" and has_items
        self.query_one("#goal-items-empty", Static).display = tab == "items" and not has_items
        self._sync_footer()
        if tab == "log":
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
            self.set_focus(self.query_one(GoalItemsTable))
        else:
            self.set_focus(None)

    def _sync_footer(self) -> None:
        if self._view is None:
            return
        if self._active_tab != "log" or not self._view.log:
            desired = HUB_SHORTCUTS
        elif self.focused is self.query_one(GoalLogFilterInput):
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

    def action_focus_search(self) -> None:
        if self._active_tab != "log" or self._view is None or not self._view.log:
            return
        self.set_focus(self.query_one(GoalLogFilterInput))

    def leave_log_filter(self) -> None:
        self._stop_filter_timer()
        self.on_log_filter_settled()
        self.set_focus(self.query_one("#goal-log-view", DescriptionPane))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "goal-log-filter-text":
            return
        self._stop_filter_timer()
        self._filter_timer = self.set_timer(FILTER_DEBOUNCE_SECONDS, self.on_log_filter_settled)

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
