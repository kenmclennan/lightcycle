
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from lightcycle.adapters.tui.design_system import (
    COLOURS,
)
from lightcycle.application.work.project_of import short_project_label
from lightcycle.adapters.tui.views.tables import PagingTable

GOALS_EMPTY_MESSAGE = "No goals yet."


class GoalsTable(PagingTable):
    pass


class GoalsView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_shape = None
        self._count = 0

    def compose(self) -> ComposeResult:
        goals_table = GoalsTable(id="goals-table")
        goals_table.display = False
        yield goals_table
        yield Static(GOALS_EMPTY_MESSAGE, id="goals-empty")

    def on_mount(self) -> None:
        table = self.query_one(GoalsTable)
        table.cursor_type = "row"
        table.show_header = False
        table.add_column("project", key="project")
        table.add_column("title", key="title")
        table.add_column("status", key="status")

    @property
    def count(self) -> int:
        return self._count

    def apply_goals(self, goals) -> None:
        shape = tuple((g.id, g.project, g.title, g.status) for g in goals)
        table = self.query_one(GoalsTable)
        if shape != self._last_shape:
            self._last_shape = shape
            previous = None
            if table.row_count and table.cursor_row < len(table.ordered_rows):
                previous = table.ordered_rows[table.cursor_row].key.value
            table.clear()
            for goal in goals:
                project = short_project_label(goal.project)
                done = goal.status == "done"
                title_style = "%s strike" % COLOURS["dim"] if done else COLOURS["text"]
                table.add_row(
                    Text(project, style=COLOURS["cyan"]),
                    Text(goal.title, style=title_style),
                    Text(goal.status, style=COLOURS["dim"]),
                    key=goal.id,
                )
            if previous is not None:
                for index, row in enumerate(table.ordered_rows):
                    if row.key.value == previous:
                        table.move_cursor(row=index)
                        break
        self._count = len(goals)
        table.display = bool(goals)
        self.query_one("#goals-empty", Static).display = not goals


