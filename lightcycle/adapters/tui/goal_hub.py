from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static

from lightcycle.adapters.tui.design_system import COLOURS, HUB_SHORTCUTS
from lightcycle.adapters.tui.footer import DashboardFooter
from lightcycle.adapters.tui.hub import (
    HUB_TAB_STRIP_CSS,
    POLL_INTERVAL_SECONDS,
    DescriptionPane,
    HubTabStrip,
)
from lightcycle.application.goals import ShowGoalUseCase

GOAL_TAB_ORDER = ("overview", "log", "items")

GOAL_DESCRIPTION_EMPTY_MESSAGE = "No description written yet."
GOAL_LOG_EMPTY_MESSAGE = "No decisions logged yet."
GOAL_ITEMS_EMPTY_MESSAGE = "No items linked to this goal."


def _stamp(value):
    return (value or "")[:16].replace("T", " ")


class GoalItemsTable(DataTable):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)


class GoalHubScreen(Screen, inherit_bindings=False):
    BINDINGS = [b for b in Screen.BINDINGS if b.key != "tab"] + [
        Binding("escape", "close_hub", "Back", show=False),
        Binding("left", "close_hub", "Back", show=False),
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

    def compose(self) -> ComposeResult:
        yield Static(id="goal-hub-identity")
        yield HubTabStrip(GOAL_TAB_ORDER, self._active_tab, id="hub-tabs")
        yield DescriptionPane(
            id="goal-description-view", highlight=False, markup=False, wrap=True,
            auto_scroll=False,
        )
        yield Static(GOAL_DESCRIPTION_EMPTY_MESSAGE, id="goal-description-empty")
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
        key = (view.goal, tuple(view.log), tuple(view.items))
        if key == self._last_key:
            return
        self._last_key = key
        self._view = view
        self._render_identity()
        self._render_overview()
        self._render_log()
        self._render_items()

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
        for entry in self._view.log:
            line = Text(_stamp(entry.created_at), style=COLOURS["dim"])
            line.append("  ")
            line.append(entry.body, style=COLOURS["text"])
            pane.write(line)

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
        self.query_one("#goal-log-view", DescriptionPane).display = tab == "log" and has_log
        self.query_one("#goal-log-empty", Static).display = tab == "log" and not has_log
        has_items = bool(self._view.items)
        self.query_one(GoalItemsTable).display = tab == "items" and has_items
        self.query_one("#goal-items-empty", Static).display = tab == "items" and not has_items

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
