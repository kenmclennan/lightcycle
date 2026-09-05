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
from lightcycle.adapters.log_parser import LogLineParser
from lightcycle.adapters.tui.design_system import (
    ACTIVE_GLYPH_FRAMES,
    ACTIVE_GLYPH_REST_INDEX,
    ACTIVE_GLYPH_TICKS_PER_SECOND,
    COLOURS,
    COLUMN_GRIDS,
    CONTENT_GLYPH,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    DONE_GLYPH,
    HUB_SHORTCUTS,
    LIST_ARTIFACT_SHORTCUTS,
    STATE_GLYPHS,
    TEXT_ARTIFACT_SHORTCUTS,
    next_active_glyph_frame,
)
from lightcycle.adapters.tui.footer import DashboardFooter, StatusBar
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    apply_widths,
    compute_layout,
    floor_message,
    pad_field,
    pad_field_right,
    render_row_budget,
    row_budget_for,
    stacked_cell,
    truncate_field,
    wrap_continuation,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import UnblockInput, UnblockStepUseCase
from lightcycle.application.pool import (
    BreakerStatusUseCase,
    PoolRunningUseCase,
    TailLogInput,
    TailLogUseCase,
)
from lightcycle.application.work import (
    HierarchyInput,
    HierarchyUseCase,
    OpenArtifactInput,
    OpenArtifactUseCase,
    StepRunInput,
    StepRunUseCase,
)
from lightcycle.application.work.project_of import project_of, short_project_label
from lightcycle.domain.feedback import Duration, format_elapsed
from lightcycle.domain.runs import pass_number
from lightcycle.domain.work import (
    LogKind, State, display_role, display_stage, has_content, landing_tab,
    row_bucket, type_label, viewable_artifacts,
)

POLL_INTERVAL_SECONDS = 10
LOG_TAIL_INTERVAL_SECONDS = 1
LOG_INITIAL_TAIL_BYTES = 256 * 1024
LOG_LINES_MAX_RETAINED = 4000
LOG_PANE_MAX_LINES = 20000
LOG_NO_STREAM_MESSAGE = "Nothing live to stream."
LOG_FINISHED_MESSAGE = "✓ step finished"
LOG_CURSOR_GLYPH = "▌"
ARTIFACTS_EMPTY_MESSAGE = "This node has no artifacts to view yet."
DESCRIPTION_EMPTY_MESSAGE = "This node has no description to show."
TOAST_DURATION_SECONDS = 2.0
TOAST_SUCCESS_PREFIX = "↗ "
TOAST_FAILURE_PREFIX = "⚠ "
TOAST_SUB_CAPTION_BY_TAB = {
    "artifacts": "back to the artifact list automatically",
    "detail": "back to the step's detail automatically",
}
TOAST_URL_SUB_SUFFIX = "nothing more to show here"
TOAST_FILEPATH_DESTINATION = "in its default application"

_ITEM_TAB_ORDER = ("description", "hierarchy", "artifacts")
_STEP_TAB_ORDER = ("detail", "log")
_TAB_LABELS = {
    "description": "Description", "hierarchy": "Hierarchy", "artifacts": "Artifacts",
    "detail": "Detail", "log": "Log",
}


def _tab_order(node):
    return _ITEM_TAB_ORDER if node.type == "item" else _STEP_TAB_ORDER


STACKED_COLUMN_KEY = "row"
HIERARCHY_CONTINUATION_BASE_INDENT = GLYPH_WIDTHS["icon"] + GLYPH_WIDTHS["content"]
ARTIFACTS_CONTINUATION_INDENT = 2
DETAIL_CONTINUATION_INDENT = 2
DETAIL_FIELD_LABELS = {
    "pr": "PR", "branch": "BRANCH", "stage": "STAGE", "state": "STATE", "role": "ROLE",
    "model": "MODEL", "claimed_by": "CLAIMED_BY", "outcome": "OUTCOME", "notes": "NOTES",
    "needs": "NEEDS", "reason": "REASON", "tried": "TRIED", "reflection": "REFLECTION",
    "watched_step": "WATCHED_STEP",
}


def _owning_id(node):
    return node.parent if node.type == "step" else node.id


def project_label(store, node):
    return short_project_label(project_of(store, _owning_id(node)))


def current_step(store, item_id):
    for child in store.children(item_id):
        if child.state != State.DONE:
            return child
    return None


def _hierarchy_default_row_id(store, node):
    if node.type != "item" or node.blocked_by or node.state == State.DONE:
        return node.id
    cur = current_step(store, node.id)
    return cur.id if cur is not None else node.id


def detail_fields(step, run):
    fields = []
    if run.pr:
        fields.append(("pr", run.pr))
    if run.branch:
        fields.append(("branch", run.branch))
    fields.append(("stage", step.stage))
    fields.append(("state", str(step.state)))
    fields.append(("role", display_role(step.role)))
    if step.model:
        fields.append(("model", step.model))
    if step.claimed_by:
        fields.append(("claimed_by", step.claimed_by))
    if step.outcome:
        fields.append(("outcome", step.outcome))
    if step.notes:
        fields.append(("notes", step.notes))
    if step.park.needs:
        fields.append(("needs", step.park.needs))
    if step.park.reason:
        fields.append(("reason", step.park.reason))
    if step.park.tried:
        fields.append(("tried", step.park.tried))
    if step.reflection:
        fields.append(("reflection", step.reflection))
    if step.watched_step:
        fields.append(("watched_step", step.watched_step))
    return fields


def log_tab_mode(node):
    if node is None or getattr(node, "role", None) == "human":
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
    workflow_line: Optional[str]
    step_field: Optional[str]
    role_field: Optional[str]
    elapsed_field: Optional[str]
    state_field: Optional[str]
    escalation_text: Optional[str]
    escalation_target: Optional[str]


def build_header(store, node, now, flow_service):
    project = project_label(store, node) or None
    if node.type == "item":
        return _item_header(store, node, now, project, flow_service)
    return _step_header(store, node, now, project)


def _park_escalation_text(node):
    if node.park.reason:
        return "%s\n%s" % (node.park.needs, node.park.reason)
    return node.park.needs


