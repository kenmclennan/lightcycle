import datetime
import time

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle.adapters.tui.backlog_list import build_backlog_rows
from lightcycle.adapters.tui.design_system import (
    ACTIVE_GLYPH_FRAMES,
    ACTIVE_GLYPH_REST_INDEX,
    ACTIVE_GLYPH_TICKS_PER_SECOND,
    BACKLOG_EMPTY_SHORTCUTS,
    BACKLOG_FILTERED_EMPTY_SHORTCUTS,
    BACKLOG_SEARCH_EMPTY_SHORTCUTS,
    BACKLOG_SEARCH_SHORTCUTS,
    BACKLOG_SHORTCUTS,
    COLOURS,
    CURSOR_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    DONE_EMPTY_SHORTCUTS,
    DONE_FILTERED_EMPTY_SHORTCUTS,
    DONE_SEARCH_EMPTY_SHORTCUTS,
    DONE_SEARCH_SHORTCUTS,
    DONE_SHORTCUTS,
    FILTER_DEBOUNCE_SECONDS,
    FILTER_ROW_LABEL_WIDTH,
    GLOBAL_SHORTCUTS,
    REPORT_SHORTCUTS,
    ROW_SPACER,
    SEARCH_BAR_CSS,
    next_active_glyph_frame,
)
from lightcycle.adapters.tui.done_list import build_done_rows
from lightcycle.adapters.tui.footer import DashboardFooter, ShortcutBar, StatusBar
from lightcycle.adapters.tui.hub import NodeHubScreen
from lightcycle.adapters.tui.priority_list import assemble_rows, build_priority_rows_from_selection
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    apply_widths,
    compute_layout,
    floor_message,
    pad_atomic_field,
    pad_field,
    pad_field_right,
    render_screen_row_budget,
    screen_row_budget_for,
    stacked_cell,
)
from lightcycle.application.pool import (
    BreakerStatusUseCase,
    DrainPoolUseCase,
    GithubBudgetUseCase,
    HealthIconUseCase,
    LiveWorkerCountUseCase,
    PoolDrainStatusUseCase,
    PoolHoldStatusUseCase,
    PoolRunningUseCase,
    StartPoolUseCase,
    StopPoolSignalUseCase,
    TickHealthUseCase,
)
from lightcycle.application.inspect import DoctorInput
from lightcycle.application.setup import UpgradeNoticeUseCase, upgrade
from lightcycle.application.work import (
    BacklogInput,
    BacklogUseCase,
    CATEGORY_ALL,
    CATEGORY_AUTOMATION,
    CATEGORY_NO_AUTOMATION,
    DoneInput,
    DoneUseCase,
    ReportInput,
    ReportUseCase,
    StatusUseCase,
)
from lightcycle.application.work.priority_rows import select_priority_rows
from lightcycle.adapters.tui.views.tables import STACKED_COLUMN_KEY, FilterLineRest, FilterBlock, _update_cell_if_changed, PagingTable, CursorGlyphTable, _repaint_stacked_cursor
from lightcycle.adapters.tui.views.backlog import BACKLOG_COLUMNS, BACKLOG_CONTINUATION_INDENT, BacklogTable, _backlog_stacked_first_line, _backlog_title_prose, _backlog_title_cell, _backlog_row_cells, _backlog_stacked_cell_builder, BacklogFilterInput, BacklogView
from lightcycle.adapters.tui.views.done import DONE_COLUMNS, DONE_CONTINUATION_INDENT, DoneTable, _done_stacked_first_line, _done_row_cells, _done_stacked_cell_builder, DoneFilterInput, DoneView
from lightcycle.adapters.tui.views.report import REPORT_COLUMNS, REPORT_CONTINUATION_INDENT, _report_rows, _report_row_cells, ReportTable, ReportView
from lightcycle.adapters.tui.modals import PICKER_CANCELLED, POOL_PROMPT_CANCELLED, POOL_PROMPT_STOP, POOL_PROMPT_DRAIN, POOL_PROMPT_QUIT_LEAVE, POOL_PROMPT_QUIT_STOP, POOL_PROMPT_MIN_WIDTH, PICKER_MIN_WIDTH, PICKER_BORDER_WIDTH, PICKER_PADDING_WIDTH, PICKER_CURSOR_PREFIX_WIDTH, PICKER_COLUMN_GAP, ProjectFilterPicker, PoolPromptScreen, pool_prompt_body, PickerOption

__all__ = [
    "STACKED_COLUMN_KEY",
    "FilterLineRest",
    "FilterBlock",
    "_update_cell_if_changed",
    "PagingTable",
    "CursorGlyphTable",
    "_repaint_stacked_cursor",
    "BACKLOG_COLUMNS",
    "BACKLOG_CONTINUATION_INDENT",
    "BacklogTable",
    "_backlog_stacked_first_line",
    "_backlog_title_prose",
    "_backlog_title_cell",
    "_backlog_row_cells",
    "_backlog_stacked_cell_builder",
    "BacklogFilterInput",
    "BacklogView",
    "DONE_COLUMNS",
    "DONE_CONTINUATION_INDENT",
    "DoneTable",
    "_done_stacked_first_line",
    "_done_row_cells",
    "_done_stacked_cell_builder",
    "DoneFilterInput",
    "DoneView",
    "REPORT_COLUMNS",
    "REPORT_CONTINUATION_INDENT",
    "_report_rows",
    "_report_row_cells",
    "ReportTable",
    "ReportView",
    "PICKER_CANCELLED",
    "POOL_PROMPT_CANCELLED",
    "POOL_PROMPT_STOP",
    "POOL_PROMPT_DRAIN",
    "POOL_PROMPT_QUIT_LEAVE",
    "POOL_PROMPT_QUIT_STOP",
    "POOL_PROMPT_MIN_WIDTH",
    "PICKER_MIN_WIDTH",
    "PICKER_BORDER_WIDTH",
    "PICKER_PADDING_WIDTH",
    "PICKER_CURSOR_PREFIX_WIDTH",
    "PICKER_COLUMN_GAP",
    "ProjectFilterPicker",
    "PoolPromptScreen",
    "pool_prompt_body",
    "PickerOption",
]


