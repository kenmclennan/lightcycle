from dataclasses import dataclass
from typing import Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, RichLog, Static
from textual.widgets.data_table import CellDoesNotExist

from lightcycle import __version__
from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
    CONTENT_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    DONE_GLYPH,
    HUB_SHORTCUTS,
    STATE_GLYPHS,
)
from lightcycle.adapters.tui.footer import DashboardFooter, StatusBar
from lightcycle.application.pool import (
    BreakerStatusUseCase,
    PoolRunningUseCase,
    TailLogInput,
    TailLogUseCase,
)
from lightcycle.application.work import HierarchyInput, HierarchyUseCase
from lightcycle.application.work.project_of import project_of, short_project_label
from lightcycle.domain.feedback import Duration, format_elapsed
from lightcycle.domain.work import Item, State, display_role, has_content, landing_tab, row_bucket

POLL_INTERVAL_SECONDS = 10
LOG_TAIL_INTERVAL_SECONDS = 1
LOG_NO_STREAM_MESSAGE = "Nothing live to stream."
LOG_FINISHED_MESSAGE = "✓ step finished"

_TAB_ORDER = ("hierarchy", "log", "artifacts")
_TAB_LABELS = {"hierarchy": "Hierarchy", "log": "Log", "artifacts": "Artifacts"}


def _owning_id(node):
    return node.parent if node.type == "step" else node.id


def project_label(store, node):
    return short_project_label(project_of(store, Item(_owning_id(node))))


def current_step(store, item_id):
    for child in store.children(item_id):
        if child.state != State.DONE:
            return child
    return None


def landing_node(store, node):
    if node.type != "item" or node.state in (State.DONE, State.IN_PROGRESS) or node.blocked_by:
        return node
    cur = current_step(store, node.id)
    return cur if cur is not None else node


def log_target_node(store, node):
    if node.type == "step":
        return node
    if node.type == "item":
        return current_step(store, node.id)
    return None


def log_tab_mode(node):
    if node is None or node.role == "human":
        return "no-log"
    if node.state == State.IN_PROGRESS:
        return "live"
    if node.state == State.DONE:
        return "historical"
    return "no-log"


def _elapsed(store, node, now):
    delta = Duration(store.history(node.id)).elapsed_since_claim(now)
    return format_elapsed(delta.total_seconds()) if delta is not None else None


@dataclass(frozen=True)
class HeaderData:
    id: str
    title: str
    project: Optional[str]
    theme_line: Optional[str]
    workflow_line: Optional[str]
    description: Optional[str]
    step_field: Optional[str]
    role_field: Optional[str]
    elapsed_field: Optional[str]
    state_field: Optional[str]
    escalation_text: Optional[str]
    escalation_target: Optional[str]


def build_header(store, node, now):
    project = project_label(store, node) or None
    if node.type == "theme":
        return HeaderData(
            id=node.id, title=node.title, project=project,
            theme_line=None, workflow_line=None, description=None,
            step_field=None, role_field=None, elapsed_field=None, state_field=None,
            escalation_text=None, escalation_target=None,
        )
    if node.type == "item":
        return _item_header(store, node, now, project)
    return _step_header(store, node, now, project)


def _item_header(store, node, now, project):
    theme_line = None
    if node.parent:
        theme = store.get_node(node.parent)
        theme_line = "%s · %s" % (theme.id, theme.title)
    workflow_line = node.workflow or None
    description = node.description or None
    step_field = role_field = elapsed_field = None
    escalation_text = escalation_target = None

    if node.blocked_by:
        escalation_target = sorted(node.blocked_by)[0]
        escalation_text = "Blocked · depends on %s" % escalation_target
    elif node.state == State.DONE:
        step_field = "done"
    else:
        cur = current_step(store, node.id)
        if cur is not None:
            if cur.blocked_by:
                escalation_target = sorted(cur.blocked_by)[0]
                escalation_text = "Blocked · depends on %s" % escalation_target
            else:
                step_field = cur.step
                if cur.role == "human":
                    if cur.needs:
                        escalation_text = cur.needs
                else:
                    role_field = cur.role
                    if cur.state == State.IN_PROGRESS:
                        elapsed_field = _elapsed(store, cur, now)

    return HeaderData(
        id=node.id, title=node.title, project=project,
        theme_line=theme_line, workflow_line=workflow_line, description=description,
        step_field=step_field, role_field=role_field, elapsed_field=elapsed_field,
        state_field=None, escalation_text=escalation_text, escalation_target=escalation_target,
    )


