from lightcycle.adapters.log_parser import LogLineParser
from lightcycle.adapters.tui.design_system import (
    ACTIVE_GLYPH_REST_INDEX,
    COLOURS,
    HUB_SHORTCUTS,
)
from lightcycle.adapters.tui.footer import DashboardFooter
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import UnblockInput
from lightcycle.application.pool import (
    BreakerStatusUseCase,
    PoolRunningUseCase,
)
from lightcycle.application.work import (
    HierarchyInput,
    HierarchyUseCase,
    OpenArtifactInput,
    OpenArtifactUseCase,
)
from lightcycle.application.work.step_context import (
    SECTION_INPUTS,
    SECTION_OUTPUTS,
)
from lightcycle.application.work.step_focus import (
    ResolveStepFocusInput,
    ResolveStepFocusUseCase,
)
from lightcycle.domain.work.detail import detail_value_is_url
from lightcycle.domain.work.step_focus import (
    FOCUS_CONTEXT,
    FOCUS_DETAIL,
    FOCUS_REASON,
)
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Static,
)
from lightcycle.adapters.tui.hub_render import (
    CONTEXT_CONTINUATION_INDENT,
    CONTEXT_EMPTY_MESSAGE,
    CONTEXT_INPUTS_LIVE_TITLE,
    CONTEXT_NONE_TEXT,
    CONTEXT_RECONSTRUCTED_NOTE,
    CONTEXT_SECTIONS,
    CONTEXT_WORKFLOW_GAP,
    COST_CACHE_HIT_RATE_DEFINITION,
    COST_COLUMN_GAP,
    COST_CONTINUATION_INDENT,
    COST_EMPTY_MESSAGE,
    COST_FIELD_LABELS,
    COST_NOT_RECORDED,
    COST_NOT_RUN_MESSAGE,
    COST_NO_TOOLS_MESSAGE,
    DESCRIPTION_EMPTY_MESSAGE,
    DETAIL_BLOCK_THRESHOLD,
    DETAIL_BODY_SUFFIX,
    DETAIL_CONTINUATION_INDENT,
    DETAIL_EMPTY_MESSAGE,
    DETAIL_FIELD_LABELS,
    ESCALATION_REASON_LINE_CAP,
    ESCALATION_TAG,
    HIERARCHY_CONTINUATION_BASE_INDENT,
    HeaderData,
    ITEM_COST_EMPTY_MESSAGE,
    LOG_CURSOR_GLYPH,
    LOG_FINISHED_MESSAGE,
    LOG_INITIAL_TAIL_BYTES,
    LOG_LINES_MAX_RETAINED,
    LOG_NO_STREAM_MESSAGE,
    LOG_PANE_MAX_LINES,
    LOG_TAIL_INTERVAL_SECONDS,
    OUTPUTS_CONTINUATION_INDENT,
    OUTPUTS_EMPTY_MESSAGE,
    POLL_INTERVAL_SECONDS,
    STACKED_COLUMN_KEY,
    TOAST_DURATION_SECONDS,
    TOAST_EDITOR_DESTINATION,
    TOAST_FAILURE_PREFIX,
    TOAST_FILEPATH_DESTINATION,
    TOAST_SUB_CAPTION_BY_TAB,
    TOAST_SUCCESS_PREFIX,
    TOAST_URL_SUB_SUFFIX,
    WORKFLOW_UNRESOLVED,
    _ITEM_TAB_ORDER,
    _STEP_TAB_ORDER,
    _TAB_BY_FOCUS,
    _TAB_LABELS,
    _capped_reason_lines,
    _context_text,
    _cost_breakdown_value,
    _cost_field_label,
    _cost_hit_rate_field,
    _cost_pane_screen_row_budget,
    _cost_row_text,
    _cost_rows_for_item,
    _cost_rows_for_step,
    _cost_stage_atomic_text,
    _cost_tool_atomic_text,
    _dependency_escalation,
    _detail_field_label,
    _display_glyph,
    _engine_wait_seconds,
    _flow_for_bucket,
    _format_item_cost,
    _gate_wait_seconds,
    _hierarchy_default_row_id,
    _hierarchy_label,
    _hierarchy_stacked_first_line,
    _identity_text,
    _item_cost_text,
    _item_header,
    _item_wall_active,
    _output_name_text,
    _output_value_style,
    _owning_id,
    _park_escalation_text,
    _rates_used_text,
    _reason_lines_text,
    _row_node,
    _stacked_block_cell,
    _stacked_prose_cell,
    _stage_cost_text,
    _stat_line_item,
    _stat_line_step,
    _state_glyph,
    _step_count_text,
    _step_header,
    _step_wall_active,
    _tab_order,
    _unpriced_suffix,
    _workflow_selector_pin,
    _workflow_text,
    build_header,
    context_row_cells,
    context_row_key,
    context_section_rows,
    context_section_title,
    detail_fields,
    detail_row_cells,
    detail_value_is_block,
    display_role,
    escalation_panel_text,
    escalation_reason_text,
    hierarchy_row_cells,
    hierarchy_time_text,
    hierarchy_usage_text,
    item_cost_fields,
    landing_tab,
    log_tab_mode,
    output_row_cells,
    project_label,
    resume_toast_text,
    step_cost_fields,
    toast_text,
)
from lightcycle.adapters.tui.hub_widgets import (
    HubScreenMarker,
    ContextList,
    ContextTable,
    CostPane,
    DescriptionPane,
    DetailTable,
    EscalationPanel,
    HierarchyPagingTable,
    HubHeader,
    HubTabStrip,
    LogPane,
    OutputsTable,
    pane_text_width,
)
from lightcycle.adapters.tui.artifact_viewer import (
    ArtifactListTable,
    ArtifactTextBody,
    ArtifactViewerHeader,
    ArtifactViewerScreen,
    ListArtifactViewerScreen,
    TextArtifactViewerScreen,
)
from lightcycle.adapters.tui.hub_tabs.log import LogTabMixin
from lightcycle.adapters.tui.hub_tabs.hierarchy import HierarchyTabMixin
from lightcycle.adapters.tui.hub_tabs.outputs import OutputsTabMixin
from lightcycle.adapters.tui.hub_tabs.detail import DetailTabMixin
from lightcycle.adapters.tui.hub_tabs.context import ContextTabMixin
from lightcycle.adapters.tui.hub_tabs.cost import CostTabMixin
from lightcycle.adapters.tui.hub_tabs.description import DescriptionTabMixin

