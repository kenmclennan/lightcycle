from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

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


class LightcycleApp(App):
    CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
    }
    """

    def __init__(self, container):
        super().__init__()
        self._container = container

    @property
    def container(self):
        return self._container

    def compose(self) -> ComposeResult:
        yield DataTable(id="priority-list")
        yield StatusBar(id="status-bar")

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