def _step_header(store, node, now, project):
    escalation_text = escalation_target = None
    if node.blocked_by:
        escalation_target = sorted(node.blocked_by)[0]
        escalation_text = "Blocked · depends on %s" % escalation_target
    elif node.role == "human" and node.needs:
        escalation_text = node.needs

    elapsed_field = _elapsed(store, node, now) if node.state == State.IN_PROGRESS else None
    return HeaderData(
        id=node.id, title=node.title, project=project,
        theme_line=None, workflow_line=None, description=None,
        step_field=None, role_field=display_role(node.role), elapsed_field=elapsed_field,
        state_field=row_bucket(node), escalation_text=escalation_text,
        escalation_target=escalation_target,
    )


def _state_glyph(node):
    bucket = row_bucket(node)
    if bucket == "needs-attention":
        return STATE_GLYPHS["needs-attention"]
    if bucket == "active":
        return STATE_GLYPHS["active"]
    if bucket == "done":
        return DONE_GLYPH
    return STATE_GLYPHS["queued"]


def hierarchy_row_cells(row):
    node = row.node
    glyph = _state_glyph(node)
    icon_cell = Text(glyph.glyph, style=COLOURS[glyph.colour])
    if node.blocked_by:
        icon_cell = icon_cell + Text(
            DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
        )
    content_cell = (
        Text(CONTENT_GLYPH.glyph, style=COLOURS[CONTENT_GLYPH.colour]) if has_content(node) else ""
    )
    title_cell = ("  " * row.depth) + node.title
    role_cell = Text(display_role(node.role), style=COLOURS["dim"]) if node.type == "step" else ""
    return (icon_cell, content_cell, node.id, title_cell, role_cell)