__all__ = [
    "HubScreenMarker",
    "ArtifactListTable",
    "ArtifactTextBody",
    "ArtifactViewerHeader",
    "ArtifactViewerScreen",
    "CONTEXT_CONTINUATION_INDENT",
    "CONTEXT_EMPTY_MESSAGE",
    "CONTEXT_INPUTS_LIVE_TITLE",
    "CONTEXT_NONE_TEXT",
    "CONTEXT_RECONSTRUCTED_NOTE",
    "CONTEXT_SECTIONS",
    "CONTEXT_WORKFLOW_GAP",
    "COST_CACHE_HIT_RATE_DEFINITION",
    "COST_COLUMN_GAP",
    "COST_CONTINUATION_INDENT",
    "COST_EMPTY_MESSAGE",
    "COST_FIELD_LABELS",
    "COST_NOT_RECORDED",
    "COST_NOT_RUN_MESSAGE",
    "COST_NO_TOOLS_MESSAGE",
    "ContextList",
    "ContextTable",
    "CostPane",
    "DESCRIPTION_EMPTY_MESSAGE",
    "DETAIL_BLOCK_THRESHOLD",
    "DETAIL_BODY_SUFFIX",
    "DETAIL_CONTINUATION_INDENT",
    "DETAIL_EMPTY_MESSAGE",
    "DETAIL_FIELD_LABELS",
    "DescriptionPane",
    "DetailTable",
    "ESCALATION_REASON_LINE_CAP",
    "ESCALATION_TAG",
    "EscalationPanel",
    "HIERARCHY_CONTINUATION_BASE_INDENT",
    "HeaderData",
    "HierarchyPagingTable",
    "HubHeader",
    "HubTabStrip",
    "ITEM_COST_EMPTY_MESSAGE",
    "LOG_CURSOR_GLYPH",
    "LOG_FINISHED_MESSAGE",
    "LOG_INITIAL_TAIL_BYTES",
    "LOG_LINES_MAX_RETAINED",
    "LOG_NO_STREAM_MESSAGE",
    "LOG_PANE_MAX_LINES",
    "LOG_TAIL_INTERVAL_SECONDS",
    "ListArtifactViewerScreen",
    "LogPane",
    "OUTPUTS_CONTINUATION_INDENT",
    "OUTPUTS_EMPTY_MESSAGE",
    "OutputsTable",
    "POLL_INTERVAL_SECONDS",
    "STACKED_COLUMN_KEY",
    "TOAST_DURATION_SECONDS",
    "TOAST_EDITOR_DESTINATION",
    "TOAST_FAILURE_PREFIX",
    "TOAST_FILEPATH_DESTINATION",
    "TOAST_SUB_CAPTION_BY_TAB",
    "TOAST_SUCCESS_PREFIX",
    "TOAST_URL_SUB_SUFFIX",
    "TextArtifactViewerScreen",
    "WORKFLOW_UNRESOLVED",
    "_ITEM_TAB_ORDER",
    "_STEP_TAB_ORDER",
    "_TAB_BY_FOCUS",
    "_TAB_LABELS",
    "_capped_reason_lines",
    "_context_text",
    "_cost_breakdown_value",
    "_cost_field_label",
    "_cost_hit_rate_field",
    "_cost_pane_screen_row_budget",
    "_cost_row_text",
    "_cost_rows_for_item",
    "_cost_rows_for_step",
    "_cost_stage_atomic_text",
    "_cost_tool_atomic_text",
    "_dependency_escalation",
    "_detail_field_label",
    "_display_glyph",
    "_engine_wait_seconds",
    "_flow_for_bucket",
    "_format_item_cost",
    "_gate_wait_seconds",
    "_hierarchy_default_row_id",
    "_hierarchy_label",
    "_hierarchy_stacked_first_line",
    "_identity_text",
    "_item_cost_text",
    "_item_header",
    "_item_wall_active",
    "_output_name_text",
    "_output_value_style",
    "_owning_id",
    "_park_escalation_text",
    "_rates_used_text",
    "_reason_lines_text",
    "_row_node",
    "_stacked_block_cell",
    "_stacked_prose_cell",
    "_stage_cost_text",
    "_stat_line_item",
    "_stat_line_step",
    "_state_glyph",
    "_step_count_text",
    "_step_header",
    "_step_wall_active",
    "_tab_order",
    "_unpriced_suffix",
    "_workflow_selector_pin",
    "_workflow_text",
    "build_header",
    "context_row_cells",
    "context_row_key",
    "context_section_rows",
    "context_section_title",
    "detail_fields",
    "detail_row_cells",
    "detail_value_is_block",
    "display_role",
    "escalation_panel_text",
    "escalation_reason_text",
    "hierarchy_row_cells",
    "hierarchy_time_text",
    "hierarchy_usage_text",
    "item_cost_fields",
    "landing_tab",
    "log_tab_mode",
    "output_row_cells",
    "pane_text_width",
    "project_label",
    "resume_toast_text",
    "step_cost_fields",
    "toast_text",
]