POLL_INTERVAL_SECONDS = 10
POOL_TRANSITION_POLL_SECONDS = 1
POOL_START_TIMEOUT_SECONDS = 15

DATA_COLUMNS = ("cursor", "icon", "id", "project", "title", "step", "cost", "time")

EMPTY_STATE_MESSAGE = "Nothing needs attention. Nothing's active. Nothing's queued."



_VIEW_CYCLE = ("priority", "backlog", "done", "report")


PRIORITY_CONTINUATION_INDENT = GLYPH_WIDTHS["cursor"] + GLYPH_WIDTHS["icon"]




class TabStrip(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("Current work", id="tab-current-work", classes="tab-active")
        yield Static(" · ", classes="tab-separator")
        yield Static("Backlog", id="tab-backlog", classes="tab-dim")
        yield Static(" · ", classes="tab-separator")
        yield Static("Done", id="tab-done", classes="tab-dim")
        yield Static(" · ", classes="tab-separator")
        yield Static("Report", id="tab-report", classes="tab-dim")

    def set_active(self, view) -> None:
        widgets = {
            "priority": self.query_one("#tab-current-work", Static),
            "backlog": self.query_one("#tab-backlog", Static),
            "done": self.query_one("#tab-done", Static),
            "report": self.query_one("#tab-report", Static),
        }
        for key, widget in widgets.items():
            widget.set_class(key == view, "tab-active")
            widget.set_class(key != view, "tab-dim")



class PriorityTable(PagingTable):
    def on_resize(self, event: events.Resize) -> None:
        app = self.app
        if isinstance(app, LightcycleApp):
            app.refresh_priority_layout()

    def on_show(self, event: events.Show) -> None:
        app = self.app
        if isinstance(app, LightcycleApp):
            app.refresh_priority_layout()

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate) -> None:
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if old_coordinate.row != new_coordinate.row:
            self._paint_cursor_glyph(old_coordinate.row, False)
            self._paint_cursor_glyph(new_coordinate.row, True)

    def _paint_cursor_glyph(self, row_index, show) -> None:
        if row_index < 0 or row_index >= len(self.ordered_rows):
            return
        row_key = self.ordered_rows[row_index].key
        if row_key.value is None:
            return
        if getattr(self, "_stacked_mode", False):
            _repaint_stacked_cursor(self, row_key, show)
            return
        value = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if show else ""
        try:
            _update_cell_if_changed(self, row_key, "cursor", value)
        except CellDoesNotExist:
            pass




def _tui_metric_line(wall_seconds, rss_kb, now):
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    rss = str(rss_kb) if rss_kb is not None else "?"
    return "%s  %-7s  wall_ms=%d rss_kb=%s\n" % (ts, "tui", round(wall_seconds * 1000), rss)




class MainScreen(Screen, inherit_bindings=False):
    BINDINGS = [b for b in Screen.BINDINGS if b.key != "tab"]