class EscalationPanel(Static):
    can_focus = True

    BINDINGS = [
        Binding("enter", "open", "Open", show=False),
        Binding("right", "open", "Open", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_id = None

    def action_open(self) -> None:
        if self.target_id and isinstance(self.screen, NodeHubScreen):
            self.screen.open_at(self.target_id)


class HubHeader(Vertical):
    def compose(self) -> ComposeResult:
        yield Static(id="hub-id")
        yield Static(id="hub-title")
        yield Static(id="hub-project")
        yield Static(id="hub-theme")
        yield Static(id="hub-workflow")
        yield Static(id="hub-description")
        yield Static(id="hub-step")
        yield Static(id="hub-role")
        yield Static(id="hub-elapsed")
        yield Static(id="hub-state")
        yield EscalationPanel(id="hub-escalation")

    def update(self, header) -> None:
        self.query_one("#hub-id", Static).update(Text(header.id, style=COLOURS["cyan"]))
        self.query_one("#hub-title", Static).update(header.title or "")
        self._line("#hub-project", "project: %s" % header.project if header.project else None)
        self._line("#hub-theme", "theme: %s" % header.theme_line if header.theme_line else None)
        self._line(
            "#hub-workflow", "workflow: %s" % header.workflow_line if header.workflow_line else None
        )
        self._line("#hub-description", header.description)
        self._line("#hub-step", "STEP: %s" % header.step_field if header.step_field else None)
        self._line("#hub-role", "ROLE: %s" % header.role_field if header.role_field else None)
        self._line(
            "#hub-elapsed", "ELAPSED: %s" % header.elapsed_field if header.elapsed_field else None
        )
        self._line("#hub-state", "STATE: %s" % header.state_field if header.state_field else None)

        panel = self.query_one(EscalationPanel)
        if header.escalation_text:
            panel.update(Text(header.escalation_text, style=COLOURS["amber"]))
            panel.target_id = header.escalation_target
            panel.display = True
        else:
            panel.update("")
            panel.target_id = None
            panel.display = False

    def _line(self, selector, text) -> None:
        widget = self.query_one(selector, Static)
        if text:
            widget.update(Text(text, style=COLOURS["dim"]))
            widget.display = True
        else:
            widget.update("")
            widget.display = False


class HubTabStrip(Horizontal):
    def compose(self) -> ComposeResult:
        for tab in _TAB_ORDER:
            yield Static(_TAB_LABELS[tab], id="hub-tab-%s" % tab, classes="tab-dim")

    def set_active(self, active) -> None:
        for tab in _TAB_ORDER:
            widget = self.query_one("#hub-tab-%s" % tab, Static)
            widget.set_class(tab == active, "tab-active")
            widget.set_class(tab != active, "tab-dim")


class LogPane(RichLog):
    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.live = False

    def watch_scroll_y(self, old, new) -> None:
        super().watch_scroll_y(old, new)
        self.auto_scroll = self.is_vertical_scroll_end


class HierarchyPagingTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("right", "select_cursor", "Open", show=False),
        Binding("a", "jump_artifacts", "Artifacts", show=False),
        Binding("l", "jump_log", "Log", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def watch_scroll_y(self, old, new) -> None:
        super().watch_scroll_y(old, new)
        if isinstance(self.screen, NodeHubScreen):
            self.screen.update_pinned_ancestor()

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate) -> None:
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if isinstance(self.screen, NodeHubScreen):
            self.screen.update_pinned_ancestor()

    def _highlighted_id(self):
        if self.row_count == 0:
            return None
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def action_jump_artifacts(self) -> None:
        row_id = self._highlighted_id()
        if row_id is not None and isinstance(self.screen, NodeHubScreen):
            self.screen.open_at(row_id, initial_tab="artifacts")

    def action_jump_log(self) -> None:
        row_id = self._highlighted_id()
        if row_id is None or not isinstance(self.screen, NodeHubScreen):
            return
        screen = self.screen
        node = screen.container.store.get_node(row_id)
        if node.type != "step" or log_tab_mode(node) == "no-log":
            return
        screen.open_at(row_id, initial_tab="log")

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, NodeHubScreen):
            screen.refresh_hierarchy_width()


class NodeHubScreen(Screen):
    BINDINGS = [
        Binding("escape", "close_hub", "Back", show=False),
        Binding("left", "close_hub", "Back", show=False),
        Binding("[", "prev_tab", "Prev tab", show=False),
        Binding("]", "next_tab", "Next tab", show=False),
    ]

    CSS = f"""
    HubHeader {{
        height: auto;
    }}
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
    #hub-escalation {{
        height: 1;
        display: none;
    }}
    #hub-log-empty, #hub-artifacts-empty {{
        content-align: center middle;
        height: 1fr;
        color: {COLOURS["dim"]};
    }}
    LogPane {{
        height: 1fr;
    }}
    #pinned-ancestor {{
        height: 1;
        background: {COLOURS["border"]};
        display: none;
    }}
    """

    def __init__(self, container, node_id, now, initial_tab=None):
        super().__init__()
        self._container = container
        self._node_id = node_id
        self._now = now
        self._forced_initial_tab = initial_tab
        self._active_tab = None
        self._last_hierarchy_shape = None
        self._last_rows = []
        self._log_mode = None
        self._log_target = None
        self._log_offset = 0
        self._log_finished = False
        self._log_timer = None

    @property
    def container(self):
        return self._container

    def compose(self) -> ComposeResult:
        yield HubHeader(id="hub-header")
        yield HubTabStrip(id="hub-tabs")
        yield Static(id="pinned-ancestor")
        yield HierarchyPagingTable(id="hierarchy-table")
        yield LogPane(id="hub-log-view", highlight=False, markup=False)
        yield Static(LOG_NO_STREAM_MESSAGE, id="hub-log-empty")
        yield Static("Nothing to show yet.", id="hub-artifacts-empty")
        yield DashboardFooter(id="hub-footer", shortcuts=HUB_SHORTCUTS)

    def on_mount(self) -> None:
        table = self.query_one(HierarchyPagingTable)
        table.cursor_type = "row"
        table.show_header = False
        store = self._container.store
        node = store.get_node(self._node_id)
        self._active_tab = self._forced_initial_tab or landing_tab(landing_node(store, node))
        self._setup_log_tab()
        self.call_after_refresh(self._initial_refresh)
        self.set_interval(POLL_INTERVAL_SECONDS, self.poll_refresh)

    def _setup_log_tab(self) -> None:
        store = self._container.store
        node = store.get_node(self._node_id)
        log_node = log_target_node(store, node)
        mode = log_tab_mode(log_node)
        self._log_mode = mode
        empty = self.query_one("#hub-log-empty", Static)
        if mode == "no-log":
            empty.update(LOG_NO_STREAM_MESSAGE)
            return
        self._log_target = log_node.id
        log_pane = self.query_one(LogPane)
        log_pane.live = mode == "live"
        log_pane.auto_scroll = mode == "live"
        result = self._run_tail(0)
        if result.path is None:
            self._log_mode = "no-log"
            empty.update(LOG_NO_STREAM_MESSAGE)
            return
        self._apply_tail_result(result)
        if self._log_mode == "live" and not self._log_finished:
            self._log_timer = self.set_interval(LOG_TAIL_INTERVAL_SECONDS, self._tail_tick)

    def _run_tail(self, offset):
        use_case = TailLogUseCase(
            self._container.store, self._container.workers, self._container.fs, self._container.config
        )
        return use_case.execute(TailLogInput(target=self._log_target, offset=offset))

    def _tail_tick(self) -> None:
        self._apply_tail_result(self._run_tail(self._log_offset))

    def _apply_tail_result(self, result) -> None:
        self._log_offset = result.offset
        log_pane = self.query_one(LogPane)
        if result.data:
            log_pane.write(Text(result.data.decode("utf-8", errors="replace"), style=COLOURS["dim"]))
        if self._log_mode == "live" and not result.live and not self._log_finished:
            self._log_finished = True
            log_pane.live = False
            log_pane.write(Text(LOG_FINISHED_MESSAGE, style=COLOURS["cyan"]))
            if self._log_timer is not None:
                self._log_timer.stop()

    def _initial_refresh(self) -> None:
        self._refresh(initial=True)
        self._apply_tab_visibility()
        self._focus_active_tab()

    def poll_refresh(self) -> None:
        self._refresh(initial=False)

    def _refresh(self, initial) -> None:
        store = self._container.store
        node = store.get_node(self._node_id)
        header = build_header(store, node, self._now().isoformat())
        self.query_one(HubHeader).update(header)
        rows = HierarchyUseCase(store).execute(HierarchyInput(node=self._node_id)).rows
        self._render_hierarchy(rows, initial)
        self.query_one(HubTabStrip).set_active(self._active_tab)
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        running = PoolRunningUseCase(self._container.lock).execute().running
        breaker = BreakerStatusUseCase(self._container.breaker).execute()
        self.query_one(StatusBar).report(
            pool_running=running,
            breaker_is_open=breaker.is_open,
            breaker_reset_at=breaker.reset_at,
            version=__version__,
            upgrade_version=self.app.upgrade_version,
        )

    def _title_width(self, table):
        grid = dict(COLUMN_GRIDS["hierarchy"])
        columns = [key for key, _ in COLUMN_GRIDS["hierarchy"]]
        padding = 2 * table.cell_padding * len(columns)
        fixed = sum(int(grid[key][:-2]) for key in columns if key != "title") + padding
        width = table.size.width - fixed
        return width if width > 0 else None

    def refresh_hierarchy_width(self) -> None:
        table = self.query_one(HierarchyPagingTable)
        if table.row_count:
            self._render_hierarchy(self._last_rows or [], initial=False, force=True)

    def _selected_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def _render_hierarchy(self, rows, initial, force=False) -> None:
        self._last_rows = rows
        table = self.query_one(HierarchyPagingTable)
        shape = tuple(r.node.id for r in rows)
        if shape == self._last_hierarchy_shape and not initial and not force:
            self._update_hierarchy_cells(table, rows)
            return

        title_width = self._title_width(table)
        if title_width is None:
            return

        selected_id = self._node_id if initial else self._selected_id(table)
        table.clear(columns=True)
        grid = dict(COLUMN_GRIDS["hierarchy"])
        for key, _ in COLUMN_GRIDS["hierarchy"]:
            width = title_width if key == "title" else int(grid[key][:-2])
            table.add_column(key, width=width, key=key)

        ids = [r.node.id for r in rows]
        index = ids.index(selected_id) if selected_id in ids else 0
        for row in rows:
            table.add_row(*hierarchy_row_cells(row), height=1, key=row.node.id)

        self._last_hierarchy_shape = shape
        if rows:
            table.move_cursor(row=index)
        self.update_pinned_ancestor()

    def _update_hierarchy_cells(self, table, rows) -> None:
        columns = [key for key, _ in COLUMN_GRIDS["hierarchy"]]
        for row in rows:
            cells = hierarchy_row_cells(row)
            for key, value in zip(columns, cells):
                table.update_cell(row.node.id, key, value)

    def update_pinned_ancestor(self) -> None:
        banner = self.query_one("#pinned-ancestor", Static)
        if self._active_tab != "hierarchy" or not self._last_rows:
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
        banner.update(Text("%s  %s" % (ancestor.node.id, ancestor.node.title), style=COLOURS["dim"]))
        banner.display = True

    def _apply_tab_visibility(self) -> None:
        self.query_one(HierarchyPagingTable).display = self._active_tab == "hierarchy"
        log_active = self._active_tab == "log"
        self.query_one(LogPane).display = log_active and self._log_mode != "no-log"
        self.query_one("#hub-log-empty", Static).display = log_active and self._log_mode == "no-log"
        self.query_one("#hub-artifacts-empty", Static).display = self._active_tab == "artifacts"
        self.update_pinned_ancestor()

    def _focus_active_tab(self) -> None:
        panel = self.query_one(EscalationPanel)
        if self._active_tab == "hierarchy" and panel.display:
            self.set_focus(panel)
        elif self._active_tab == "hierarchy":
            self.set_focus(self.query_one(HierarchyPagingTable))
        elif self._active_tab == "log" and self._log_mode != "no-log":
            self.set_focus(self.query_one(LogPane))
        else:
            self.set_focus(None)

    def action_next_tab(self) -> None:
        index = _TAB_ORDER.index(self._active_tab)
        self._active_tab = _TAB_ORDER[(index + 1) % len(_TAB_ORDER)]
        self.query_one(HubTabStrip).set_active(self._active_tab)
        self._apply_tab_visibility()
        self._focus_active_tab()

    def action_prev_tab(self) -> None:
        index = _TAB_ORDER.index(self._active_tab)
        self._active_tab = _TAB_ORDER[(index - 1) % len(_TAB_ORDER)]
        self.query_one(HubTabStrip).set_active(self._active_tab)
        self._apply_tab_visibility()
        self._focus_active_tab()

    def action_close_hub(self) -> None:
        self.close_hub()

    def close_hub(self) -> None:
        self.app.pop_screen()

    def open_at(self, node_id, initial_tab=None) -> None:
        self.app.push_screen(NodeHubScreen(self._container, node_id, self._now, initial_tab=initial_tab))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        row_id = event.row_key.value
        if row_id is None:
            return
        self.open_at(row_id)
