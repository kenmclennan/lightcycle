from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import DataTable, Static

from lightcycle.adapters.tui import tokens
from lightcycle.application.pool import BreakerStatusUseCase, PoolRunningUseCase
from lightcycle.application.work import QueueInput, QueueUseCase

POLL_INTERVAL_SECONDS = 10

THEME = Theme(
    name="lightcycle",
    primary=tokens.CYAN,
    warning=tokens.AMBER,
    error=tokens.RED,
    foreground=tokens.TEXT,
    background=tokens.BG,
    panel=tokens.PANEL,
    surface=tokens.BG,
    dark=True,
    variables={
        "border": tokens.BORDER,
        "dim": tokens.DIM,
        "selected-bg": tokens.SELECTED_BG,
        "block-cursor-background": tokens.SELECTED_BG,
        "block-cursor-foreground": tokens.CYAN,
    },
)


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
    pass


class FooterGroup(Vertical):
    pass


class ShortcutBar(Static):
    pass


class LightcycleApp(App):
    CSS = """
    Screen {
        border: solid $border;
    }
    TabStrip {
        dock: top;
        height: 1;
    }
    TabStrip > Static {
        width: auto;
    }
    .tab-active {
        color: $primary;
        text-style: bold;
    }
    .tab-inactive {
        color: $dim;
    }
    .tab-sep {
        color: $dim;
        padding: 0 1;
    }
    FooterGroup {
        dock: bottom;
        height: 2;
        border-top: solid $border;
        background: $background;
    }
    StatusBar {
        height: 1;
    }
    ShortcutBar {
        height: 1;
        color: $dim;
    }
    """

    def __init__(self, container):
        super().__init__()
        self.register_theme(THEME)
        self.theme = "lightcycle"
        self._container = container

    @property
    def container(self):
        return self._container

    def compose(self) -> ComposeResult:
        with TabStrip():
            yield Static("Current work", classes="tab-active")
            yield Static("·", classes="tab-sep")
            yield Static("Backlog", classes="tab-inactive")
        yield DataTable(id="priority-list")
        with FooterGroup():
            yield StatusBar(id="status-bar")
            yield ShortcutBar(id="shortcut-bar")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("id", "role", "state", "title")
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
