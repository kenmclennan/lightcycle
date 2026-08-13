import datetime

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

from lightcycle.application.pool import BreakerStatusUseCase, PoolRunningUseCase
from lightcycle.application.work import StatusUseCase
from lightcycle.adapters.tui.priority_list import build_snapshot

POLL_INTERVAL_SECONDS = 10

COLUMN_WIDTHS = {"icon": 4, "id": 9, "project": 10, "step": 16, "time": 8}
COLUMN_PADDING = 2
MIN_TITLE_WIDTH = 20

COLOR_RED = "#e05f6b"
COLOR_CYAN = "#5fd7e0"
COLOR_DIM = "#6e6e78"
COLOR_AMBER = "#e0a95f"

GROUP_COLOR = {"attention": COLOR_RED, "active": COLOR_CYAN, "queued": COLOR_DIM}


def _title_width(app_width):
    fixed_total = sum(COLUMN_WIDTHS.values())
    other_padding = COLUMN_PADDING * (len(COLUMN_WIDTHS) + 1)
    return max(app_width - fixed_total - other_padding, MIN_TITLE_WIDTH)


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


def _gap_row_cells():
    return ("", "", "", "", "", "")


def _row_cells(row):
    icon = Text(row.icon, style=GROUP_COLOR[row.group])
    step_color = COLOR_AMBER if row.step_attention else COLOR_DIM
    step = Text(row.step, style=step_color)
    project = Text(row.project, style=COLOR_CYAN) if row.project else row.project
    time = Text(row.time, style=COLOR_DIM)
    return (icon, row.id, project, row.title, step, time)


class LightcycleApp(App):
    CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
    }
    """

    def __init__(self, container, now=datetime.datetime.now):
        super().__init__()
        self._container = container
        self._now = now
        self._last_shape = None
        self._last_attention_ids = None
        self._last_rows = {}

    @property
    def container(self):
        return self._container

    def compose(self) -> ComposeResult:
        yield DataTable(id="priority-list")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("", width=COLUMN_WIDTHS["icon"], key="icon")
        table.add_column("id", width=COLUMN_WIDTHS["id"], key="id")
        table.add_column("project", width=COLUMN_WIDTHS["project"], key="project")
        table.add_column("title", width=_title_width(self.size.width), key="title")
        table.add_column("step", width=COLUMN_WIDTHS["step"], key="step")
        table.add_column("time", width=COLUMN_WIDTHS["time"], key="time")
        self._refresh()
        self.set_interval(POLL_INTERVAL_SECONDS, self._refresh)

    def on_resize(self, event) -> None:
        table = self.query_one(DataTable)
        if "title" in table.columns:
            table.columns["title"].width = _title_width(event.size.width)

    def _rebuild_table(self, attention, active, queued):
        table = self.query_one(DataTable)
        table.columns["title"].width = _title_width(self.size.width)
        table.clear()
        groups = [g for g in (attention, active, queued) if g]
        gap_count = 0
        for i, group in enumerate(groups):
            if i > 0:
                gap_count += 1
                table.add_row(*_gap_row_cells(), key="__gap_%d__" % gap_count, height=1)
            for row in group:
                table.add_row(*_row_cells(row), key=row.id, height=None)

    def _update_cells(self, rows):
        table = self.query_one(DataTable)
        for row in rows:
            previous = self._last_rows.get(row.id)
            cells = _row_cells(row)
            for field, value in zip(("icon", "id", "project", "title", "step", "time"), cells):
                if previous is None or getattr(previous, field) != getattr(row, field):
                    table.update_cell(row.id, field, value)

    def _refresh(self) -> None:
        lanes = StatusUseCase(self._container.store).execute().lanes
        now = self._now().isoformat()
        attention, active, queued = build_snapshot(self._container.store, lanes, now)
        shape = (
            tuple(r.id for r in attention),
            tuple(r.id for r in active),
            tuple(r.id for r in queued),
        )

        if self._last_attention_ids is not None:
            if set(shape[0]) - self._last_attention_ids:
                self.bell()

        if shape == self._last_shape:
            self._update_cells(attention + active + queued)
        else:
            self._rebuild_table(attention, active, queued)

        self._last_shape = shape
        self._last_attention_ids = set(shape[0])
        self._last_rows = {r.id: r for r in attention + active + queued}

        running = PoolRunningUseCase(self._container.lock).execute().running
        breaker = BreakerStatusUseCase(self._container.breaker).execute()
        self.query_one(StatusBar).report(
            running=running, is_open=breaker.is_open, reset_at=breaker.reset_at
        )


def run(container):
    LightcycleApp(container).run()