HUB_TAB_STRIP_CSS = f"""
    HubTabStrip {{
        height: 3;
        border-top: solid {COLOURS["border"]};
        border-bottom: solid {COLOURS["border"]};
    }}
    HubTabStrip Static {{
        width: auto;
        height: 1;
        margin-right: 3;
    }}
"""


class NodeHubScreen(HubScreenMarker, LogTabMixin, HierarchyTabMixin, OutputsTabMixin, DetailTabMixin, ContextTabMixin, CostTabMixin, DescriptionTabMixin, Screen, inherit_bindings=False):
    BINDINGS = [b for b in Screen.BINDINGS if b.key != "tab"] + [
        Binding("escape", "close_hub", "Back", show=False),
        Binding("tab", "close_hub", "Back", show=False),
        Binding("left", "close_hub", "Back", show=False),
        Binding("t", "toggle_thinking", "Thinking", show=False),
        Binding("r", "resume", "Resume", show=False),
    ]

    CSS = f"""
    HubHeader {{
        height: auto;
    }}
    HierarchyPagingTable {{
        height: 1fr;
    }}
    OutputsTable {{
        height: 1fr;
    }}
    DetailTable {{
        height: 1fr;
    }}
    ContextList {{
        height: 1fr;
        scrollbar-background: {COLOURS["bg"]};
        scrollbar-background-hover: {COLOURS["bg"]};
        scrollbar-background-active: {COLOURS["bg"]};
        scrollbar-color: {COLOURS["dim"]};
        scrollbar-color-hover: {COLOURS["dim"]};
        scrollbar-color-active: {COLOURS["dim"]};
        scrollbar-corner-color: {COLOURS["bg"]};
        scrollbar-gutter: stable;
        display: none;
    }}
    ContextTable {{
        height: auto;
        max-height: 1000;
        width: 100%;
        overflow: hidden hidden;
    }}
    .context-header {{
        height: auto;
        padding: 1 0 1 1;
    }}
    .context-header.first-visible {{
        padding: 0 0 1 1;
    }}
    .context-none {{
        height: auto;
        padding: 0 0 0 1;
        color: {COLOURS["dim"]};
    }}
    .context-none.hidden, ContextTable.hidden {{
        display: none;
    }}
    CostPane {{
        height: 1fr;
    }}
    {HUB_TAB_STRIP_CSS}
    #hub-context {{
        display: none;
    }}
    #hub-context-note {{
        height: auto;
        display: none;
        color: {COLOURS["dim"]};
    }}
    #hub-escalation {{
        height: auto;
        display: none;
    }}
    #hub-detail-park {{
        height: auto;
        display: none;
        border: solid {COLOURS["red"]};
        border-title-color: {COLOURS["red"]};
        padding: 0 1;
    }}
    #hub-log-empty, #hub-outputs-empty, #hub-description-empty, #hub-cost-empty,
    #hub-detail-empty, #hub-context-empty {{
        content-align: center middle;
        height: 1fr;
        display: none;
        color: {COLOURS["dim"]};
    }}
    #hierarchy-floor, #outputs-floor, #detail-floor, #context-floor, #cost-floor {{
        content-align: center middle;
        height: 1fr;
        color: {COLOURS["dim"]};
        display: none;
    }}
    #hub-outputs-toast, #hub-detail-toast, #hub-context-toast {{
        content-align: center middle;
        height: 1fr;
        display: none;
    }}
    LogPane {{
        height: 1fr;
    }}
    DescriptionPane {{
        height: 1fr;
    }}
    #pinned-ancestor {{
        height: 1;
        background: {COLOURS["panel"]};
        display: none;
    }}
    """

    def __init__(self, container, node_id, now, initial_tab=None):
        super().__init__()
        self._container = container
        self._node_id = node_id
        self._now = now
        self._forced_initial_tab = initial_tab
        node = container.store.get_node(node_id)
        self._node_type = node.type
        self._focus = ResolveStepFocusUseCase(
            container.store, container.flow_service()
        ).execute(ResolveStepFocusInput(step=node_id)).focus
        self._tab_order = _tab_order(node)
        self._active_tab = self._forced_initial_tab or landing_tab(self._focus)
        self._last_hierarchy_shape = None
        self._pool_running = False
        self._last_rows = []
        self._last_multi_pass = False
        self._hierarchy_floor = False
        self._hierarchy_stacked = False
        self._hierarchy_needs_rebuild = False
        self._hierarchy_layout_cache = None
        self._hierarchy_row_budget_cache = None
        self._hierarchy_target_id = None
        self._flow_service = None
        self._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX
        self._active_glyph_timer = None
        self._poll_timer = None
        self._log_mode = None
        self._log_target = None
        self._log_offset = 0
        self._log_finished = False
        self._log_timer = None
        self._log_parser = LogLineParser()
        self._log_lines = []
        self._show_thinking = True
        self._log_cursor_active = False
        self._log_cursor_text = None
        self._log_cursor_row_count = 0
        self._last_outputs_shape = None
        self._output_rows = []
        self._expanded_outputs = set()
        self._last_outputs = []
        self._has_outputs = False
        self._outputs_floor = False
        self._outputs_stacked = False
        self._outputs_needs_rebuild = False
        self._last_detail_shape = None
        self._last_detail_fields = []
        self._detail_floor = False
        self._detail_stacked = False
        self._detail_needs_rebuild = False
        self._detail_empty = False
        self._detail_park = None
        self._last_context_shape = None
        self._last_context_rows = []
        self._context_floor = False
        self._context_stacked = False
        self._context_needs_rebuild = False
        self._has_context = False
        self._context_inputs_live = False
        self._context_reconstructed = False
        self._context_active = SECTION_INPUTS
        self._context_width = None
        self._landed = False
        self._cost_whole_empty_message = None
        self._last_cost_shape = None
        self._last_cost_rows = []
        self._cost_floor = False
        self._cost_stacked = False
        self._toast_active = False
        self._toast_tab = None
        self._toast_timer = None
        self._has_description = False
        self._last_description = None
        self._description_item = None

    @property
    def container(self):
        return self._container

    def compose(self) -> ComposeResult:
        yield HubHeader(id="hub-header")
        yield HubTabStrip(self._tab_order, self._active_tab, id="hub-tabs")
        yield Static(id="pinned-ancestor")
        hierarchy_table = HierarchyPagingTable(id="hierarchy-table")
        hierarchy_table.display = self._active_tab == "workflow"
        yield hierarchy_table
        yield Static(id="hierarchy-floor")
        log_pane = LogPane(id="hub-log-view", highlight=False, markup=False)
        log_pane.display = self._active_tab == "log"
        yield log_pane
        yield Static(LOG_NO_STREAM_MESSAGE, id="hub-log-empty")
        outputs_table = OutputsTable(id="hub-outputs-table")
        outputs_table.display = self._active_tab == "outputs"
        yield outputs_table
        yield Static(id="outputs-floor")
        yield Static(OUTPUTS_EMPTY_MESSAGE, id="hub-outputs-empty")
        yield Static(id="hub-outputs-toast")
        yield Static(id="hub-detail-park")
        detail_table = DetailTable(id="hub-detail-table")
        detail_table.display = self._active_tab == "detail"
        yield detail_table
        yield Static(id="detail-floor")
        yield Static(DETAIL_EMPTY_MESSAGE, id="hub-detail-empty")
        yield Static(id="hub-detail-toast")
        yield Static(CONTEXT_RECONSTRUCTED_NOTE, id="hub-context-note")
        context_list = ContextList(id="hub-context-list")
        context_list.display = self._active_tab == "context"
        with context_list:
            for section in CONTEXT_SECTIONS:
                yield from self._compose_context_section(section)
        yield Static(id="context-floor")
        yield Static(CONTEXT_EMPTY_MESSAGE, id="hub-context-empty")
        yield Static(id="hub-context-toast")
        description_pane = DescriptionPane(
            id="hub-description-view", highlight=False, markup=False, wrap=True, auto_scroll=False
        )
        description_pane.display = self._active_tab == "description"
        yield description_pane
        yield Static(DESCRIPTION_EMPTY_MESSAGE, id="hub-description-empty")
        cost_pane = CostPane(
            id="hub-cost-view", highlight=False, markup=False, wrap=False, auto_scroll=False, min_width=0
        )
        cost_pane.display = self._active_tab == "cost"
        yield cost_pane
        yield Static(id="cost-floor")
        yield Static(id="hub-cost-empty")
        yield DashboardFooter(id="hub-footer", shortcuts=HUB_SHORTCUTS)

    def _compose_context_section(self, section) -> ComposeResult:
        yield Static("", id="hub-context-header-%s" % section, classes="context-header")
        yield ContextTable(id="hub-context-table-%s" % section, name=section)
        yield Static(CONTEXT_NONE_TEXT, id="hub-context-none-%s" % section, classes="context-none")

    def on_mount(self) -> None:
        table = self.query_one(HierarchyPagingTable)
        table.cursor_type = "row"
        table.show_header = False
        outputs_table = self.query_one(OutputsTable)
        outputs_table.cursor_type = "row"
        outputs_table.show_header = False
        detail_table = self.query_one(DetailTable)
        detail_table.cursor_type = "row"
        detail_table.show_header = False
        for context_table in self._context_tables():
            context_table.cursor_type = "row"
            context_table.show_header = False
        store = self._container.store
        node = store.get_node(self._node_id)
        self._hierarchy_target_id = _hierarchy_default_row_id(store, node)
        self._setup_log_tab()
        self.app.screen_change_signal.subscribe(self, lambda screen: self._sync_active_glyph_animation())
        self.call_after_refresh(self._initial_refresh)
        self._poll_timer = self.set_interval(POLL_INTERVAL_SECONDS, self.poll_refresh)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._on_terminal_resized)

    def _on_terminal_resized(self) -> None:
        self.refresh_hierarchy_width()
        self.refresh_outputs_width()
        self.refresh_detail_width()
        self.refresh_context_width()
        self.refresh_cost_width()
        self._last_description = None
        self._render_description(self._description_item)

    def on_screen_suspend(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.pause()
        if self._log_timer is not None:
            self._log_timer.pause()

    def on_screen_resume(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.resume()
        if self._log_timer is not None:
            self._log_timer.resume()

    def _initial_refresh(self) -> None:
        self._refresh(initial=True)
        self._focus_active_tab()

    def poll_refresh(self) -> None:
        self._refresh(initial=False)

    def _refresh(self, initial) -> None:
        store = self._container.store
        node = store.get_node(self._node_id)
        self._flow_service = self._container.flow_service()
        breaker = BreakerStatusUseCase(self._container.breaker, self._container.spin).execute(
            self._now().timestamp()
        )
        pool_halted = breaker.is_open or breaker.pool_spin_open
        self._pool_running = PoolRunningUseCase(self._container.lock).execute().running
        header = build_header(
            store, node, self._now().isoformat(), self._flow_service, pool_halted,
            self._pool_running,
        )
        self.query_one(HubHeader).update(header)
        hierarchy = HierarchyUseCase(store).execute(HierarchyInput(node=self._node_id))
        self._render_hierarchy(hierarchy.rows, hierarchy.multi_pass, initial)
        if node.type == "item":
            self._render_outputs(self._item_output_rows(store, node), initial)
            self._render_description(node)
        else:
            self._render_detail(store, node, initial)
            self._render_context(store, node, initial)
            self._land_cursor()
        self._render_cost(store, node, initial)
        self.query_one(HubTabStrip).set_active(self._active_tab)
        self._apply_tab_visibility()
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        self.app._refresh_status_bar()

    def _land_cursor(self) -> None:
        if self._landed:
            return
        self._landed = True
        name = self._focus.name
        if not name:
            return
        if self._focus.kind in (FOCUS_DETAIL, FOCUS_REASON):
            table = self.query_one(DetailTable)
            for index, row_key in enumerate(table.rows):
                if row_key.value == name:
                    table.move_cursor(row=index)
                    return
        elif self._focus.kind == FOCUS_CONTEXT:
            table = self.query_one("#hub-context-table-%s" % SECTION_OUTPUTS, ContextTable)
            for index, row in enumerate(self._last_context_rows):
                if row.section == SECTION_OUTPUTS and row.key == name:
                    for position, row_key in enumerate(table.rows):
                        if row_key.value == str(index):
                            self._activate_context_table(table)
                            table.move_cursor(row=position)
                            return

    def update_pinned_ancestor(self) -> None:
        banner = self.query_one("#pinned-ancestor", Static)
        if self._active_tab != "workflow" or not self._last_rows or self._hierarchy_floor:
            banner.display = False
            return
        table = self.query_one(HierarchyPagingTable)
        top_index = int(table.scroll_y)
        if top_index <= 0 or top_index >= len(self._last_rows):
            banner.display = False
            return
        top_row = self._last_rows[top_index]
        if top_row.depth == 0:
            banner.display = False
            return
        ancestor = None
        for row in reversed(self._last_rows[:top_index]):
            if row.depth < top_row.depth:
                ancestor = row
                break
        if ancestor is None:
            banner.display = False
            return
        glyph = _display_glyph(
            ancestor.node, self._active_glyph_char(), _flow_for_bucket(ancestor.node, self._flow_service),
            self._pool_running,
        )
        text = Text(glyph.glyph + "  ", style=COLOURS[glyph.colour])
        label = _hierarchy_label(ancestor.node, self._flow_service, self._last_multi_pass)
        text.append("%s  %s" % (ancestor.node.id, label), style=COLOURS["dim"])
        banner.update(text)
        banner.display = True

    def _apply_tab_visibility(self) -> None:
        hierarchy_active = self._active_tab == "workflow"
        showing_hierarchy_floor = hierarchy_active and self._hierarchy_floor
        self.query_one(HierarchyPagingTable).display = hierarchy_active and not showing_hierarchy_floor
        self.query_one("#hierarchy-floor", Static).display = showing_hierarchy_floor
        log_active = self._active_tab == "log"
        self.query_one(LogPane).display = log_active and self._log_mode != "no-log"
        self.query_one("#hub-log-empty", Static).display = log_active and self._log_mode == "no-log"
        outputs_active = self._active_tab == "outputs"
        showing_outputs_toast = outputs_active and self._toast_active and self._toast_tab == "outputs"
        showing_outputs_floor = (
            outputs_active and self._outputs_floor and not showing_outputs_toast
        )
        self.query_one(OutputsTable).display = (
            outputs_active and self._has_outputs
            and not showing_outputs_toast and not showing_outputs_floor
        )
        self.query_one("#outputs-floor", Static).display = showing_outputs_floor
        self.query_one("#hub-outputs-empty", Static).display = (
            outputs_active and not self._has_outputs and not showing_outputs_toast
        )
        self.query_one("#hub-outputs-toast", Static).display = showing_outputs_toast
        detail_active = self._active_tab == "detail"
        showing_detail_toast = detail_active and self._toast_active and self._toast_tab == "detail"
        showing_detail_floor = detail_active and self._detail_floor and not showing_detail_toast
        showing_detail_empty = detail_active and self._detail_empty and not showing_detail_toast
        self.query_one(DetailTable).display = (
            detail_active and not showing_detail_toast and not showing_detail_floor
            and not showing_detail_empty
        )
        self.query_one("#hub-detail-park", Static).display = (
            detail_active and self._detail_park is not None and not showing_detail_toast
            and not showing_detail_floor
        )
        self.query_one("#detail-floor", Static).display = showing_detail_floor
        self.query_one("#hub-detail-empty", Static).display = (
            showing_detail_empty and self._detail_park is None
        )
        self.query_one("#hub-detail-toast", Static).display = showing_detail_toast
        context_active = self._active_tab == "context"
        showing_context_toast = context_active and self._toast_active and self._toast_tab == "context"
        showing_context_floor = context_active and self._context_floor and not showing_context_toast
        showing_context_empty = (
            context_active and not self._has_context and not showing_context_toast
        )
        self.query_one(ContextList).display = (
            context_active and not showing_context_toast and not showing_context_floor
            and not showing_context_empty
        )
        self.query_one("#hub-context-note", Static).display = (
            context_active and self._context_reconstructed and not showing_context_toast
            and not showing_context_floor and not showing_context_empty
        )
        self.query_one("#context-floor", Static).display = showing_context_floor
        self.query_one("#hub-context-empty", Static).display = showing_context_empty
        self.query_one("#hub-context-toast", Static).display = showing_context_toast
        description_active = self._active_tab == "description"
        self.query_one(DescriptionPane).display = description_active and self._has_description
        self.query_one("#hub-description-empty", Static).display = (
            description_active and not self._has_description
        )
        cost_active = self._active_tab == "cost"
        cost_whole_empty = cost_active and self._cost_whole_empty_message is not None
        showing_cost_floor = cost_active and not cost_whole_empty and self._cost_floor
        self.query_one(CostPane).display = cost_active and not cost_whole_empty and not showing_cost_floor
        self.query_one("#cost-floor", Static).display = showing_cost_floor
        self.query_one("#hub-cost-empty", Static).display = cost_whole_empty
        self.update_pinned_ancestor()
        self._sync_active_glyph_animation()

    def _focus_active_tab(self) -> None:
        if self._active_tab == "workflow" and not self._hierarchy_floor:
            self.set_focus(self.query_one(HierarchyPagingTable))
        elif self._active_tab == "log" and self._log_mode != "no-log":
            self.set_focus(self.query_one(LogPane))
        elif (
            self._active_tab == "outputs"
            and self._has_outputs
            and not (self._toast_active and self._toast_tab == "outputs")
            and not self._outputs_floor
        ):
            self.set_focus(self.query_one(OutputsTable))
        elif (
            self._active_tab == "detail"
            and not self._detail_empty
            and not (self._toast_active and self._toast_tab == "detail")
            and not self._detail_floor
        ):
            self.set_focus(self.query_one(DetailTable))
        elif (
            self._active_tab == "context"
            and self._has_context
            and not (self._toast_active and self._toast_tab == "context")
            and not self._context_floor
        ):
            self.set_focus(self._context_focus_target())
        elif self._active_tab == "description" and self._has_description:
            self.set_focus(self.query_one(DescriptionPane))
        elif self._active_tab == "cost" and self._cost_whole_empty_message is None and not self._cost_floor:
            self.set_focus(self.query_one(CostPane))
        else:
            self.set_focus(None)

    def action_next_tab(self) -> None:
        index = self._tab_order.index(self._active_tab)
        self._active_tab = self._tab_order[(index + 1) % len(self._tab_order)]
        self.query_one(HubTabStrip).set_active(self._active_tab)
        self._apply_tab_visibility()
        self._focus_active_tab()
        self._sync_active_glyph_animation()

    def action_prev_tab(self) -> None:
        index = self._tab_order.index(self._active_tab)
        self._active_tab = self._tab_order[(index - 1) % len(self._tab_order)]
        self.query_one(HubTabStrip).set_active(self._active_tab)
        self._apply_tab_visibility()
        self._focus_active_tab()
        self._sync_active_glyph_animation()

    def action_close_hub(self) -> None:
        if self._toast_active:
            return
        self.close_hub()

    def close_hub(self) -> None:
        self.app.pop_screen()

    def action_resume(self) -> None:
        store = self._container.store
        node = store.get_node(self._node_id)
        if node.type != "step" or not node.park:
            return
        try:
            response = self._container.unblock_step_use_case().execute(
                UnblockInput(step=self._node_id)
            )
        except UseCaseError as e:
            self._show_resume_toast(False, str(e))
            return
        self._show_resume_toast(True, "Resumed - reassigned to %s" % response.role)
        self._refresh(initial=False)

    def switch_at(self, node_id, initial_tab=None) -> None:
        self.app.switch_screen(NodeHubScreen(self._container, node_id, self._now, initial_tab=initial_tab))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if event.data_table.id == "hub-outputs-table":
            self._open_selected_output(event.row_key.value)
            return
        if event.data_table.id == "hub-detail-table":
            self._open_selected_detail_field(event.row_key.value)
            return
        if isinstance(event.data_table, ContextTable):
            self._open_selected_context_row(event.row_key.value)
            return
        row_id = event.row_key.value
        if row_id is None or row_id == self._node_id:
            return
        self.switch_at(row_id)

    def _open_selected_output(self, key_value) -> None:
        if key_value is None:
            return
        index = int(key_value)
        if index >= len(self._last_outputs):
            return
        artifact = self._last_outputs[index].as_artifact()
        kind = artifact.kind or "text"
        if kind in ("url", "filepath"):
            self._open_external_output(kind, artifact.value)
        elif kind == "list":
            self.app.push_screen(ListArtifactViewerScreen(artifact, self._node_id))
        else:
            self.app.push_screen(
                TextArtifactViewerScreen(
                    artifact, self._node_id, index + 1, len(self._last_outputs)
                )
            )

    def _open_selected_context_row(self, key_value) -> None:
        if key_value is None:
            return
        rows = self._last_context_rows
        row = rows[int(key_value)]
        if not row.value:
            return
        if row.kind == "url":
            self._open_external_output("url", row.value, tab="context")
            return
        if row.kind == "filepath":
            self._open_worktree(row.value, tab="context")
            return

    def _open_selected_detail_field(self, key_value) -> None:
        if key_value.endswith(DETAIL_BODY_SUFFIX):
            key_value = key_value[: -len(DETAIL_BODY_SUFFIX)]
        value = next(
            (v for k, v in self._last_detail_fields if k == key_value), None
        )
        if not value:
            return
        if key_value == "worktree":
            self._open_worktree(value)
            return
        if key_value == "spec":
            self._open_worktree(value)
            return
        if key_value in ("pr", "spec-pr", "ci-checks") or detail_value_is_url(value):
            url = value.strip()
            use_case = OpenArtifactUseCase(self._container.fs, self._container.launcher)
            result = use_case.execute(OpenArtifactInput(kind="url", value=url))
            self._show_toast(result.success, result.message, "url", url, tab="detail")

    def _open_worktree(self, path, tab="detail") -> None:
        use_case = OpenArtifactUseCase(self._container.fs, self._container.launcher)
        editor_input = OpenArtifactInput(kind="editor", value=path, editor=self._container.config.editor())
        result = use_case.execute(editor_input)
        self._show_toast(result.success, result.message, "editor", path, tab=tab)

    def _open_external_output(self, kind, value, tab="outputs") -> None:
        use_case = OpenArtifactUseCase(self._container.fs, self._container.launcher)
        result = use_case.execute(OpenArtifactInput(kind=kind, value=value))
        self._show_toast(result.success, result.message, kind, value, tab=tab)

    def _toast_widget(self):
        return self.query_one("#hub-%s-toast" % self._toast_tab, Static)

    def _show_toast(self, success, message, kind, value, tab="outputs") -> None:
        self._toast_tab = tab
        self._toast_widget().update(toast_text(success, message, kind, value, tab=tab))
        self._toast_active = True
        self._apply_tab_visibility()
        if self._toast_timer is not None:
            self._toast_timer.stop()
        self._toast_timer = self.set_timer(TOAST_DURATION_SECONDS, self._dismiss_toast)

    def _show_resume_toast(self, success, message) -> None:
        self._toast_tab = "detail"
        self.query_one("#hub-detail-toast", Static).update(resume_toast_text(success, message))
        self._toast_active = True
        self._apply_tab_visibility()
        if self._toast_timer is not None:
            self._toast_timer.stop()
        self._toast_timer = self.set_timer(TOAST_DURATION_SECONDS, self._dismiss_toast)

    def _dismiss_toast(self) -> None:
        self._toast_active = False
        self._toast_tab = None
        self._toast_timer = None
        self._apply_tab_visibility()
        if self._active_tab in ("outputs", "detail", "context"):
            self._focus_active_tab()
