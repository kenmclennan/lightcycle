
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
)
from lightcycle.adapters.tui.hub import _format_item_cost
from lightcycle.adapters.tui.row_grid import (
    compute_layout,
    floor_message,
    pad_field,
    render_screen_row_budget,
    screen_row_budget_for,
    stacked_cell,
)
from lightcycle.render import format_elapsed
from lightcycle.adapters.tui.views.tables import STACKED_COLUMN_KEY, PagingTable

REPORT_COLUMNS = COLUMN_GRIDS["report"]
REPORT_CONTINUATION_INDENT = 2


def _report_rows(response):
    delta = response.backlog_delta
    delta_text = "+%d" % delta if delta >= 0 else str(delta)
    slow_rows = tuple(
        (slow.step.id, "%s - %s active - %s" % (slow.step.stage, format_elapsed(slow.active_seconds), slow.kind))
        for slow in response.slow_steps
    )
    return (
        ("Items Completed", str(response.completed)),
        ("Items Closed", str(response.completed + response.abandoned)),
        ("Spend", _format_item_cost(response.spend)),
        ("Automation Items", str(response.automation_count)),
        ("Automation Spend", _format_item_cost(response.automation_spend)),
        ("Escalations", str(response.escalations)),
        ("Slow Steps", str(len(response.slow_steps))),
    ) + slow_rows + (
        ("Starting Backlog Size", str(response.backlog_start)),
        ("Closing Backlog Size", str(response.backlog_close)),
        ("Backlog Delta", delta_text),
    )


def _report_row_cells(field, layout, row_budget):
    key, value = field
    if layout.stacked:
        key_field = pad_field(Text(key, style=COLOURS["dim"]), layout.atomic_widths["key"])
        return (
            stacked_cell(key_field, REPORT_CONTINUATION_INDENT, value, row_budget, prose_style=COLOURS["text"]),
        )
    return (Text(key, style=COLOURS["dim"]), Text(value, style=COLOURS["text"]))


class ReportTable(PagingTable):
    def on_resize(self, event: events.Resize) -> None:
        view = self.parent
        if isinstance(view, ReportView):
            view.refresh_column_width()

    def on_show(self, event: events.Show) -> None:
        view = self.parent
        if isinstance(view, ReportView):
            view.refresh_column_width()




class ReportView(Vertical):
    can_focus = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._day = None
        self._rows = ()
        self._floor = False
        self._report_stacked = False

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("DAY", id="report-day-filter-label", classes="filter-row-label"),
            Static(id="report-day-filter-left"),
            Static(id="report-day-filter-right"),
            id="report-day-filter-bar",
        )
        yield ReportTable(id="report-table")
        yield Static(id="report-floor")
        yield Static("Loading report...", id="report-loading")
        yield VerticalScroll(Static(id="report-summary-text"), id="report-summary")

    def on_mount(self) -> None:
        table = self.query_one(ReportTable)
        table.cursor_type = "none"
        table.show_header = False
        table.display = False
        self.query_one("#report-summary", VerticalScroll).display = False
        self.query_one("#report-loading", Static).display = False

    @property
    def shown_day(self):
        return self._day

    def show_loading(self, day, message="Loading report...") -> None:
        self._day = None
        self._rows = ()
        self.query_one("#report-day-filter-left", Static).update(
            Text(day.isoformat(), style=COLOURS["text"])
        )
        self.query_one(ReportTable).display = False
        self.query_one("#report-floor", Static).display = False
        self.query_one("#report-summary", VerticalScroll).display = False
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
        summary_widget = self.query_one("#report-summary", VerticalScroll)
        if response.summary:
            self.query_one("#report-summary-text", Static).update(
                Text(response.summary, style=COLOURS["text"])
            )
            summary_widget.display = True
            summary_widget.scroll_home(animate=False)
        else:
            summary_widget.display = False
        self._rebuild_table(_report_rows(response))

    def refresh_column_width(self) -> None:
        self._rebuild_table(self._rows)

    def _layout(self, table):
        atomic_values = {"key": [key for key, _value in self._rows]}
        row_budget = screen_row_budget_for(table, len(REPORT_COLUMNS))
        return compute_layout(row_budget, [], atomic_values, indent=REPORT_CONTINUATION_INDENT)

    def _rebuild_table(self, rows) -> None:
        table = self.query_one(ReportTable)
        self._rows = rows
        layout = self._layout(table)
        self._report_stacked = layout.stacked
        self._floor = layout.floor
        floor_widget = self.query_one("#report-floor", Static)
        if self._floor:
            table.display = False
            floor_widget.display = True
            floor_widget.update(
                Text(floor_message(layout, table, len(REPORT_COLUMNS)), style=COLOURS["dim"])
            )
            return
        table.display = True
        floor_widget.display = False

        table.clear(columns=True)
        row_budget = render_screen_row_budget(table, layout, len(REPORT_COLUMNS))
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {"key": layout.atomic_widths["key"], "value": layout.flexible_width}
            for key in REPORT_COLUMNS:
                table.add_column(key, width=widths[key], key=key)

        for field in rows:
            table.add_row(*_report_row_cells(field, layout, row_budget), height=None, key=field[0])