def _item_header(store, node, now, project, flow_service):
    workflow_line = node.workflow or None
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
                step_field = display_stage(flow_service.display_for(cur), cur.step)
                if getattr(cur, "role", None) == "human":
                    if cur.needs:
                        escalation_text = _park_escalation_text(cur)
                else:
                    role_field = getattr(cur, "role", None)
                    if cur.state == State.IN_PROGRESS:
                        elapsed_field = _elapsed(store, cur, now)

    return HeaderData(
        id=node.id, title=node.title, project=project,
        workflow_line=workflow_line,
        step_field=step_field, role_field=role_field, elapsed_field=elapsed_field,
        state_field=None, escalation_text=escalation_text, escalation_target=escalation_target,
    )


def _step_header(store, node, now, project):
    escalation_text = escalation_target = None
    if node.blocked_by:
        escalation_target = sorted(node.blocked_by)[0]
        escalation_text = "Blocked · depends on %s" % escalation_target
    elif getattr(node, "role", None) == "human" and getattr(node, "needs", None):
        escalation_text = _park_escalation_text(node)

    elapsed_field = _elapsed(store, node, now) if node.state == State.IN_PROGRESS else None
    return HeaderData(
        id=node.id, title=node.title, project=project,
        workflow_line=None,
        step_field=None, role_field=display_role(getattr(node, "role", None)), elapsed_field=elapsed_field,
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


def _display_glyph(node, active_frame):
    glyph = _state_glyph(node)
    if active_frame is not None and row_bucket(node) == "active":
        return glyph._replace(glyph=active_frame)
    return glyph


def _hierarchy_stacked_first_line(row, layout, row_budget, active_frame=None):
    node = row.node
    glyph = _display_glyph(node, active_frame)
    icon_cell = Text(glyph.glyph, style=COLOURS[glyph.colour])
    if node.blocked_by:
        icon_cell = icon_cell + Text(
            DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
        )
    icon_field = pad_field(icon_cell, GLYPH_WIDTHS["icon"])
    content_cell = (
        Text(CONTENT_GLYPH.glyph, style=COLOURS[CONTENT_GLYPH.colour]) if has_content(node) else Text("")
    )
    content_field = pad_field(content_cell, GLYPH_WIDTHS["content"])
    id_field = pad_field(node.id, layout.atomic_widths["id"])
    content_so_far = icon_field + content_field + id_field
    role_cell = (
        Text(display_role(getattr(node, "role", None)), style=COLOURS["dim"])
        if node.type == "step" else Text("")
    )
    role_area = max(0, row_budget - len(content_so_far.plain))
    return content_so_far + pad_field_right(role_cell, role_area)


def _hierarchy_label(node, flow_service):
    if node.type != "step":
        return node.title
    if flow_service is None:
        base, phase = node.step, None
    else:
        base, phase = flow_service.display_for(node) or node.step, flow_service.phase_for(node)
    n = pass_number(node.pass_id)
    parts = (["pass %d" % n] if n > 1 else []) + ([phase] if phase else [])
    return " · ".join(parts + [base]) if parts else base


def _row_node(rows, row_id):
    return next((r.node for r in rows if r.node.id == row_id), None)


def hierarchy_row_cells(row, layout=None, row_budget=None, active_frame=None, flow_service=None):
    node = row.node
    if layout is not None and layout.stacked:
        first_line = _hierarchy_stacked_first_line(row, layout, row_budget, active_frame)
        indent = HIERARCHY_CONTINUATION_BASE_INDENT + row.depth
        label = _hierarchy_label(node, flow_service)
        return (stacked_cell(first_line, indent, label, row_budget),)
    glyph = _display_glyph(node, active_frame)
    icon_cell = Text(glyph.glyph, style=COLOURS[glyph.colour])
    if node.blocked_by:
        icon_cell = icon_cell + Text(
            DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
        )
    content_cell = (
        Text(CONTENT_GLYPH.glyph, style=COLOURS[CONTENT_GLYPH.colour]) if has_content(node) else ""
    )
    title_cell = ("  " * row.depth) + _hierarchy_label(node, flow_service)
    role_cell = (
        Text(display_role(getattr(node, "role", None)), style=COLOURS["dim"])
        if node.type == "step" else ""
    )
    return (icon_cell, content_cell, node.id, title_cell, role_cell)


def artifact_row_cells(artifact, layout=None, row_budget=None):
    if layout is not None and layout.stacked:
        type_field = pad_field(Text(type_label(artifact), style=COLOURS["dim"]), layout.atomic_widths["type"])
        return (
            stacked_cell(
                type_field, ARTIFACTS_CONTINUATION_INDENT, artifact.value, row_budget,
                prose_style=COLOURS["cyan"],
            ),
        )
    return (
        Text(type_label(artifact), style=COLOURS["dim"]),
        Text(artifact.value, style=COLOURS["cyan"]),
    )


def detail_row_cells(field, layout=None, row_budget=None):
    key, value = field
    label = DETAIL_FIELD_LABELS[key]
    style = COLOURS["cyan"] if key == "pr" else COLOURS["text"]
    if layout is not None and layout.stacked:
        key_field = pad_field(Text(label, style=COLOURS["dim"]), layout.atomic_widths["key"])
        return (
            stacked_cell(key_field, DETAIL_CONTINUATION_INDENT, value, row_budget, prose_style=style),
        )
    return (
        Text(label, style=COLOURS["dim"]),
        Text(value, style=style),
    )


def toast_text(success, message, kind, value, tab="artifacts"):
    base_caption = TOAST_SUB_CAPTION_BY_TAB[tab]
    prefix = TOAST_SUCCESS_PREFIX if success else TOAST_FAILURE_PREFIX
    colour = COLOURS["cyan"] if success else COLOURS["red"]
    main, sub = message, base_caption
    if success and kind == "url":
        sub = "%s - %s" % (base_caption, TOAST_URL_SUB_SUFFIX)
    elif success and kind == "filepath":
        main = "Opened %s" % value
        sub = "%s - %s" % (TOAST_FILEPATH_DESTINATION, base_caption)
    text = Text(prefix + main, style=colour)
    text.append("\n")
    text.append(sub, style=COLOURS["dim"])
    return text


def resume_toast_text(success, message):
    prefix = TOAST_SUCCESS_PREFIX if success else TOAST_FAILURE_PREFIX
    colour = COLOURS["cyan"] if success else COLOURS["red"]
    return Text(prefix + message, style=colour)


ESCALATION_TAG = "⚠ needs you"
ESCALATION_REASON_LINE_CAP = 4


def _capped_reason_lines(text, width):
    paragraphs = text.split("\n")
    lines = []
    offsets = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        consumed = 0
        for line in wrap_continuation(paragraph, width):
            consumed += len(line) + 1
            lines.append(line)
            offsets.append((paragraph_index, consumed))
    if len(lines) <= ESCALATION_REASON_LINE_CAP:
        return lines
    kept = lines[: ESCALATION_REASON_LINE_CAP - 1]
    cut_paragraph_index, cut_offset = offsets[ESCALATION_REASON_LINE_CAP - 2]
    remaining_parts = [paragraphs[cut_paragraph_index][cut_offset:].lstrip()]
    remaining_parts.extend(paragraphs[cut_paragraph_index + 1 :])
    remaining_text = " ".join(part for part in remaining_parts if part)
    kept.append(truncate_field(remaining_text, width))
    return kept


def _reason_lines_text(header, width):
    result = Text()
    for index, line in enumerate(_capped_reason_lines(header.escalation_text, width)):
        if index:
            result.append("\n")
        line_text = Text(line, style=COLOURS["text"])
        if header.escalation_target:
            idx = line.find(header.escalation_target)
            if idx != -1:
                line_text.stylize(COLOURS["cyan"], idx, idx + len(header.escalation_target))
        result.append_text(line_text)
    return result


def escalation_reason_text(header, width):
    return _reason_lines_text(header, width)


def escalation_panel_text(header, width):
    text = Text(ESCALATION_TAG, style="bold %s" % COLOURS["amber"])
    text.append("\n")
    text.append_text(_reason_lines_text(header, width))
    return text


class EscalationPanel(Static):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_id = None

    def on_resize(self, event: events.Resize) -> None:
        header = self.parent
        if isinstance(header, HubHeader) and header._last_header is not None:
            header._paint_escalation(header._last_header)


class HubHeader(Vertical):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_header = None

    def compose(self) -> ComposeResult:
        yield Static(id="hub-id")
        yield Static(id="hub-title")
        yield Static(id="hub-project")
        yield Static(id="hub-workflow")
        yield Static(id="hub-step")
        yield Static(id="hub-role")
        yield Static(id="hub-elapsed")
        yield Static(id="hub-state")
        yield EscalationPanel(id="hub-escalation")

    def update(self, header) -> None:
        self.query_one("#hub-id", Static).update(Text(header.id, style=COLOURS["cyan"]))
        self.query_one("#hub-title", Static).update(header.title or "")
        self._line("#hub-project", "project: %s" % header.project if header.project else None)
        self._line(
            "#hub-workflow", "workflow: %s" % header.workflow_line if header.workflow_line else None
        )
        self._field_line("#hub-step", "STEP", header.step_field)
        self._field_line("#hub-role", "ROLE", header.role_field)
        self._field_line("#hub-elapsed", "ELAPSED", header.elapsed_field)
        self._field_line("#hub-state", "STATE", header.state_field)

        self._last_header = header
        self._paint_escalation(header)

    def _paint_escalation(self, header) -> None:
        panel = self.query_one(EscalationPanel)
        if header.escalation_text:
            is_demand = header.escalation_target is None
            width = max(1, panel.size.width)
            painted = (
                escalation_panel_text(header, width) if is_demand
                else escalation_reason_text(header, width)
            )
            panel.update(painted)
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

    def _field_line(self, selector, key, value) -> None:
        widget = self.query_one(selector, Static)
        if value:
            text = Text("%s: " % key, style=COLOURS["dim"])
            text.append(str(value), style=COLOURS["text"])
            widget.update(text)
            widget.display = True
        else:
            widget.update("")
            widget.display = False


class HubTabStrip(Horizontal):
    def __init__(self, tabs, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tabs = tabs

    def compose(self) -> ComposeResult:
        for tab in self._tabs:
            yield Static(_TAB_LABELS[tab], id="hub-tab-%s" % tab, classes="tab-dim")

    def set_active(self, active) -> None:
        for tab in self._tabs:
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
        kwargs.setdefault("wrap", True)
        kwargs.setdefault("min_width", 0)
        kwargs.setdefault("max_lines", LOG_PANE_MAX_LINES)
        super().__init__(*args, **kwargs)
        self.live = False

    def watch_scroll_y(self, old, new) -> None:
        super().watch_scroll_y(old, new)
        self.auto_scroll = self.is_vertical_scroll_end

    def write_entry(self, content) -> int:
        before_deferred = len(self._deferred_renders)
        before = len(self.lines) + self._start_line
        self.write(content)
        if len(self._deferred_renders) > before_deferred:
            return 1
        return len(self.lines) + self._start_line - before

    def replace_last_entry(self, row_count, content) -> None:
        for _ in range(row_count):
            if self._deferred_renders:
                self._deferred_renders.pop()
            elif self.lines:
                self.lines.pop()
        self._line_cache.clear()
        self.write(content, scroll_end=False)


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
        if row_id is None or not isinstance(self.screen, NodeHubScreen):
            return
        node = _row_node(self.screen._last_rows, row_id)
        if node is None or node.type != "item":
            return
        self.screen.open_at(row_id, initial_tab="artifacts")

    def action_jump_log(self) -> None:
        row_id = self._highlighted_id()
        if row_id is None or not isinstance(self.screen, NodeHubScreen):
            return
        node = _row_node(self.screen._last_rows, row_id)
        if node is None or node.type != "step" or log_tab_mode(node) == "no-log":
            return
        self.screen.open_at(row_id, initial_tab="log")

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, NodeHubScreen):
            screen.refresh_hierarchy_width()

    def _page_height(self) -> int:
        height = self.scrollable_content_region.height - (
            self.header_height if self.show_header else 0
        )
        if isinstance(self.screen, NodeHubScreen):
            banner = self.screen.query_one("#pinned-ancestor", Static)
            if banner.display:
                height += 1
        return height

    def action_page_down(self) -> None:
        self._set_hover_cursor(False)
        if self.show_cursor and self.cursor_type in ("cell", "row"):
            height = self._page_height()
            offset = 0
            rows_to_scroll = 0
            row_index, _ = self.cursor_coordinate
            for ordered_row in self.ordered_rows[row_index:]:
                offset += ordered_row.height
                rows_to_scroll += 1
                if offset > height:
                    break
            target_row = row_index + rows_to_scroll - 1
            self.scroll_relative(y=height, animate=False, force=True)
            self.move_cursor(row=target_row, scroll=False)
        else:
            super().action_page_down()

    def action_page_up(self) -> None:
        self._set_hover_cursor(False)
        if self.show_cursor and self.cursor_type in ("cell", "row"):
            height = self._page_height()
            offset = 0
            rows_to_scroll = 0
            row_index, _ = self.cursor_coordinate
            for ordered_row in self.ordered_rows[: row_index + 1]:
                offset += ordered_row.height
                rows_to_scroll += 1
                if offset > height:
                    break
            target_row = row_index - rows_to_scroll + 1
            self.scroll_relative(y=-height, animate=False)
            self.move_cursor(row=target_row, scroll=False)
        else:
            super().action_page_up()


class ArtifactsTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("right", "select_cursor", "Open", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, NodeHubScreen):
            screen.refresh_artifacts_width()


class DetailTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("right", "select_cursor", "Open", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)

    def on_resize(self, event: events.Resize) -> None:
        screen = self.screen
        if isinstance(screen, NodeHubScreen):
            screen.refresh_detail_width()


class ArtifactTextBody(RichLog):
    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]


