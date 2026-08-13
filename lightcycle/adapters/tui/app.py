from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static

from lightcycle.adapters.tui.design_system import COLOURS, GLOBAL_SHORTCUTS
from lightcycle.application.pool import BreakerStatusUseCase, PoolRunningUseCase
from lightcycle.application.work import QueueInput, QueueUseCase

POLL_INTERVAL_SECONDS = 10


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
        color: {COLOURS["cyan"]};
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

    def __init__(self, container):
        super().__init__()
        self._container = container

    @property
    def container(self):
        return self._container

    def compose(self) -> ComposeResult:
        yield TabStrip(id="tab-strip")
        yield DataTable(id="priority-list")
        yield DashboardFooter(id="footer")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("id", "role", "state", "title")
        self._refresh()
        self.set_interval(POLL_INTERVAL_SECONDS, self._refresh)

    def _refresh(self) -> None:
        steps = QueueUseCase(self._container.store).execute(QueueInput(n=None)).steps
        table = self.query_one(DataTable)
        table.clear()
        for step in steps:
            table.add_row(step.id, step.role, step.state, step.title, key=step.id)

        running = PoolRunningUseCase(self._container.lock).execute().running
        breaker = BreakerStatusUseCase(self._container.breaker).execute()
        self.query_one(StatusBar).report(
            running=running, is_open=breaker.is_open, reset_at=breaker.reset_at
        )


def run(container):
    LightcycleApp(container).run()
