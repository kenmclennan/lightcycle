from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, Static

from lightcycle.adapters.tui.design_system import COLOURS
from lightcycle.adapters.tui.views.report_markdown import report_markdown


class ReportView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._day = None

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("DAY", id="report-day-filter-label", classes="filter-row-label"),
            Static(id="report-day-filter-left"),
            Static(id="report-day-filter-right"),
            id="report-day-filter-bar",
        )
        yield Static("Loading report...", id="report-loading")
        yield VerticalScroll(Markdown(id="report-markdown"), id="report-body")

    def on_mount(self) -> None:
        self.query_one("#report-body", VerticalScroll).display = False
        self.query_one("#report-loading", Static).display = False

    @property
    def shown_day(self):
        return self._day

    def show_loading(self, day, message="Loading report...") -> None:
        self._day = None
        self.query_one("#report-day-filter-left", Static).update(
            Text(day.isoformat(), style=COLOURS["text"])
        )
        self.query_one("#report-body", VerticalScroll).display = False
        loading = self.query_one("#report-loading", Static)
        loading.update(Text(message, style=COLOURS["dim"]))
        loading.display = True

    def apply_report(self, response) -> None:
        self._day = response.day
        self.query_one("#report-loading", Static).display = False
        self.query_one("#report-day-filter-left", Static).update(
            Text(response.day.isoformat(), style=COLOURS["text"])
        )
        self.query_one("#report-day-filter-right", Static).display = False
        markdown = self.query_one("#report-markdown", Markdown)
        document = report_markdown(response)
        if document != markdown.source:
            markdown.update(document)
        self.query_one("#report-body", VerticalScroll).display = True
