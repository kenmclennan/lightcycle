from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
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

GOAL_TAB_ORDER = ("overview", "log", "questions", "items")

GOAL_OUTCOME_EMPTY_MESSAGE = "No outcome written yet."
GOAL_SCOPE_EMPTY_MESSAGE = "No scope written yet."
GOAL_LOG_EMPTY_MESSAGE = "No decisions logged yet."
GOAL_QUESTIONS_EMPTY_MESSAGE = "No open questions."
GOAL_ITEMS_EMPTY_MESSAGE = "No items linked to this goal."
GOAL_PROGRESS_NOT_BUILT_MESSAGE = "Progress statement: not built yet."


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
    #goal-overview {{
        height: 1fr;
    }}
    .goal-section {{
        height: 1fr;
    }}
    .goal-section-label {{
        height: 1;
        color: {COLOURS["dim"]};
    }}
    .goal-section DescriptionPane {{
        height: 1fr;
    }}
    .goal-section .goal-empty {{
        height: 1fr;
        color: {COLOURS["dim"]};
        display: none;
    }}
    #goal-status, #goal-progress {{
        height: 1;
    }}
    #goal-progress {{
        color: {COLOURS["dim"]};
    }}
    #goal-log-view, #goal-questions-view, GoalItemsTable {{
        height: 1fr;
        display: none;
    }}
    #goal-log-empty, #goal-questions-empty, #goal-items-empty {{
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
        with Vertical(id="goal-overview"):
            yield Static(id="goal-status")
            with Vertical(classes="goal-section", id="goal-outcome-section"):
                yield Static("OUTCOME", classes="goal-section-label")
                yield DescriptionPane(
                    id="goal-outcome-view", highlight=False, markup=False, wrap=True,
                    auto_scroll=False,
                )
                yield Static(GOAL_OUTCOME_EMPTY_MESSAGE, id="goal-outcome-empty", classes="goal-empty")
            with Vertical(classes="goal-section", id="goal-scope-section"):
                yield Static("SCOPE", classes="goal-section-label")
                yield DescriptionPane(
                    id="goal-scope-view", highlight=False, markup=False, wrap=True,
                    auto_scroll=False,
                )
                yield Static(GOAL_SCOPE_EMPTY_MESSAGE, id="goal-scope-empty", classes="goal-empty")
            yield Static(GOAL_PROGRESS_NOT_BUILT_MESSAGE, id="goal-progress")
        yield DescriptionPane(
            id="goal-log-view", highlight=False, markup=False, wrap=True, auto_scroll=False
        )
        yield Static(GOAL_LOG_EMPTY_MESSAGE, id="goal-log-empty")
        yield DescriptionPane(
            id="goal-questions-view", highlight=False, markup=False, wrap=True, auto_scroll=False
        )
        yield Static(GOAL_QUESTIONS_EMPTY_MESSAGE, id="goal-questions-empty")
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
        open_questions = [q for q in view.questions if q.resolved_at is None]
        key = (view.goal, tuple(view.log), tuple(open_questions), tuple(view.items))
        if key == self._last_key:
            return
        self._last_key = key
        self._view = view._replace(questions=open_questions)
        self._render_identity()
        self._render_overview()
        self._render_log()
        self._render_questions()
        self._render_items()

    def _render_identity(self) -> None:
        goal = self._view.goal
        text = Text(goal.id, style=COLOURS["cyan"])
        text.append("  ")
        text.append(goal.title, style=COLOURS["text"])
        self.query_one("#goal-hub-identity", Static).update(text)

    def _write_prose(self, name, value) -> None:
        pane = self.query_one("#goal-%s-view" % name, DescriptionPane)
        pane.clear()
        if value:
            pane.write(Text(value, style=COLOURS["text"]))

    def _render_overview(self) -> None:
        goal = self._view.goal
        status = Text("status  ", style=COLOURS["dim"])
        status.append(goal.status, style=COLOURS["text"])
        self.query_one("#goal-status", Static).update(status)
        self._write_prose("outcome", goal.outcome)
        self._write_prose("scope", goal.scope)

    def _render_log(self) -> None:
        pane = self.query_one("#goal-log-view", DescriptionPane)
        pane.clear()
        for entry in self._view.log:
            line = Text(_stamp(entry.created_at), style=COLOURS["dim"])
            line.append("  ")
            line.append(entry.body, style=COLOURS["text"])
            pane.write(line)

    def _render_questions(self) -> None:
        pane = self.query_one("#goal-questions-view", DescriptionPane)
        pane.clear()
        for question in self._view.questions:
            line = Text("#%d" % question.id, style=COLOURS["cyan"])
            line.append("  ")
            line.append(question.body, style=COLOURS["text"])
            line.append("  %s" % _stamp(question.raised_at), style=COLOURS["dim"])
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
        self.query_one("#goal-overview", Vertical).display = overview
        goal = self._view.goal
        self.query_one("#goal-outcome-view", DescriptionPane).display = overview and bool(goal.outcome)
        self.query_one("#goal-outcome-empty", Static).display = overview and not goal.outcome
        self.query_one("#goal-scope-view", DescriptionPane).display = overview and bool(goal.scope)
        self.query_one("#goal-scope-empty", Static).display = overview and not goal.scope
        has_log = bool(self._view.log)
        self.query_one("#goal-log-view", DescriptionPane).display = tab == "log" and has_log
        self.query_one("#goal-log-empty", Static).display = tab == "log" and not has_log
        has_questions = bool(self._view.questions)
        self.query_one("#goal-questions-view", DescriptionPane).display = (
            tab == "questions" and has_questions
        )
        self.query_one("#goal-questions-empty", Static).display = (
            tab == "questions" and not has_questions
        )
        has_items = bool(self._view.items)
        self.query_one(GoalItemsTable).display = tab == "items" and has_items
        self.query_one("#goal-items-empty", Static).display = tab == "items" and not has_items

    def _focus_active_tab(self) -> None:
        if self._view is None:
            return
        tab = self._active_tab
        if tab == "overview":
            goal = self._view.goal
            if goal.outcome:
                self.set_focus(self.query_one("#goal-outcome-view", DescriptionPane))
            elif goal.scope:
                self.set_focus(self.query_one("#goal-scope-view", DescriptionPane))
            else:
                self.set_focus(None)
        elif tab == "log" and self._view.log:
            self.set_focus(self.query_one("#goal-log-view", DescriptionPane))
        elif tab == "questions" and self._view.questions:
            self.set_focus(self.query_one("#goal-questions-view", DescriptionPane))
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