class DescriptionPane(RichLog):
    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]


class ArtifactListTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)


class ArtifactViewerHeader(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(id="artifact-viewer-kind")
        yield Static(id="artifact-viewer-count")

    def update(self, artifact_type, node_id, count_text) -> None:
        kind_text = Text()
        kind_text.append(artifact_type, style=COLOURS["cyan"])
        kind_text.append(" · %s" % node_id, style=COLOURS["dim"])
        self.query_one("#artifact-viewer-kind", Static).update(kind_text)
        self.query_one("#artifact-viewer-count", Static).update(
            Text(count_text, style=COLOURS["dim"]) if count_text else ""
        )


class ArtifactViewerScreen(Screen):
    BINDINGS = [
        Binding("escape", "close", "Back", show=False),
        Binding("left", "close", "Back", show=False),
    ]

    CSS = f"""
    ArtifactViewerHeader {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    #artifact-viewer-kind {{
        width: auto;
    }}
    #artifact-viewer-count {{
        width: 1fr;
        content-align: right middle;
    }}
    """

    def __init__(self, artifact, node_id):
        super().__init__()
        self._artifact = artifact
        self._node_id = node_id

    def on_mount(self) -> None:
        self._refresh_footer()
        self.set_interval(POLL_INTERVAL_SECONDS, self.poll_refresh)

    def poll_refresh(self) -> None:
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        container = self.app.container
        running = PoolRunningUseCase(container.lock).execute().running
        breaker = BreakerStatusUseCase(container.breaker).execute(self.app._now().timestamp())
        self.query_one(StatusBar).report(
            pool_running=running,
            breaker_is_open=breaker.is_open,
            breaker_is_probing=breaker.is_probing,
            breaker_reset_at=breaker.reset_at,
            version=__version__,
            upgrade_version=self.app.upgrade_version,
        )

    def action_close(self) -> None:
        self.app.pop_screen()


class TextArtifactViewerScreen(ArtifactViewerScreen):
    CSS = ArtifactViewerScreen.CSS + """
    ArtifactTextBody {
        height: 1fr;
    }
    """

    def __init__(self, artifact, node_id, position, total):
        super().__init__(artifact, node_id)
        self._position = position
        self._total = total

    def compose(self) -> ComposeResult:
        yield ArtifactViewerHeader(id="artifact-viewer-header")
        yield ArtifactTextBody(id="artifact-viewer-body", highlight=False, markup=False, wrap=True)
        yield DashboardFooter(id="artifact-viewer-footer", shortcuts=TEXT_ARTIFACT_SHORTCUTS)

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one(ArtifactViewerHeader).update(
            self._artifact.type, self._node_id, "%d / %d" % (self._position, self._total)
        )
        body = self.query_one(ArtifactTextBody)
        body.write(Text(self._artifact.value))
        self.set_focus(body)


class ListArtifactViewerScreen(ArtifactViewerScreen):
    CSS = ArtifactViewerScreen.CSS + """
    ArtifactListTable {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield ArtifactViewerHeader(id="artifact-viewer-header")
        yield ArtifactListTable(id="artifact-viewer-list")
        yield DashboardFooter(id="artifact-viewer-footer", shortcuts=LIST_ARTIFACT_SHORTCUTS)

    def on_mount(self) -> None:
        super().on_mount()
        table = self.query_one(ArtifactListTable)
        table.cursor_type = "row"
        table.show_header = False
        items = [line for line in self._artifact.value.splitlines() if line.strip()]
        self.query_one(ArtifactViewerHeader).update(
            self._artifact.type,
            self._node_id,
            "%d item%s" % (len(items), "" if len(items) == 1 else "s"),
        )
        table.add_column("value", key="value")
        for index, item in enumerate(items):
            table.add_row(item, key=str(index))
        if items:
            self.set_focus(table)


class NodeHubScreen(Screen):
    BINDINGS = [
        Binding("escape", "close_hub", "Back", show=False),
        Binding("left", "close_hub", "Back", show=False),
        Binding("[", "prev_tab", "Prev tab", show=False),
        Binding("]", "next_tab", "Next tab", show=False),
        Binding("t", "toggle_thinking", "Thinking", show=False),
        Binding("b", "open_blocker", "Open blocker", show=False),
        Binding("r", "resume", "Resume", show=False),
    ]

    CSS = f"""
    HubHeader {{
        height: auto;
    }}
    HierarchyPagingTable {{
        height: 1fr;
    }}
    ArtifactsTable {{
        height: 1fr;
    }}
    DetailTable {{
        height: 1fr;
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
        height: auto;
        display: none;
    }}
    #hub-log-empty, #hub-artifacts-empty, #hub-description-empty {{
        content-align: center middle;
        height: 1fr;
        color: {COLOURS["dim"]};
    }}
    #hierarchy-floor, #artifacts-floor, #detail-floor {{
        content-align: center middle;
        height: 1fr;
        color: {COLOURS["dim"]};
        display: none;
    }}
    #hub-artifacts-toast, #hub-detail-toast {{
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
        node = container.store.get_node(node_id)
        self._node_type = node.type
        self._tab_order = _tab_order(node)
        self._active_tab = None
        self._last_hierarchy_shape = None
        self._last_rows = []
        self._hierarchy_floor = False
        self._hierarchy_stacked = False
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
        self._last_artifacts_shape = None
        self._last_artifacts = []
        self._has_artifacts = False
        self._artifacts_floor = False
        self._artifacts_stacked = False
        self._last_detail_shape = None
        self._last_detail_fields = []
        self._detail_floor = False
        self._detail_stacked = False
        self._toast_active = False
        self._toast_tab = None
        self._toast_timer = None
        self._has_description = False
        self._last_description = None

    @property
    def container(self):
        return self._container

    def compose(self) -> ComposeResult:
        yield HubHeader(id="hub-header")
        yield HubTabStrip(self._tab_order, id="hub-tabs")
        yield Static(id="pinned-ancestor")
        yield HierarchyPagingTable(id="hierarchy-table")
        yield Static(id="hierarchy-floor")
        yield LogPane(id="hub-log-view", highlight=False, markup=False)
        yield Static(LOG_NO_STREAM_MESSAGE, id="hub-log-empty")
        yield ArtifactsTable(id="hub-artifacts-table")
        yield Static(id="artifacts-floor")
        yield Static(ARTIFACTS_EMPTY_MESSAGE, id="hub-artifacts-empty")
        yield Static(id="hub-artifacts-toast")
        yield DetailTable(id="hub-detail-table")
        yield Static(id="detail-floor")
        yield Static(id="hub-detail-toast")
        yield DescriptionPane(id="hub-description-view", highlight=False, markup=False, wrap=True, auto_scroll=False)
        yield Static(DESCRIPTION_EMPTY_MESSAGE, id="hub-description-empty")
        yield DashboardFooter(id="hub-footer", shortcuts=HUB_SHORTCUTS)

    def on_mount(self) -> None:
        table = self.query_one(HierarchyPagingTable)
        table.cursor_type = "row"
        table.show_header = False
        artifacts_table = self.query_one(ArtifactsTable)
        artifacts_table.cursor_type = "row"
        artifacts_table.show_header = False
        detail_table = self.query_one(DetailTable)
        detail_table.cursor_type = "row"
        detail_table.show_header = False
        store = self._container.store
        node = store.get_node(self._node_id)
        self._active_tab = self._forced_initial_tab or landing_tab(node)
        self._hierarchy_target_id = _hierarchy_default_row_id(store, node)
        self._setup_log_tab()
        self.app.screen_change_signal.subscribe(self, lambda screen: self._sync_active_glyph_animation())
        self.call_after_refresh(self._initial_refresh)
        self._poll_timer = self.set_interval(POLL_INTERVAL_SECONDS, self.poll_refresh)

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

    def _setup_log_tab(self) -> None:
        store = self._container.store
        node = store.get_node(self._node_id)
        log_node = node if node.type == "step" else None
        mode = log_tab_mode(log_node)
        self._log_mode = mode
        self._log_parser = LogLineParser()
        self._log_lines = []
        self._show_thinking = True
        empty = self.query_one("#hub-log-empty", Static)
        if mode == "no-log":
            empty.update(LOG_NO_STREAM_MESSAGE)
            return
        self._log_target = log_node.id
        log_pane = self.query_one(LogPane)
        log_pane.live = mode == "live"
        log_pane.auto_scroll = mode == "live"
        result = self._run_initial_tail()
        if result.path is None:
            self._log_mode = "no-log"
            empty.update(LOG_NO_STREAM_MESSAGE)
            return
        self._apply_tail_result(result)
        if self._log_mode == "live" and not self._log_finished:
            self._log_timer = self.set_interval(LOG_TAIL_INTERVAL_SECONDS, self._tail_tick)

    def _run_initial_tail(self):
        use_case = TailLogUseCase(
            self._container.store, self._container.workers, self._container.fs, self._container.config
        )
        return use_case.execute(TailLogInput(target=self._log_target, max_bytes=LOG_INITIAL_TAIL_BYTES))

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
        new_lines = self._log_parser.feed(result.data) if result.data else []
        if new_lines:
            self._log_lines = (self._log_lines + new_lines)[-LOG_LINES_MAX_RETAINED:]
            retained_new = new_lines[max(0, len(new_lines) - LOG_LINES_MAX_RETAINED):]
            self._write_tail_data(log_pane, retained_new)
        if self._log_mode == "live" and not result.live and not self._log_finished:
            self._clear_log_cursor(log_pane)
            self._log_finished = True
            log_pane.live = False
            log_pane.write(Text(LOG_FINISHED_MESSAGE, style=COLOURS["cyan"]))
            if self._log_timer is not None:
                self._log_timer.stop()

    def _visible_log_lines(self, lines):
        if self._show_thinking:
            return list(lines)
        return [line for line in lines if line.kind != LogKind.THINKING]

    def _render_log_line(self, line) -> Text:
        prefix = line.timestamp.astimezone().strftime("%H:%M:%S ") if line.timestamp else ""
        return Text(prefix + line.text, style=COLOURS["text"])

    def _paint_log_lines(self, log_pane, lines, live) -> None:
        for index, line in enumerate(lines):
            content = self._render_log_line(line)
            if live and index == len(lines) - 1:
                cursor_content = Text.assemble(content, (LOG_CURSOR_GLYPH, COLOURS["cyan"]))
                self._log_cursor_row_count = log_pane.write_entry(cursor_content)
                self._log_cursor_text = content
                self._log_cursor_active = True
            else:
                log_pane.write_entry(content)

    def _write_tail_data(self, log_pane, lines) -> None:
        visible = self._visible_log_lines(lines)
        if not visible:
            return
        live = self._log_mode == "live" and not self._log_finished
        if live:
            self._clear_log_cursor(log_pane)
        self._paint_log_lines(log_pane, visible, live)

    def _clear_log_cursor(self, log_pane) -> None:
        if not self._log_cursor_active:
            return
        log_pane.replace_last_entry(self._log_cursor_row_count, self._log_cursor_text)
        self._log_cursor_active = False

    def action_toggle_thinking(self) -> None:
        if self._active_tab != "log" or self._log_mode == "no-log":
            return
        self._show_thinking = not self._show_thinking
        log_pane = self.query_one(LogPane)
        log_pane.clear()
        self._log_cursor_active = False
        visible = self._visible_log_lines(self._log_lines)
        live = self._log_mode == "live" and not self._log_finished
        self._paint_log_lines(log_pane, visible, live)

    def _initial_refresh(self) -> None:
        self._refresh(initial=True)
        self._focus_active_tab()

    def poll_refresh(self) -> None:
        self._refresh(initial=False)

    def _refresh(self, initial) -> None:
        store = self._container.store
        node = store.get_node(self._node_id)
        self._flow_service = self._container.flow_service()
        header = build_header(store, node, self._now().isoformat(), self._flow_service)
        self.query_one(HubHeader).update(header)
        if node.type == "item":
            rows = HierarchyUseCase(store).execute(HierarchyInput(node=self._node_id)).rows
            self._render_hierarchy(rows, initial)
            self._render_artifacts(viewable_artifacts(node), initial)
            self._render_description(node.description)
        else:
            self._render_detail(store, node, initial)
        self.query_one(HubTabStrip).set_active(self._active_tab)
        self._apply_tab_visibility()
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        running = PoolRunningUseCase(self._container.lock).execute().running
        breaker = BreakerStatusUseCase(self._container.breaker).execute(self._now().timestamp())
        self.query_one(StatusBar).report(
            pool_running=running,
            breaker_is_open=breaker.is_open,
            breaker_is_probing=breaker.is_probing,
            breaker_reset_at=breaker.reset_at,
            version=__version__,
            upgrade_version=self.app.upgrade_version,
        )

    def _hierarchy_layout(self, table, rows):
        atomic_values = {
            "id": [r.node.id for r in rows],
            "role": [display_role(getattr(r.node, "role", None)) for r in rows if r.node.type == "step"],
        }
        row_budget = row_budget_for(table, len(COLUMN_GRIDS["hierarchy"]))
        max_depth = max((r.depth for r in rows), default=0)
        indent = HIERARCHY_CONTINUATION_BASE_INDENT + max_depth
        return compute_layout(row_budget, ["icon", "content"], atomic_values, indent)

    def refresh_hierarchy_width(self) -> None:
        table = self.query_one(HierarchyPagingTable)
        if not self._last_rows:
            return
        layout = self._hierarchy_layout(table, self._last_rows)
        if layout.floor != self._hierarchy_floor or layout.stacked != self._hierarchy_stacked or layout.stacked:
            self._render_hierarchy(self._last_rows, initial=True)
            self._apply_tab_visibility()
            return
        if layout.floor:
            self.query_one("#hierarchy-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["hierarchy"])), style=COLOURS["dim"])
            )
            return
        widths = {
            "icon": GLYPH_WIDTHS["icon"],
            "content": GLYPH_WIDTHS["content"],
            "id": layout.atomic_widths["id"],
            "title": layout.flexible_width,
            "role": layout.atomic_widths["role"],
        }
        apply_widths(table, widths)

    def refresh_artifacts_width(self) -> None:
        table = self.query_one(ArtifactsTable)
        if not self._last_artifacts:
            return
        layout = self._artifacts_layout(table, self._last_artifacts)
        if layout.floor != self._artifacts_floor or layout.stacked != self._artifacts_stacked or layout.stacked:
            self._render_artifacts(self._last_artifacts, initial=True)
            self._apply_tab_visibility()
            return
        if layout.floor:
            self.query_one("#artifacts-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["artifacts"])), style=COLOURS["dim"])
            )
            return
        apply_widths(table, {"type": layout.atomic_widths["type"], "value": layout.flexible_width})

    def refresh_detail_width(self) -> None:
        table = self.query_one(DetailTable)
        if not self._last_detail_fields:
            return
        layout = self._detail_layout(table, self._last_detail_fields)
        if layout.floor != self._detail_floor or layout.stacked != self._detail_stacked or layout.stacked:
            self._render_detail_fields(self._last_detail_fields, initial=True)
            self._apply_tab_visibility()
            return
        if layout.floor:
            self.query_one("#detail-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["detail"])), style=COLOURS["dim"])
            )
            return
        apply_widths(table, {"key": layout.atomic_widths["key"], "value": layout.flexible_width})

    def _selected_id(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def _render_hierarchy(self, rows, initial) -> None:
        self._last_rows = rows
        self._sync_active_glyph_animation()
        table = self.query_one(HierarchyPagingTable)
        shape = tuple(r.node.id for r in rows)
        if shape == self._last_hierarchy_shape and not initial:
            self._update_hierarchy_cells(table, rows)
            return
        if table.size.width == 0:
            return

        layout = self._hierarchy_layout(table, rows)
        self._hierarchy_floor = bool(rows) and layout.floor
        self._hierarchy_stacked = layout.stacked
        if self._hierarchy_floor:
            self.query_one("#hierarchy-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["hierarchy"])), style=COLOURS["dim"])
            )
            self._last_hierarchy_shape = shape
            return

        selected_id = self._selected_id(table) or self._hierarchy_target_id
        table.clear(columns=True)
        row_budget = render_row_budget(table, layout, len(COLUMN_GRIDS["hierarchy"]))
        self._hierarchy_layout_cache = layout
        self._hierarchy_row_budget_cache = row_budget
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {
                "icon": GLYPH_WIDTHS["icon"],
                "content": GLYPH_WIDTHS["content"],
                "id": layout.atomic_widths["id"],
                "title": layout.flexible_width,
                "role": layout.atomic_widths["role"],
            }
            for key in COLUMN_GRIDS["hierarchy"]:
                table.add_column(key, width=widths[key], key=key)

        ids = [r.node.id for r in rows]
        index = ids.index(selected_id) if selected_id in ids else 0
        active_frame = self._active_glyph_char()
        for row in rows:
            table.add_row(
                *hierarchy_row_cells(
                    row, layout, row_budget, active_frame=active_frame,
                    flow_service=self._flow_service,
                ),
                height=None, key=row.node.id
            )

        self._last_hierarchy_shape = shape
        if rows:
            table.move_cursor(row=index)
        self.update_pinned_ancestor()

    def _update_hierarchy_cells(self, table, rows) -> None:
        table_ = self.query_one(HierarchyPagingTable)
        layout = self._hierarchy_layout(table_, rows)
        row_budget = render_row_budget(table_, layout, len(COLUMN_GRIDS["hierarchy"]))
        self._hierarchy_layout_cache = layout
        self._hierarchy_row_budget_cache = row_budget
        active_frame = self._active_glyph_char()
        for row in rows:
            cells = hierarchy_row_cells(
                row, layout, row_budget, active_frame=active_frame,
                flow_service=self._flow_service,
            )
            if layout.stacked:
                table.update_cell(row.node.id, STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(COLUMN_GRIDS["hierarchy"], cells):
                table.update_cell(row.node.id, key, value)

    def _active_glyph_char(self) -> str:
        return ACTIVE_GLYPH_FRAMES[self._active_glyph_frame]

    def _active_glyph_ids(self):
        return tuple(r.node.id for r in self._last_rows if row_bucket(r.node) == "active")

    def _sync_active_glyph_animation(self) -> None:
        should_run = (
            self._active_tab == "hierarchy"
            and self.is_current
            and bool(self._active_glyph_ids())
            and not self._hierarchy_floor
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
        active_ids = self._active_glyph_ids()
        if not active_ids or self._hierarchy_layout_cache is None:
            return
        table = self.query_one(HierarchyPagingTable)
        frame = self._active_glyph_char()
        layout = self._hierarchy_layout_cache
        row_budget = self._hierarchy_row_budget_cache
        rows_by_id = {r.node.id: r for r in self._last_rows}
        for node_id in active_ids:
            row = rows_by_id.get(node_id)
            if row is None:
                continue
            cells = hierarchy_row_cells(
                row, layout, row_budget, active_frame=frame, flow_service=self._flow_service,
            )
            try:
                if layout.stacked:
                    table.update_cell(node_id, STACKED_COLUMN_KEY, cells[0])
                else:
                    table.update_cell(node_id, "icon", cells[0])
            except CellDoesNotExist:
                pass
        self.update_pinned_ancestor()

    def _artifacts_layout(self, table, artifacts):
        atomic_values = {"type": [type_label(a) for a in artifacts]}
        row_budget = row_budget_for(table, len(COLUMN_GRIDS["artifacts"]))
        return compute_layout(row_budget, [], atomic_values, indent=ARTIFACTS_CONTINUATION_INDENT)

    def _detail_layout(self, table, fields):
        atomic_values = {"key": [DETAIL_FIELD_LABELS[key] for key, _value in fields]}
        row_budget = row_budget_for(table, len(COLUMN_GRIDS["detail"]))
        return compute_layout(row_budget, [], atomic_values, indent=DETAIL_CONTINUATION_INDENT)

    def _selected_artifact_index(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        value = cell_key.row_key.value
        return int(value) if value is not None else None

    def _render_artifacts(self, artifacts, initial) -> None:
        self._last_artifacts = artifacts
        self._has_artifacts = bool(artifacts)
        table = self.query_one(ArtifactsTable)
        shape = tuple((a.type, a.value, a.label, a.kind) for a in artifacts)
        if shape == self._last_artifacts_shape and not initial:
            self._last_artifacts_shape = shape
            self._update_artifact_cells(table, artifacts)
            return
        if table.size.width == 0:
            return

        layout = self._artifacts_layout(table, artifacts)
        self._artifacts_floor = bool(artifacts) and layout.floor
        self._artifacts_stacked = layout.stacked
        if self._artifacts_floor:
            self.query_one("#artifacts-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["artifacts"])), style=COLOURS["dim"])
            )
            self._last_artifacts_shape = shape
            return

        selected_index = self._selected_artifact_index(table)
        table.clear(columns=True)
        row_budget = render_row_budget(table, layout, len(COLUMN_GRIDS["artifacts"]))
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {"type": layout.atomic_widths["type"], "value": layout.flexible_width}
            for key in COLUMN_GRIDS["artifacts"]:
                table.add_column(key, width=widths[key], key=key)

        for index, artifact in enumerate(artifacts):
            table.add_row(
                *artifact_row_cells(artifact, layout, row_budget), height=None, key=str(index)
            )

        self._last_artifacts_shape = shape
        if artifacts:
            has_selection = selected_index is not None and selected_index < len(artifacts)
            table.move_cursor(row=selected_index if has_selection else 0)

    def _update_artifact_cells(self, table, artifacts) -> None:
        layout = self._artifacts_layout(table, artifacts)
        row_budget = render_row_budget(table, layout, len(COLUMN_GRIDS["artifacts"]))
        for index, artifact in enumerate(artifacts):
            cells = artifact_row_cells(artifact, layout, row_budget)
            if layout.stacked:
                table.update_cell(str(index), STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(COLUMN_GRIDS["artifacts"], cells):
                table.update_cell(str(index), key, value)

    def _render_detail(self, store, step, initial) -> None:
        run = StepRunUseCase(store, self._flow_service).execute(StepRunInput(step=step.id))
        self._render_detail_fields(detail_fields(step, run), initial)

    def _render_detail_fields(self, fields, initial) -> None:
        self._last_detail_fields = fields
        table = self.query_one(DetailTable)
        shape = tuple(fields)
        if shape == self._last_detail_shape and not initial:
            self._last_detail_shape = shape
            self._update_detail_cells(table, fields)
            return
        if table.size.width == 0:
            return

        layout = self._detail_layout(table, fields)
        self._detail_floor = bool(fields) and layout.floor
        self._detail_stacked = layout.stacked
        if self._detail_floor:
            self.query_one("#detail-floor", Static).update(
                Text(floor_message(layout, table, len(COLUMN_GRIDS["detail"])), style=COLOURS["dim"])
            )
            self._last_detail_shape = shape
            return

        selected_key = self._selected_detail_key(table)
        table.clear(columns=True)
        row_budget = render_row_budget(table, layout, len(COLUMN_GRIDS["detail"]))
        if layout.stacked:
            table.add_column(STACKED_COLUMN_KEY, width=row_budget, key=STACKED_COLUMN_KEY)
        else:
            widths = {"key": layout.atomic_widths["key"], "value": layout.flexible_width}
            for key in COLUMN_GRIDS["detail"]:
                table.add_column(key, width=widths[key], key=key)

        for field in fields:
            table.add_row(
                *detail_row_cells(field, layout, row_budget), height=None, key=field[0]
            )

        self._last_detail_shape = shape
        if fields:
            keys = [key for key, _value in fields]
            index = keys.index(selected_key) if selected_key in keys else 0
            table.move_cursor(row=index)

    def _selected_detail_key(self, table):
        if table.row_count == 0:
            return None
        try:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except CellDoesNotExist:
            return None
        return cell_key.row_key.value

    def _update_detail_cells(self, table, fields) -> None:
        layout = self._detail_layout(table, fields)
        row_budget = render_row_budget(table, layout, len(COLUMN_GRIDS["detail"]))
        for field in fields:
            cells = detail_row_cells(field, layout, row_budget)
            if layout.stacked:
                table.update_cell(field[0], STACKED_COLUMN_KEY, cells[0])
                continue
            for key, value in zip(COLUMN_GRIDS["detail"], cells):
                table.update_cell(field[0], key, value)

    def _render_description(self, description) -> None:
        if description == self._last_description:
            return
        self._last_description = description
        self._has_description = bool(description)
        pane = self.query_one(DescriptionPane)
        pane.clear()
        if description:
            pane.write(Text(description, style=COLOURS["text"]))

    def update_pinned_ancestor(self) -> None:
        banner = self.query_one("#pinned-ancestor", Static)
        if self._active_tab != "hierarchy" or not self._last_rows or self._hierarchy_floor:
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
        glyph = _display_glyph(ancestor.node, self._active_glyph_char())
        text = Text(glyph.glyph + "  ", style=COLOURS[glyph.colour])
        text.append("%s  %s" % (ancestor.node.id, ancestor.node.title), style=COLOURS["dim"])
        banner.update(text)
        banner.display = True

    def _apply_tab_visibility(self) -> None:
        hierarchy_active = self._active_tab == "hierarchy"
        showing_hierarchy_floor = hierarchy_active and self._hierarchy_floor
        self.query_one(HierarchyPagingTable).display = hierarchy_active and not showing_hierarchy_floor
        self.query_one("#hierarchy-floor", Static).display = showing_hierarchy_floor
        log_active = self._active_tab == "log"
        self.query_one(LogPane).display = log_active and self._log_mode != "no-log"
        self.query_one("#hub-log-empty", Static).display = log_active and self._log_mode == "no-log"
        artifacts_active = self._active_tab == "artifacts"
        showing_artifacts_toast = artifacts_active and self._toast_active and self._toast_tab == "artifacts"
        showing_artifacts_floor = (
            artifacts_active and self._artifacts_floor and not showing_artifacts_toast
        )
        self.query_one(ArtifactsTable).display = (
            artifacts_active and self._has_artifacts
            and not showing_artifacts_toast and not showing_artifacts_floor
        )
        self.query_one("#artifacts-floor", Static).display = showing_artifacts_floor
        self.query_one("#hub-artifacts-empty", Static).display = (
            artifacts_active and not self._has_artifacts and not showing_artifacts_toast
        )
        self.query_one("#hub-artifacts-toast", Static).display = showing_artifacts_toast
        detail_active = self._active_tab == "detail"
        showing_detail_toast = detail_active and self._toast_active and self._toast_tab == "detail"
        showing_detail_floor = detail_active and self._detail_floor and not showing_detail_toast
        self.query_one(DetailTable).display = (
            detail_active and not showing_detail_toast and not showing_detail_floor
        )
        self.query_one("#detail-floor", Static).display = showing_detail_floor
        self.query_one("#hub-detail-toast", Static).display = showing_detail_toast
        description_active = self._active_tab == "description"
        self.query_one(DescriptionPane).display = description_active and self._has_description
        self.query_one("#hub-description-empty", Static).display = (
            description_active and not self._has_description
        )
        self.update_pinned_ancestor()
        self._sync_active_glyph_animation()

    def _focus_active_tab(self) -> None:
        if self._active_tab == "hierarchy" and not self._hierarchy_floor:
            self.set_focus(self.query_one(HierarchyPagingTable))
        elif self._active_tab == "log" and self._log_mode != "no-log":
            self.set_focus(self.query_one(LogPane))
        elif (
            self._active_tab == "artifacts"
            and self._has_artifacts
            and not (self._toast_active and self._toast_tab == "artifacts")
            and not self._artifacts_floor
        ):
            self.set_focus(self.query_one(ArtifactsTable))
        elif (
            self._active_tab == "detail"
            and not (self._toast_active and self._toast_tab == "detail")
            and not self._detail_floor
        ):
            self.set_focus(self.query_one(DetailTable))
        elif self._active_tab == "description" and self._has_description:
            self.set_focus(self.query_one(DescriptionPane))
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

    def action_open_blocker(self) -> None:
        target_id = self.query_one(EscalationPanel).target_id
        if target_id:
            self.open_at(target_id)

    def action_resume(self) -> None:
        store = self._container.store
        node = store.get_node(self._node_id)
        if node.type != "step" or not node.park:
            return
        try:
            response = UnblockStepUseCase(store, self._container.flow_service()).execute(
                UnblockInput(step=self._node_id)
            )
        except UseCaseError as e:
            self._show_resume_toast(False, str(e))
            return
        self._show_resume_toast(True, "Resumed - reassigned to %s" % response.role)
        self._refresh(initial=False)

    def open_at(self, node_id, initial_tab=None) -> None:
        self.app.push_screen(NodeHubScreen(self._container, node_id, self._now, initial_tab=initial_tab))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if event.data_table.id == "hub-artifacts-table":
            self._open_selected_artifact(event.row_key.value)
            return
        if event.data_table.id == "hub-detail-table":
            self._open_selected_detail_field(event.row_key.value)
            return
        row_id = event.row_key.value
        if row_id is None or row_id == self._node_id:
            return
        node = _row_node(self._last_rows, row_id)
        if node is not None and node.type == "pass":
            return
        self.open_at(row_id)

    def _open_selected_artifact(self, key_value) -> None:
        if key_value is None:
            return
        index = int(key_value)
        if index >= len(self._last_artifacts):
            return
        artifact = self._last_artifacts[index]
        kind = artifact.kind or "text"
        if kind in ("url", "filepath"):
            self._open_external_artifact(kind, artifact.value)
        elif kind == "list":
            self.app.push_screen(ListArtifactViewerScreen(artifact, self._node_id))
        else:
            self.app.push_screen(
                TextArtifactViewerScreen(
                    artifact, self._node_id, index + 1, len(self._last_artifacts)
                )
            )

    def _open_selected_detail_field(self, key_value) -> None:
        if key_value != "pr":
            return
        pr = next((value for key, value in self._last_detail_fields if key == "pr"), None)
        if pr is None:
            return
        use_case = OpenArtifactUseCase(self._container.fs, self._container.launcher)
        result = use_case.execute(OpenArtifactInput(kind="url", value=pr))
        self._show_toast(result.success, result.message, "url", pr, tab="detail")

    def _open_external_artifact(self, kind, value) -> None:
        use_case = OpenArtifactUseCase(self._container.fs, self._container.launcher)
        result = use_case.execute(OpenArtifactInput(kind=kind, value=value))
        self._show_toast(result.success, result.message, kind, value, tab="artifacts")

    def _toast_widget(self):
        return self.query_one("#hub-detail-toast" if self._toast_tab == "detail" else "#hub-artifacts-toast", Static)

    def _show_toast(self, success, message, kind, value, tab="artifacts") -> None:
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
        if self._active_tab in ("artifacts", "detail"):
            self._focus_active_tab()