class LightcycleApp(App):
    CSS = f"""
    Screen {{
        border: solid {COLOURS["border"]};
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
        overflow-y: hidden;
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

    PriorityTable {{
        height: 1fr;
        display: none;
    }}

    DataTable {{
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
        scrollbar-background: {COLOURS["bg"]};
        scrollbar-background-hover: {COLOURS["bg"]};
        scrollbar-background-active: {COLOURS["bg"]};
        scrollbar-color: {COLOURS["dim"]};
        scrollbar-color-hover: {COLOURS["dim"]};
        scrollbar-color-active: {COLOURS["dim"]};
        scrollbar-corner-color: {COLOURS["bg"]};
        scrollbar-gutter: stable;
        overflow-x: hidden;
    }}
    DataTable:focus {{
        background-tint: transparent;
    }}
    DataTable > .datatable--cursor {{
        background: {COLOURS["selected-bg"]};
        color: {COLOURS["text"]};
    }}
    RichLog {{
        background: {COLOURS["bg"]};
        color: {COLOURS["text"]};
        scrollbar-background: {COLOURS["bg"]};
        scrollbar-background-hover: {COLOURS["bg"]};
        scrollbar-background-active: {COLOURS["bg"]};
        scrollbar-color: {COLOURS["dim"]};
        scrollbar-color-hover: {COLOURS["dim"]};
        scrollbar-color-active: {COLOURS["dim"]};
        scrollbar-corner-color: {COLOURS["bg"]};
    }}
    RichLog:focus {{
        background-tint: transparent;
    }}

    #empty-state {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}

    #priority-list-floor {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}

    BacklogView {{
        display: none;
    }}
    #backlog-floor {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}
    .filter-row-label {{
        width: {FILTER_ROW_LABEL_WIDTH};
        color: {COLOURS["text"]};
    }}
    {SEARCH_BAR_CSS}
    FilterBlock {{
        height: auto;
        border-bottom: solid {COLOURS["border"]};
    }}
    FilterBlock .search-bar {{
        margin-bottom: 0;
    }}
    .filter-line-one {{
        width: auto;
        height: 3;
        content-align: left middle;
    }}
    FilterLineRest {{
        height: auto;
        display: none;
    }}
    BacklogTable {{
        height: 1fr;
        display: none;
    }}
    #backlog-empty-overall {{
        content-align: center top;
        height: auto;
        margin-top: 4;
        display: none;
    }}
    #backlog-empty-filtered-message {{
        content-align: center top;
        height: auto;
        margin-top: 4;
        display: none;
    }}
    #backlog-empty-filtered-hint {{
        content-align: center top;
        height: auto;
        display: none;
    }}

    DoneView {{
        display: none;
    }}
    #done-floor {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
    }}
    DoneTable {{
        height: 1fr;
        display: none;
    }}
    #done-empty-overall {{
        content-align: center top;
        height: auto;
        margin-top: 4;
        display: none;
    }}
    #done-empty-filtered-message {{
        content-align: center top;
        height: auto;
        margin-top: 4;
        display: none;
    }}
    #done-empty-filtered-hint {{
        content-align: center top;
        height: auto;
        display: none;
    }}

    ReportView {{
        display: none;
    }}
    #report-day-filter-bar {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    #report-day-filter-left {{
        width: auto;
    }}
    #report-day-filter-right {{
        width: 1fr;
        content-align: right middle;
        display: none;
    }}
    #report-summary {{
        height: auto;
        max-height: 30%;
        overflow-y: auto;
        margin: 1 0;
        display: none;
    }}
    ReportTable {{
        height: auto;
        max-height: 70%;
    }}
    #report-floor {{
        color: {COLOURS["dim"]};
        content-align: center middle;
        height: 1fr;
        display: none;
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
    StatusBar Static {{
        width: auto;
        margin-right: 2;
    }}
    StatusBar #status-version {{
        width: 1fr;
    }}
    StatusBar #status-upgrade {{
        margin-right: 0;
    }}
    #status-hold {{
        display: none;
    }}
    #status-github {{
        display: none;
    }}
    #status-doctor {{
        display: none;
    }}
    #status-config {{
        display: none;
    }}
    #status-upgrade {{
        display: none;
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

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("[", "prev_strip", "Prev tab", show=False),
        Binding("]", "next_strip", "Next tab", show=False),
        Binding("f", "open_picker", "Filter", show=False),
        Binding("d", "open_day_picker", "Day", show=False),
        Binding("/", "focus_search", "Search", show=False),
        Binding("p", "toggle_pool", "Pool", show=False),
        Binding("enter", "open_done_for_report_day", "Open", show=False),
        Binding("right", "open_done_for_report_day", "Open", show=False),
    ]

    def __init__(self, container, now=None, upgrade_check=None, doctor_check=None):
        super().__init__()
        self._container = container
        self._now = now or (lambda: datetime.datetime.now().astimezone())
        self._upgrade_check = upgrade_check or (
            lambda: upgrade(
                self._container.config.version(), check_only=True,
                fetch=self._container.upgrade.fetch_remote_version)
        )
        self._doctor_check = doctor_check or (
            lambda: self._container.doctor_for_current_thread().execute(DoctorInput())
        )
        self._doctor_areas = ()
        self._doctor_failed = False
        self._upgrade_version = None
        self._upgrade_error = None
        self._config_mtime_at_load = container.config.config_mtime()
        self._last_shape = None
        self._pool_running = False
        self._last_attention_ids = None
        self._last_priority_selection = None
        self._health_icon_use_case = HealthIconUseCase(
            container.fs, container.config, container.health_icon)
        self._selected_flat_index = 0
        self._view = "priority"
        self._priority_empty = True
        self._priority_floor = False
        self._priority_stacked = False
        self._priority_needs_rebuild = False
        self._last_priority_rows = []
        self._active_row_ids = ()
        self._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX
        self._active_glyph_timer = None
        self._pool_transition_kind = None
        self._pool_transition_expired = False
        self._pool_transition_deadline = None
        self._pool_transition_timer = None
        self._priority_layout_cache = None
        self._priority_row_budget_cache = None
        self._backlog_project_filter = None
        self._backlog_text_filter = None
        self._backlog_total = 0
        self._backlog_filtered_count = 0
        self._backlog_filter_timer = None
        self._done_project_filter = None
        self._done_category = CATEGORY_NO_AUTOMATION
        self._done_text_filter = None
        self._done_day_filter = None
        self._done_total = 0
        self._done_filtered_count = 0
        self._done_filter_timer = None
        self._upgrade_check_timer = None
        self._doctor_check_timer = None
        self._done_cost_time_cache = {}
        self._report_cache = {}
        self._report_day = None
        self._picker_open = False

    @property
    def container(self):
        return self._container

    def get_default_screen(self) -> Screen:
        return MainScreen(id="_default")

    def compose(self) -> ComposeResult:
        yield TabStrip(id="tab-strip")
        on_priority = self._view == "priority"
        showing_floor = on_priority and self._priority_floor and not self._priority_empty
        priority_table = PriorityTable(id="priority-list")
        priority_table.display = on_priority and not self._priority_empty and not showing_floor
        yield priority_table
        yield Static(EMPTY_STATE_MESSAGE, id="empty-state")
        priority_floor = Static(id="priority-list-floor")
        priority_floor.display = showing_floor
        yield priority_floor
        backlog_view = BacklogView(id="backlog-view")
        backlog_view.display = self._view == "backlog"
        yield backlog_view
        done_view = DoneView(id="done-view")
        done_view.display = self._view == "done"
        yield done_view
        report_view = ReportView(id="report-view")
        report_view.display = self._view == "report"
        yield report_view
        yield DashboardFooter(id="footer")

    def on_mount(self) -> None:
        driver = self._driver
        if driver is not None and not driver.is_headless:
            self._container.terminal_writer.bind(driver.write)
        table = self.query_one(PriorityTable)
        table.cursor_type = "row"
        table.show_header = False
        self._start_upgrade_check()
        self._start_doctor_check()
        self.screen_change_signal.subscribe(self, lambda screen: self._sync_active_glyph_animation())
        self.call_after_refresh(self._refresh)
        self.set_interval(POLL_INTERVAL_SECONDS, self._refresh)
        upgrade_check_interval = self._container.config.tui_upgrade_check_seconds()
        if upgrade_check_interval > 0:
            self._upgrade_check_timer = self.set_interval(
                upgrade_check_interval, self._start_upgrade_check)
        doctor_check_interval = self._container.config.tui_doctor_check_seconds()
        if doctor_check_interval > 0:
            self._doctor_check_timer = self.set_interval(
                doctor_check_interval, self._start_doctor_check)
        if self._container.config.tui_autostart_pool():
            self._start_pool()

    def on_unmount(self) -> None:
        self._health_icon_use_case.release()

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._on_terminal_resized)

    def _on_terminal_resized(self) -> None:
        self.refresh_priority_layout()
        self.query_one(BacklogView).refresh_column_width()
        self.query_one(DoneView).refresh_column_width()

    def _check_upgrade(self):
        response = UpgradeNoticeUseCase(
            self._container.config.version(), check=self._upgrade_check).execute()
        return response.remote, response.error

    def _start_upgrade_check(self) -> None:
        self.run_worker(
            self._check_upgrade_worker, thread=True,
            group="upgrade-check", exclusive=True, exit_on_error=False,
        )

    def _check_upgrade_worker(self) -> None:
        version, error = self._check_upgrade()
        self.call_from_thread(self._apply_upgrade_result, version, error)

    def _apply_upgrade_result(self, version, error) -> None:
        if version is not None or error is None:
            self._upgrade_version = version
            self._upgrade_error = error
        elif self._upgrade_version is None:
            self._upgrade_error = error
        self._refresh_status_bar()

    def _start_doctor_check(self) -> None:
        self.run_worker(
            self._check_doctor_worker, thread=True,
            group="doctor-check", exclusive=True, exit_on_error=False,
        )

    def _check_doctor_worker(self) -> None:
        try:
            report = self._doctor_check()
        except Exception:
            self.call_from_thread(self._apply_doctor_result, (), True)
            return
        areas = tuple(
            category for category, problems in report.problems.items()
            if problems and category != "github"
        )
        self.call_from_thread(self._apply_doctor_result, areas, False)

    def _apply_doctor_result(self, areas, failed) -> None:
        self._doctor_areas = areas
        self._doctor_failed = failed
        self._refresh_status_bar()

    def _refresh(self) -> None:
        metrics_enabled = self._container.config.tui_metrics()
        tick_start = time.perf_counter() if metrics_enabled else None

        lanes = StatusUseCase(self._container.store).execute().lanes

        self._pool_running = PoolRunningUseCase(self._container.lock).execute().running
        selection = select_priority_rows(
            self._container.store, lanes, self._container.flow_service(), self._pool_running,
        )
        shape = (
            tuple(s.owning_node.id for s in selection.attention),
            tuple(s.owning_node.id for s in selection.active),
            tuple(s.owning_node.id for s in selection.queued),
        )
        had_prior_attention = self._last_attention_ids is not None
        newly_attention = set(shape[0]) - (self._last_attention_ids or set())
        self._last_attention_ids = set(shape[0])
        if had_prior_attention and newly_attention:
            self.bell()

        self._active_row_ids = tuple(s.owning_node.id for s in selection.active)
        self._last_priority_selection = selection
        if self._view == "priority":
            self._render_priority_rows(selection, shape)
        self._last_shape = shape

        self._sync_active_glyph_animation()

        self._refresh_backlog_view()
        self._refresh_done_view()

        self._apply_view_visibility()
        self._sync_footer_shortcuts()

        self._refresh_status_bar()

        if tick_start is not None:
            wall_seconds = time.perf_counter() - tick_start
            rss_kb = self._container.machine.self_rss()
            self._container.worker_log.append_run_log(
                _tui_metric_line(wall_seconds, rss_kb, self._now().timestamp())
            )

    def _render_priority_rows(self, selection, shape=None, force_rebuild=False) -> None:
        store = self._container.store
        attention_rows, active_rows, queued_rows = build_priority_rows_from_selection(
            store, selection,
        )
        rows = assemble_rows(attention_rows, active_rows, queued_rows)
        table = self.query_one(PriorityTable)
        self._priority_empty = not rows
        layout = self._priority_layout(table, rows)
        if (
            not force_rebuild
            and shape == self._last_shape
            and not self._priority_needs_rebuild
            and layout.stacked == self._priority_stacked
        ):
            self._update_cells(table, rows)
        else:
            self._rebuild_table(table, rows)

    def _render_status_bar(self, status_bar, running, breaker, hold, drain=None, github=None,
                           tick_health=None) -> None:
        status_bar.report(
            pool_running=running,
            pool_transition_kind=self._pool_transition_kind,
            pool_transition_expired=self._pool_transition_expired,
            pool_draining_waiting=drain.waiting_text() if drain is not None and drain.draining else None,
            breaker_is_open=breaker.is_open,
            breaker_is_probing=breaker.is_probing,
            breaker_reset_at=breaker.reset_at,
            version=self._container.config.version(),
            upgrade_version=self._upgrade_version,
            upgrade_error=self._upgrade_error,
            hold=hold,
            config_changed=self._container.config.config_mtime() != self._config_mtime_at_load,
            github=github,
            doctor_areas=self._doctor_areas,
            doctor_failed=self._doctor_failed,
            pool_tick_health=tick_health,
        )

    def _refresh_status_bar(self) -> None:
        pool = PoolRunningUseCase(self._container.lock).execute()
        running = pool.running
        if self._pool_transition_kind == "start" and running:
            self._clear_pool_transition()
        elif self._pool_transition_kind == "stop" and not running:
            self._clear_pool_transition()
        drain = PoolDrainStatusUseCase(
            self._container.drain, self._container.workers, self._container.store
        ).execute(running, self._now().timestamp())
        breaker = BreakerStatusUseCase(self._container.breaker).execute(self._now().timestamp())
        hold = PoolHoldStatusUseCase(
            self._container.memory_gate_status, self._container.workers, self._container.config,
        ).execute(self._container.workers.pid_alive)
        github = GithubBudgetUseCase(
            self._container.github_budget_status, self._container.flow_service(),
            self._container.config, lambda: self._now().timestamp(),
        ).reading()
        tick_health = TickHealthUseCase(
            self._container.tick_timing_status, self._container.config,
        ).reading(running, pool.holder_pid, self._now().timestamp())
        icon = self._health_icon_use_case.reading(
            pool_state=self._health_pool_state(running, drain),
            tick_health=tick_health,
            poll_seconds=self._container.config.poll_seconds(),
            breaker_is_open=breaker.is_open,
            github=github,
            upgrade_available=self._upgrade_version is not None,
            config_changed=self._container.config.config_mtime() != self._config_mtime_at_load,
            busy=self._has_active(),
        )
        for screen in self.screen_stack:
            try:
                status_bar = screen.query_one(StatusBar)
            except NoMatches:
                continue
            self._render_status_bar(status_bar, running, breaker, hold, drain, github, tick_health)
            try:
                screen.query_one(DashboardFooter).show_health_icon(icon)
            except NoMatches:
                continue

    def _health_pool_state(self, running, drain):
        kind = self._pool_transition_kind
        if kind in ("start", "stop"):
            return kind + ("-timed-out" if self._pool_transition_expired else "ing")
        if drain is not None and drain.draining:
            return "draining"
        return "running" if running else "stopped"

    def _has_active(self):
        selection = self._last_priority_selection
        return selection is not None and bool(selection.active)

    def _begin_pool_transition(self, kind) -> None:
        self._pool_transition_kind = kind
        self._pool_transition_expired = False
        timeout = (
            POOL_START_TIMEOUT_SECONDS if kind == "start"
            else self._container.config.shutdown_grace_seconds()
        )
        self._pool_transition_deadline = self._now().timestamp() + timeout
        self._refresh_status_bar()
        self._sync_pool_transition_poll()

    def _clear_pool_transition(self) -> None:
        self._pool_transition_kind = None
        self._pool_transition_expired = False
        self._pool_transition_deadline = None
        self._sync_pool_transition_poll()

    def _sync_pool_transition_poll(self) -> None:
        should_run = self._pool_transition_kind is not None and not self._pool_transition_expired
        if should_run and self._pool_transition_timer is None:
            self._pool_transition_timer = self.set_interval(
                POOL_TRANSITION_POLL_SECONDS, self._tick_pool_transition
            )
        elif not should_run and self._pool_transition_timer is not None:
            self._pool_transition_timer.stop()
            self._pool_transition_timer = None

    def _tick_pool_transition(self) -> None:
        self._refresh_status_bar()
        if self._pool_transition_kind is None:
            return
        if self._now().timestamp() >= self._pool_transition_deadline:
            self._pool_transition_expired = True
            self._refresh_status_bar()
        self._sync_pool_transition_poll()

    def _refresh_backlog_view(self) -> None:
        if self._view != "backlog":
            return
        backlog_uc = BacklogUseCase(self._container.store, None)
        backlog_resp = backlog_uc.execute(
            BacklogInput(project=self._backlog_project_filter, text=self._backlog_text_filter)
        )
        backlog_counts = backlog_uc.counts()
        self._backlog_total = backlog_counts.total
        self._backlog_filtered_count = len(backlog_resp.rows)
        backlog_rows = build_backlog_rows(backlog_resp.rows)
        self.query_one(BacklogView).apply_rows(
            backlog_rows, self._backlog_total, self._backlog_project_filter, self._backlog_text_filter
        )

    def _refresh_done_view(self) -> None:
        if self._view != "done":
            return
        done_uc = DoneUseCase(self._container.store)
        done_resp = done_uc.execute(DoneInput(
            project=self._done_project_filter, text=self._done_text_filter, day=self._done_day_filter,
            category=self._done_category,
        ))
        done_counts = done_uc.counts(self._done_category)
        self._done_total = done_counts.total
        self._done_filtered_count = len(done_resp.rows)
        done_rows = build_done_rows(
            self._container.store, done_resp.rows, self._now(), self._done_cost_time_cache,
        )
        self.query_one(DoneView).apply_rows(
            done_rows, self._done_total, self._done_project_filter, self._done_text_filter,
            self._done_day_filter, self._done_category,
        )

    def _refresh_report_view(self) -> None:
        if self._view != "report":
            return
        day = self._report_day or self._now().date()
        cached = self._report_cache.get(day)
        if cached is None or day == self._now().date():
            cached = ReportUseCase(self._container.store).execute(ReportInput(day))
            self._report_cache[day] = cached
        self.query_one(ReportView).apply_report(cached)

    def _apply_view_visibility(self) -> None:
        on_priority = self._view == "priority"
        showing_floor = on_priority and self._priority_floor and not self._priority_empty
        self.query_one(PriorityTable).display = (
            on_priority and not self._priority_empty and not showing_floor
        )
        self.query_one("#empty-state", Static).display = on_priority and self._priority_empty
        self.query_one("#priority-list-floor", Static).display = showing_floor
        self.query_one(BacklogView).display = self._view == "backlog"
        self.query_one(DoneView).display = self._view == "done"
        self.query_one(ReportView).display = self._view == "report"
        self._sync_active_glyph_animation()

    def _desired_shortcuts(self):
        if self._view == "priority":
            return GLOBAL_SHORTCUTS
        if self._view == "done":
            if self.focused is self.query_one(DoneFilterInput):
                return DONE_SEARCH_SHORTCUTS if self._done_filtered_count > 0 else DONE_SEARCH_EMPTY_SHORTCUTS
            if self._done_total == 0:
                return DONE_EMPTY_SHORTCUTS
            if self._done_filtered_count == 0:
                return DONE_FILTERED_EMPTY_SHORTCUTS
            return DONE_SHORTCUTS
        if self._view == "report":
            return REPORT_SHORTCUTS
        if self.focused is self.query_one(BacklogFilterInput):
            return BACKLOG_SEARCH_SHORTCUTS if self._backlog_filtered_count > 0 else BACKLOG_SEARCH_EMPTY_SHORTCUTS
        if self._backlog_total == 0:
            return BACKLOG_EMPTY_SHORTCUTS
        if self._backlog_filtered_count == 0:
            return BACKLOG_FILTERED_EMPTY_SHORTCUTS
        return BACKLOG_SHORTCUTS

    def _sync_footer_shortcuts(self) -> None:
        shortcut_bar = self.screen_stack[0].query_one(ShortcutBar)
        desired = self._desired_shortcuts()
        if shortcut_bar.shortcuts != desired:
            shortcut_bar.set_shortcuts(desired)

    def action_prev_strip(self) -> None:
        if isinstance(self.screen, NodeHubScreen):
            self.screen.action_prev_tab()
            return
        self._cycle_view(-1)

    def action_next_strip(self) -> None:
        if isinstance(self.screen, NodeHubScreen):
            self.screen.action_next_tab()
            return
        self._cycle_view(1)

    def _cycle_view(self, direction: int) -> None:
        if self._backlog_filter_timer is not None:
            self._backlog_filter_timer.stop()
            self._backlog_filter_timer = None
        if self._done_filter_timer is not None:
            self._done_filter_timer.stop()
            self._done_filter_timer = None
        while len(self.screen_stack) > 1:
            self.pop_screen()
        index = _VIEW_CYCLE.index(self._view)
        self._cycle_view_to(_VIEW_CYCLE[(index + direction) % len(_VIEW_CYCLE)])

    def _cycle_view_to(self, view) -> None:
        self._view = view
        if self._view == "priority":
            if self._last_priority_selection is not None:
                self._render_priority_rows(
                    self._last_priority_selection, force_rebuild=True,
                )
        elif self._view == "backlog":
            self._refresh_backlog_view()
        elif self._view == "done":
            self._refresh_done_view()
        elif self._view == "report":
            self._refresh_report_view()
        self._apply_view_visibility()
        self.query_one(TabStrip).set_active(self._view)
        self._sync_footer_shortcuts()
        self._sync_active_glyph_animation()
        if self._view == "priority":
            self.set_focus(self.query_one(PriorityTable))
        elif self._view == "backlog":
            self.set_focus(self.query_one(BacklogTable))
        elif self._view == "report":
            self.set_focus(self.query_one(ReportView))
        else:
            self.set_focus(self.query_one(DoneTable))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        table = event.data_table
        row_id = event.row_key.value
        if row_id is None:
            return
        if table.id == "priority-list":
            event.stop()
            rows_by_id = {row.id: row for row in self._last_priority_rows}
            row = rows_by_id.get(row_id)
            if row is None:
                return
            self.push_screen(NodeHubScreen(self._container, row.step_id, self._now))
        elif table.id in ("backlog-table", "done-table"):
            event.stop()
            self.push_screen(NodeHubScreen(self._container, row_id, self._now))

    def _start_pool(self):
        return StartPoolUseCase(self._container.lock, self._container.spawner).execute()

    def _live_worker_count(self):
        return LiveWorkerCountUseCase(self._container.workers).execute()

    def action_toggle_pool(self) -> None:
        if self._pool_transition_kind is not None and not self._pool_transition_expired:
            return
        if not PoolRunningUseCase(self._container.lock).execute().running:
            self._start_pool()
            self._begin_pool_transition("start")
            return
        options = [(POOL_PROMPT_STOP, "Stop the pool")]
        if not self._container.drain.requested():
            options.append((POOL_PROMPT_DRAIN, "Drain: finish running work, then stop"))
        options.append((POOL_PROMPT_CANCELLED, "Cancel"))
        self.push_screen(
            PoolPromptScreen("Stop the pool?", pool_prompt_body(self._live_worker_count()), options),
            self._on_stop_prompt_dismiss,
        )

    def _on_stop_prompt_dismiss(self, result) -> None:
        if result == POOL_PROMPT_DRAIN:
            DrainPoolUseCase(self._container.lock, self._container.drain).execute()
            return
        if result != POOL_PROMPT_STOP:
            return
        StopPoolSignalUseCase(self._container.lock, self._container.workers).execute()
        self._begin_pool_transition("stop")

    def action_quit(self) -> None:
        if not PoolRunningUseCase(self._container.lock).execute().running:
            self.exit()
            return
        self.push_screen(
            PoolPromptScreen(
                "Quit lightcycle?",
                pool_prompt_body(self._live_worker_count()),
                [
                    (POOL_PROMPT_QUIT_LEAVE, "Quit and leave the pool running"),
                    (POOL_PROMPT_QUIT_STOP, "Quit and stop the pool"),
                    (POOL_PROMPT_CANCELLED, "Cancel"),
                ],
            ),
            self._on_quit_prompt_dismiss,
        )

    def _on_quit_prompt_dismiss(self, result) -> None:
        if result == POOL_PROMPT_CANCELLED:
            return
        if result == POOL_PROMPT_QUIT_STOP:
            StopPoolSignalUseCase(self._container.lock, self._container.workers).execute()
        self.exit()

    def action_open_picker(self) -> None:
        if self._view not in ("backlog", "done") or self._picker_open:
            return
        if self._view == "backlog":
            counts = BacklogUseCase(self._container.store, None).counts()
            options = [(None, "All", counts.total)]
        else:
            counts = DoneUseCase(self._container.store).counts()
            options = [
                (("category", CATEGORY_ALL), "All", counts.all_count),
                (("category", CATEGORY_NO_AUTOMATION), "All (no automation)", counts.no_automation_count),
                (("category", CATEGORY_AUTOMATION), "Automations", counts.automation_count),
            ]
        options += [(pc.project, pc.project, pc.count) for pc in counts.projects]
        self._picker_open = True
        self.push_screen(ProjectFilterPicker(options), self._on_picker_dismiss)

    def _on_picker_dismiss(self, result) -> None:
        self._picker_open = False
        if result is PICKER_CANCELLED:
            return
        if self._view == "backlog":
            self._backlog_project_filter = result
            self._refresh()
            self.set_focus(self.query_one(BacklogTable))
        else:
            if isinstance(result, tuple):
                self._done_project_filter = None
                self._done_category = result[1]
            else:
                self._done_project_filter = result
                self._done_category = CATEGORY_NO_AUTOMATION
            self._refresh()
            self.set_focus(self.query_one(DoneTable))

    def action_open_day_picker(self) -> None:
        if self._view not in ("done", "report") or self._picker_open:
            return
        done_uc = DoneUseCase(self._container.store)
        if self._view == "done":
            day_counts = done_uc.day_counts(self._done_project_filter, self._done_category)
            options = [(None, "All", sum(dc.count for dc in day_counts))] + [
                (dc.day, dc.day.isoformat(), dc.count) for dc in day_counts
            ]
            dismiss = self._on_done_day_picker_dismiss
        else:
            today = self._now().date()
            counts = {dc.day: dc.count for dc in done_uc.day_counts()}
            days = sorted({today} | set(counts), reverse=True)
            options = [(d, d.isoformat(), counts.get(d, 0)) for d in days]
            dismiss = self._on_report_day_picker_dismiss
        self._picker_open = True
        self.push_screen(ProjectFilterPicker(options, heading="Filter by day"), dismiss)

    def _on_done_day_picker_dismiss(self, result) -> None:
        self._picker_open = False
        if result is PICKER_CANCELLED:
            return
        self._done_day_filter = result
        self._refresh()
        self.set_focus(self.query_one(DoneTable))

    def _on_report_day_picker_dismiss(self, result) -> None:
        self._picker_open = False
        if result is PICKER_CANCELLED:
            return
        self._report_day = result
        self._refresh_report_view()
        self.set_focus(self.query_one(ReportView))

    def action_open_done_for_report_day(self) -> None:
        if self._view != "report":
            return
        self._done_day_filter = self._report_day or self._now().date()
        self._cycle_view_to("done")

    def action_focus_search(self) -> None:
        if self._view == "backlog":
            self.set_focus(self.query_one(BacklogFilterInput))
        elif self._view == "done":
            self.set_focus(self.query_one(DoneFilterInput))
        else:
            return
        self.stylesheet.update(self.screen, animate=False)
        self._sync_footer_shortcuts()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "backlog-filter-text":
            self._backlog_text_filter = event.value or None
            if self._backlog_filter_timer is not None:
                self._backlog_filter_timer.stop()
            self._backlog_filter_timer = self.set_timer(FILTER_DEBOUNCE_SECONDS, self._on_backlog_filter_settled)
        elif event.input.id == "done-filter-text":
            self._done_text_filter = event.value or None
            if self._done_filter_timer is not None:
                self._done_filter_timer.stop()
            self._done_filter_timer = self.set_timer(FILTER_DEBOUNCE_SECONDS, self._on_done_filter_settled)

    def _on_backlog_filter_settled(self) -> None:
        self._backlog_filter_timer = None
        self._refresh_backlog_view()
        self._sync_footer_shortcuts()

    def _on_done_filter_settled(self) -> None:
        self._done_filter_timer = None
        self._refresh_done_view()
        self._sync_footer_shortcuts()

    def _priority_layout(self, table, rows):
        atomic_values = {
            "id": [row.id for row in rows],
            "project": [row.project for row in rows],
            "step": [row.step for row in rows],
            "cost": [row.cost for row in rows],
            "time": [row.time for row in rows],
        }
        row_budget = screen_row_budget_for(table, len(DATA_COLUMNS))
        return compute_layout(row_budget, ["cursor", "icon"], atomic_values, PRIORITY_CONTINUATION_INDENT)

    def _add_columns(self, table, layout, row_budget) -> None:
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
            return
        widths = {
            "cursor": GLYPH_WIDTHS["cursor"],
            "icon": GLYPH_WIDTHS["icon"],
            "id": layout.atomic_widths["id"],
            "project": layout.atomic_widths["project"],
            "step": layout.atomic_widths["step"],
            "cost": layout.atomic_widths["cost"],
            "time": layout.atomic_widths["time"],
            "title": layout.flexible_width,
        }
        for key in DATA_COLUMNS:
            table.add_column(key, width=widths[key], key=key)

    def _stacked_first_line(self, row, cursor, layout, row_budget, icon_override=None):
        cursor_field = pad_field(
            Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else Text(""),
            GLYPH_WIDTHS["cursor"],
        )
        icon_cell = Text(icon_override if icon_override is not None else row.icon, style=COLOURS[row.icon_colour])
        if row.dependency_icon:
            icon_cell = icon_cell + Text(
                row.dependency_icon, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
            )
        icon_field = pad_field(icon_cell, GLYPH_WIDTHS["icon"])
        id_field = pad_atomic_field(row.id, layout.atomic_widths["id"])
        project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else Text("")
        project_field = pad_atomic_field(project_cell, layout.atomic_widths["project"])
        step_field = pad_atomic_field(
            Text(row.step, style=COLOURS[row.step_colour]), layout.atomic_widths["step"]
        )
        cost_field = pad_atomic_field(
            Text(row.cost, style=COLOURS["dim"]) if row.cost else Text(""), layout.atomic_widths["cost"]
        )
        content_so_far = cursor_field + icon_field + id_field + project_field + step_field + cost_field
        time_cell = Text(row.time, style=COLOURS["dim"]) if row.time else Text("")
        time_area = max(0, row_budget - len(content_so_far.plain))
        return content_so_far + pad_field_right(time_cell, time_area)

    def _row_cells(self, row, layout, row_budget, cursor=False, icon_override=None):
        if layout.stacked:
            first_line = self._stacked_first_line(row, cursor, layout, row_budget, icon_override)
            cell = stacked_cell(first_line, PRIORITY_CONTINUATION_INDENT, row.title, row_budget)
            return (cell + Text(ROW_SPACER),)
        cursor_cell = Text(CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]) if cursor else ""
        icon_cell = Text(icon_override if icon_override is not None else row.icon, style=COLOURS[row.icon_colour])
        if row.dependency_icon:
            icon_cell = icon_cell + Text(
                row.dependency_icon, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
            )
        step_cell = Text(row.step, style=COLOURS[row.step_colour])
        project_cell = Text(row.project, style=COLOURS["cyan"]) if row.project else ""
        cost_cell = Text(row.cost, style=COLOURS["dim"]) if row.cost else ""
        time_cell = Text(row.time, style=COLOURS["dim"]) if row.time else ""
        return (
            cursor_cell, icon_cell, row.id, project_cell, row.title + ROW_SPACER, step_cell, cost_cell, time_cell,
        )

    def _stacked_row_cell_builder(self, row, layout, row_budget, cursor, icon_override):
        return self._row_cells(row, layout, row_budget, cursor=cursor, icon_override=icon_override)

    def _update_cells(self, table, rows) -> None:
        self._last_priority_rows = rows
        layout = self._priority_layout(table, rows)
        row_budget = render_screen_row_budget(table, layout, len(DATA_COLUMNS))
        if not layout.stacked:
            apply_widths(
                table,
                {
                    "id": layout.atomic_widths["id"],
                    "project": layout.atomic_widths["project"],
                    "step": layout.atomic_widths["step"],
                    "cost": layout.atomic_widths["cost"],
                    "time": layout.atomic_widths["time"],
                    "title": layout.flexible_width,
                },
            )
        self._priority_layout_cache = layout
        self._priority_row_budget_cache = row_budget
        active_glyph = self._active_glyph_char()
        selected_id = self._selected_row_id(table)
        for row in rows:
            icon_override = active_glyph if row.group == "active" else None
            cells = self._row_cells(
                row, layout, row_budget, cursor=(row.id == selected_id), icon_override=icon_override
            )
            if layout.stacked:
                _update_cell_if_changed(table, row.id, STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(DATA_COLUMNS, cells):
                if key == "cursor":
                    continue
                _update_cell_if_changed(table, row.id, key, value)

    def _active_glyph_char(self) -> str:
        return ACTIVE_GLYPH_FRAMES[self._active_glyph_frame]

    def _priority_view_visible(self) -> bool:
        return self._view == "priority" and self.screen is self.screen_stack[0]

    def _sync_active_glyph_animation(self) -> None:
        should_run = (
            self._priority_view_visible()
            and bool(self._active_row_ids)
            and not self._priority_floor
            and not self._priority_needs_rebuild
        )
        if should_run and self._active_glyph_timer is None:
            self._active_glyph_timer = self.set_interval(
                1 / ACTIVE_GLYPH_TICKS_PER_SECOND, self._tick_active_glyph
            )
        elif not should_run and self._active_glyph_timer is not None:
            self._active_glyph_timer.stop()
            self._active_glyph_timer = None
            self._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX

    def _tick_active_glyph(self) -> None:
        self._active_glyph_frame = next_active_glyph_frame(self._active_glyph_frame)
        if not self._active_row_ids or self._priority_layout_cache is None:
            return
        try:
            table = self.query_one(PriorityTable)
        except NoMatches:
            return
        glyph = self._active_glyph_char()
        layout = self._priority_layout_cache
        row_budget = self._priority_row_budget_cache
        rows_by_id = {row.id: row for row in self._last_priority_rows}
        selected_id = self._selected_row_id(table)
        for row_id in self._active_row_ids:
            row = rows_by_id.get(row_id)
            if row is None:
                continue
            cells = self._row_cells(
                row, layout, row_budget, cursor=(row_id == selected_id), icon_override=glyph
            )
            try:
                if layout.stacked:
                    _update_cell_if_changed(table, row_id, STACKED_COLUMN_KEY, cells[0])
                else:
                    _update_cell_if_changed(table, row_id, "icon", cells[1])
            except CellDoesNotExist:
                pass

    def _selected_row_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        row_id = cell_key.row_key.value
        if row_id is None:
            return None
        return row_id

    def _rebuild_table(self, table, rows) -> None:
        self._last_priority_rows = rows
        layout = self._priority_layout(table, rows)
        self._priority_floor = bool(rows) and layout.floor
        self._priority_stacked = layout.stacked
        if self._priority_floor:
            self._priority_needs_rebuild = True
            self.query_one("#priority-list-floor", Static).update(
                Text(floor_message(layout, table, len(DATA_COLUMNS)), style=COLOURS["dim"])
            )
            return
        self._priority_needs_rebuild = False

        has_prior = self._last_shape is not None
        selected_id = self._selected_row_id(table) if has_prior else None

        table.clear(columns=True)
        row_budget = render_screen_row_budget(table, layout, len(DATA_COLUMNS))
        self._add_columns(table, layout, row_budget)
        self._priority_layout_cache = layout
        self._priority_row_budget_cache = row_budget

        new_index = 0
        if has_prior and rows:
            ids = [row.id for row in rows]
            if selected_id is not None and selected_id in ids:
                new_index = ids.index(selected_id)
            else:
                new_index = min(max(self._selected_flat_index, 0), len(rows) - 1)

        table._stacked_mode = layout.stacked
        table._stacked_layout = layout
        table._stacked_row_budget = row_budget
        table._stacked_cell_builder = self._stacked_row_cell_builder
        active_glyph = self._active_glyph_char()
        stacked_rows = {}
        for index, row in enumerate(rows):
            is_cursor = index == new_index
            icon_override = active_glyph if row.group == "active" else None
            cells = self._row_cells(row, layout, row_budget, cursor=is_cursor, icon_override=icon_override)
            if layout.stacked:
                stacked_rows[row.id] = (row, icon_override)
            table.add_row(*cells, height=None, key=row.id)
        table._stacked_rows = stacked_rows

        self._selected_flat_index = new_index
        if rows:
            table.move_cursor(row=new_index)

    def refresh_priority_layout(self) -> None:
        table = self.query_one(PriorityTable)
        if self._priority_empty or not self._last_priority_rows:
            return
        if self._priority_needs_rebuild:
            self._rebuild_table(table, self._last_priority_rows)
            self._apply_view_visibility()
            return
        layout = self._priority_layout(table, self._last_priority_rows)
        if bool(self._last_priority_rows) and layout.floor != self._priority_floor:
            self._rebuild_table(table, self._last_priority_rows)
            self._apply_view_visibility()
            return
        if layout.floor:
            self.query_one("#priority-list-floor", Static).update(
                Text(floor_message(layout, table, len(DATA_COLUMNS)), style=COLOURS["dim"])
            )
            return
        if layout.stacked or layout.stacked != self._priority_stacked:
            self._rebuild_table(table, self._last_priority_rows)
            return
        widths = {
            "id": layout.atomic_widths["id"],
            "project": layout.atomic_widths["project"],
            "step": layout.atomic_widths["step"],
            "cost": layout.atomic_widths["cost"],
            "time": layout.atomic_widths["time"],
            "title": layout.flexible_width,
        }
        apply_widths(table, widths)


def run(container):
    LightcycleApp(container).run()

