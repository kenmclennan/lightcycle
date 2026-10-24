import re
from dataclasses import dataclass
from lightcycle.adapters.tui.design_system import (
    COLOURS,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    DONE_GLYPH,
    Glyph,
    HUMAN_STEP_GLYPH,
    STATE_GLYPHS,
)
from lightcycle.adapters.tui.prose_text import prose_text
from lightcycle.adapters.tui.row_grid import (
    GLYPH_WIDTHS,
    pad_atomic_field,
    pad_field,
    pad_field_right,
    stacked_cell,
    truncate_field,
    wrap_continuation,
)
from lightcycle.application.work.current_step import current_step
from lightcycle.application.work.project_of import (
    project_of,
    short_project_label,
)
from lightcycle.application.work.step_context import (
    SECTION_INPUTS,
    SECTION_OUTPUTS,
    SECTION_RECORDS,
)
from lightcycle.domain.feedback import Duration
from lightcycle.domain.money import Cost
from lightcycle.domain.runs import pass_number
from lightcycle.domain.work import (
    State,
    is_human_step,
    item_active_seconds,
    item_cost,
    parse_timestamp,
    row_bucket,
    step_cost,
)
from lightcycle.domain.work.step_focus import (
    FOCUS_CONTEXT,
    FOCUS_DESCRIPTION,
    FOCUS_DETAIL,
    FOCUS_LOG,
    FOCUS_REASON,
    FOCUS_WORKFLOW,
)
from lightcycle.domain.workflows.identity import parse_pin
from lightcycle.render import (
    display_stage,
    format_elapsed,
    format_rate,
    format_tokens,
    format_usd,
    format_wall_and_active,
)
from rich.console import Console
from rich.text import Text
from typing import Optional


POLL_INTERVAL_SECONDS = 10


LOG_TAIL_INTERVAL_SECONDS = 1


LOG_INITIAL_TAIL_BYTES = 256 * 1024


LOG_LINES_MAX_RETAINED = 4000


LOG_PANE_MAX_LINES = 20000


LOG_NO_STREAM_MESSAGE = "Nothing live to stream."


LOG_FINISHED_MESSAGE = "✓ step finished"


LOG_CURSOR_GLYPH = "▌"


OUTPUTS_EMPTY_MESSAGE = "This item has no outputs yet."


DESCRIPTION_EMPTY_MESSAGE = "This item has no description to show."


DETAIL_EMPTY_MESSAGE = "This step has nothing to show here yet."


CONTEXT_EMPTY_MESSAGE = "This step has no context to show."


CONTEXT_RECONSTRUCTED_NOTE = (
    "Reconstructed from the item's current state; this step closed before inputs were frozen at claim."
)


DETAIL_BLOCK_THRESHOLD = 80


TOAST_DURATION_SECONDS = 2.0


TOAST_SUCCESS_PREFIX = "↗ "


TOAST_FAILURE_PREFIX = "⚠ "


TOAST_SUB_CAPTION_BY_TAB = {
    "outputs": "back to the outputs list automatically",
    "detail": "back to the step's detail automatically",
    "context": "back to the step's context automatically",
}


TOAST_URL_SUB_SUFFIX = "nothing more to show here"


TOAST_FILEPATH_DESTINATION = "in its default application"


TOAST_EDITOR_DESTINATION = "in your editor"


WORKFLOW_UNRESOLVED = "workflow unresolved"


_ITEM_TAB_ORDER = ("description", "outputs", "workflow", "cost")


_STEP_TAB_ORDER = ("detail", "context", "workflow", "log", "cost")


_TAB_LABELS = {
    "description": "Description", "workflow": "Workflow", "outputs": "Outputs",
    "detail": "Detail", "context": "Context", "log": "Log", "cost": "Cost",
    "overview": "Overview", "items": "Items",
}


def _tab_order(node):
    if node.type == "item":
        return _ITEM_TAB_ORDER
    return _STEP_TAB_ORDER


_TAB_BY_FOCUS = {
    FOCUS_LOG: "log",
    FOCUS_REASON: "detail",
    FOCUS_DETAIL: "detail",
    FOCUS_CONTEXT: "context",
    FOCUS_WORKFLOW: "workflow",
    FOCUS_DESCRIPTION: "description",
}


def landing_tab(focus):
    return _TAB_BY_FOCUS[focus.kind]


def display_role(role):
    return role or "human"


STACKED_COLUMN_KEY = "row"


HIERARCHY_CONTINUATION_BASE_INDENT = GLYPH_WIDTHS["icon"]


OUTPUTS_CONTINUATION_INDENT = 2


DETAIL_CONTINUATION_INDENT = 2


DETAIL_BODY_SUFFIX = "#body"


CONTEXT_CONTINUATION_INDENT = 2


CONTEXT_INPUTS_LIVE_TITLE = "INPUTS (live, not yet frozen)"


CONTEXT_NONE_TEXT = "none"


DETAIL_FIELD_LABELS = {
    "pr": "PR", "spec-pr": "SPEC PR", "branch": "BRANCH", "worktree": "WORKTREE",
    "spec": "SPEC", "ci-checks": "CI CHECKS",
    "model": "MODEL", "claimed_by": "CLAIMED_BY", "session": "SESSION",
    "outcome": "OUTCOME", "report": "REPORT",
    "needs": "NEEDS", "reason": "REASON",
}


def _detail_field_label(key):
    return DETAIL_FIELD_LABELS.get(key) or key.upper()


COST_CONTINUATION_INDENT = 2


COST_COLUMN_GAP = 2


COST_NOT_RECORDED = "not recorded"


COST_CACHE_HIT_RATE_DEFINITION = "cache-read ÷ (cache-read + cache-creation + input)"


COST_EMPTY_MESSAGE = "This step has no cost to show."


COST_NOT_RUN_MESSAGE = "This step hasn't run yet."


COST_NO_TOOLS_MESSAGE = "No tool calls recorded for this step."


ITEM_COST_EMPTY_MESSAGE = "This item has no usage to show yet."


COST_FIELD_LABELS = {
    "turns": "TURNS", "api_calls": "API CALLS", "input_tokens": "INPUT TOKENS", "output_tokens": "OUTPUT TOKENS",
    "cache_read_tokens": "CACHE READ TOKENS", "cache_creation_tokens": "CACHE CREATION TOKENS",
    "thinking_tokens": "THINKING TOKENS", "cache_hit_rate": "CACHE HIT RATE", "cost": "COST",
    "cost_basis": "COST BASIS", "rates_used": "RATES USED",
}


def _cost_field_label(key):
    return COST_FIELD_LABELS[key]


def _cost_hit_rate_field(rate):
    return "%s (%s)" % (format_rate(rate), COST_CACHE_HIT_RATE_DEFINITION)


def _rates_used_text(rates_used):
    return "%s in / %s out / %s cache-write / %s cache-read per MTok" % (
        format_usd(Cost.from_usd(rates_used["input"])),
        format_usd(Cost.from_usd(rates_used["output"])),
        format_usd(Cost.from_usd(rates_used["cache_write"])),
        format_usd(Cost.from_usd(rates_used["cache_read"])),
    )


def _unpriced_suffix(unpriced_count):
    if not unpriced_count:
        return ""
    return " (%d unpriced)" % unpriced_count


def step_cost_fields(cost):
    fields = [
        ("cost", format_usd(cost.cost_usd) if cost.recorded and cost.cost_usd else COST_NOT_RECORDED),
    ]
    fields.append(("cost_basis", cost.cost_basis if cost.recorded else COST_NOT_RECORDED))
    if cost.cost_basis == "derived" and cost.rates_used:
        fields.append(("rates_used", _rates_used_text(cost.rates_used)))
    fields.append(("turns", format_tokens(cost.turn_count)))
    if cost.api_calls is not None:
        fields.append(("api_calls", format_tokens(cost.api_calls)))
    fields.append(("input_tokens", format_tokens(cost.input_tokens)))
    fields.append(("output_tokens", format_tokens(cost.output_tokens)))
    fields.append(("cache_read_tokens", format_tokens(cost.cache_read_tokens)))
    fields.append(("cache_creation_tokens", format_tokens(cost.cache_creation_tokens)))
    if cost.thinking_tokens is not None:
        fields.append(("thinking_tokens", format_tokens(cost.thinking_tokens)))
    fields.append(("cache_hit_rate", _cost_hit_rate_field(cost.cache_hit_rate)))
    return fields


def item_cost_fields(cost):
    cost_text = format_usd(cost.cost_usd) if cost.cost_usd else COST_NOT_RECORDED
    fields = [("cost", cost_text + _unpriced_suffix(cost.unpriced_count))]
    fields.append(("turns", format_tokens(cost.turn_count)))
    if cost.api_calls is not None:
        fields.append(("api_calls", format_tokens(cost.api_calls)))
    fields.append(("input_tokens", format_tokens(cost.input_tokens)))
    fields.append(("output_tokens", format_tokens(cost.output_tokens)))
    fields.append(("cache_read_tokens", format_tokens(cost.cache_read_tokens)))
    fields.append(("cache_creation_tokens", format_tokens(cost.cache_creation_tokens)))
    if cost.thinking_tokens is not None:
        fields.append(("thinking_tokens", format_tokens(cost.thinking_tokens)))
    fields.append(("cache_hit_rate", _cost_hit_rate_field(cost.cache_hit_rate)))
    return fields


def _stage_cost_text(row):
    suffix = _unpriced_suffix(row.unpriced_count)
    if row.cost_usd:
        return format_usd(row.cost_usd) + suffix
    if row.turn_count > 0:
        return COST_NOT_RECORDED + suffix
    return format_usd(Cost())


def _cost_tool_atomic_text(row):
    return "%s calls" % format_tokens(row.calls), "%s bytes" % format_tokens(row.bytes)


def _cost_stage_atomic_text(row):
    steps_text = "%d step%s · %d turn%s" % (
        row.step_count, "" if row.step_count == 1 else "s",
        row.turn_count, "" if row.turn_count == 1 else "s",
    )
    return steps_text, _stage_cost_text(row)


def _cost_breakdown_value(kind, row):
    if kind == "step":
        calls_text, bytes_text = _cost_tool_atomic_text(row)
        return "%s · %s" % (calls_text, bytes_text)
    steps_text, cost_text = _cost_stage_atomic_text(row)
    return "%s · %s" % (steps_text, cost_text)


def _cost_rows_for_step(cost):
    rows = [(key, _cost_field_label(key), value) for key, value in step_cost_fields(cost)]
    rows.append(("__divider__", None, ""))
    if cost.tools:
        for row in cost.tools:
            rows.append(("tool:%s" % row.tool, row.tool, _cost_breakdown_value("step", row)))
    else:
        rows.append(("__no_tools__", None, COST_NO_TOOLS_MESSAGE))
    return rows


def _cost_rows_for_item(cost):
    rows = [(key, _cost_field_label(key), value) for key, value in item_cost_fields(cost)]
    rows.append(("__divider__", None, ""))
    for row in cost.stages:
        rows.append(("stage:%s" % row.stage, row.stage, _cost_breakdown_value("item", row)))
    return rows


def _owning_id(node):
    return node.item if node.type == "step" else node.id


def project_label(store, node):
    return short_project_label(project_of(store, _owning_id(node)))


def _hierarchy_default_row_id(store, node):
    if node.type != "item" or node.blocked_by or node.state == State.DONE:
        return node.id
    cur = current_step(store, node.id)
    return cur.id if cur is not None else node.id


def detail_fields(entries):
    return [(e.key, e.value) for e in entries if e.value]


def shorten_home(value, home):
    if not value or not home or home == "/":
        return value
    return re.sub(r"(?<![\w/.~-])" + re.escape(home.rstrip("/")) + r"(?![\w.-])", "~", value)


PARK_PANEL_TITLE = "\u25b2 Blocked"


def park_panel_text(park, home):
    parts = []
    if park.reason:
        parts.append(Text(shorten_home(park.reason, home), style=COLOURS["text"]))
    if park.needs:
        parts.append(Text(shorten_home(park.needs, home), style="bold " + COLOURS["text"]))
    if park.tried:
        parts.append(Text("Already tried: " + shorten_home(park.tried, home), style=COLOURS["dim"]))
    if not parts:
        return None
    return Text("\n\n").join(parts)


def log_tab_mode(node):
    if node is None:
        return "no-log"
    if getattr(node, "role", None) == "engine":
        if getattr(node, "log_path", None) is None:
            return "no-log"
        return "live" if node.state == State.QUEUED else "historical"
    if getattr(node, "role", None) in ("human", "engine"):
        return "no-log"
    if node.state == State.RUNNING:
        return "live"
    if node.state == State.DONE:
        return "historical"
    return "no-log"


@dataclass(frozen=True)
class HeaderData:
    id: str
    title: str
    project: Optional[str]
    stat_line: Optional[str]
    workflow_text: Optional[str]
    glyph: Glyph
    dependency_blocked: bool
    escalation_text: Optional[str]
    escalation_target: Optional[str]


def build_header(store, node, now, flow_service, pool_halted, pool_running):
    project = project_label(store, node) or None
    if node.type == "item":
        return _item_header(store, node, now, project, flow_service, pool_halted, pool_running)
    return _step_header(store, node, now, project, flow_service, pool_halted, pool_running)


def _park_escalation_text(node):
    if node.park.reason:
        return "%s\n%s" % (node.park.needs, node.park.reason)
    return node.park.needs


def _dependency_escalation(node):
    if node.state != State.BLOCKED or not node.blocked_by:
        return None, None
    target = sorted(node.blocked_by)[0]
    return "Blocked · depends on %s" % target, target


def _flow_for_bucket(node, flow_service):
    if flow_service is None or getattr(node, "type", None) != "step":
        return None
    return flow_service.flow_for(node)


def _step_count_text(children):
    n = len(children)
    return "%d step%s" % (n, "" if n == 1 else "s")


def _format_item_cost(cost):
    base = format_usd(cost.cost_usd) if cost.cost_usd else COST_NOT_RECORDED
    return base + _unpriced_suffix(cost.unpriced_count)


def _item_cost_text(children):
    cost = item_cost(children)
    if cost.turn_count == 0 and not cost.cost_usd:
        return ""
    return _format_item_cost(cost)


def _item_wall_active(store, item, children, now):
    start = Duration.earliest_claim(store.history(child.id) for child in children)
    if start is None:
        return None
    end = item.closed_at if item.state == State.DONE and item.closed_at else now
    wall = (
        parse_timestamp(end) - parse_timestamp(start)
    ).total_seconds()
    active = item_active_seconds(children)
    return wall, active


def _workflow_selector_pin(flow_service, node):
    selector, _source = flow_service.workflow_owner(node)
    if selector is None:
        return None, None
    try:
        return flow_service.resolve_selection(selector), None
    except ValueError as error:
        return None, str(error)


def _workflow_text(flow_service, node):
    pin, error = _workflow_selector_pin(flow_service, node)
    if error is not None:
        return WORKFLOW_UNRESOLVED
    if pin is None:
        return None
    parsed = parse_pin(pin)
    if parsed is None:
        return pin
    origin, name, sha = parsed
    return "%s/%s (%s)" % (origin, name, sha[:8])


def _stat_line_item(store, item, children, flow_service, now, pool_halted=False):
    if item.blocked_by:
        return None
    if item.state == State.DONE:
        lead = "Done"
    else:
        cur = current_step(store, item.id)
        if cur is None or cur.state == State.BLOCKED:
            return None
        lead = display_stage(flow_service.display_for(cur), cur.stage)
    segments = [lead, _step_count_text(children)]
    wall_active = _item_wall_active(store, item, children, now)
    if wall_active is not None:
        segments.append(format_wall_and_active(*wall_active))
    cost_text = _item_cost_text(children)
    if cost_text:
        segments.append(cost_text)
    if item.state == State.QUEUED and pool_halted:
        segments.append("pool halted")
    return " · ".join(segments)


def _gate_wait_seconds(store, node, now):
    parked = Duration(store.history(node.id)).last_release()
    start = parked or node.created_at
    if not start:
        return None
    end = node.closed_at if node.state == State.DONE else now
    return (
        parse_timestamp(end) - parse_timestamp(start)
    ).total_seconds()


def _step_wall_active(store, node, now):
    delta = Duration(store.history(node.id)).elapsed_since_last_claim(now)
    if delta is None:
        return None
    return delta.total_seconds(), node.active_seconds or 0


def _engine_wait_seconds(node, now):
    if not node.created_at:
        return None
    end = node.closed_at if node.state == State.DONE else now
    return (parse_timestamp(end) - parse_timestamp(node.created_at)).total_seconds()


def _stat_line_step(store, node, flow_service, now, pool_halted=False):
    phrase = display_stage(flow_service.display_for(node), node.stage)
    role = display_role(getattr(node, "role", None))
    if role == "human":
        wait = _gate_wait_seconds(store, node, now)
        if wait is None:
            return phrase
        label = "done" if node.state == State.DONE else "waiting"
        return "%s · %s %s" % (phrase, label, format_elapsed(wait))
    if role == "engine":
        wait = _engine_wait_seconds(node, now)
        if wait is None:
            return phrase
        label = "done" if node.state == State.DONE else "waiting"
        return "%s · %s %s" % (phrase, label, format_elapsed(wait))
    segments = [phrase]
    if node.state == State.DONE:
        segments.append("done")
    wall_active = _step_wall_active(store, node, now)
    if wall_active is not None:
        segments.append(format_wall_and_active(*wall_active))
    cost_text = hierarchy_usage_text(node)[1]
    if cost_text:
        segments.append(cost_text)
    if node.state == State.QUEUED and pool_halted:
        segments.append("pool halted")
    return " · ".join(segments)


def _item_header(store, node, now, project, flow_service, pool_halted, pool_running):
    glyph_node, glyph_flow = node, None
    children = store.children(node.id)

    escalation_text, escalation_target = _dependency_escalation(node)
    if escalation_text is None and node.state != State.DONE:
        cur = current_step(store, node.id)
        if cur is not None:
            glyph_node, glyph_flow = cur, flow_service.flow_for(cur)
            escalation_text, escalation_target = _dependency_escalation(cur)
            if escalation_text is None and getattr(cur, "role", None) == "human" and cur.needs:
                escalation_text = _park_escalation_text(cur)

    stat_line = _stat_line_item(store, node, children, flow_service, now, pool_halted)

    return HeaderData(
        id=node.id, title=node.title, project=project,
        stat_line=stat_line,
        workflow_text=_workflow_text(flow_service, node),
        glyph=_state_glyph(glyph_node, glyph_flow, pool_running),
        dependency_blocked=bool(glyph_node.blocked_by),
        escalation_text=escalation_text, escalation_target=escalation_target,
    )


def _step_header(store, node, now, project, flow_service, pool_halted, pool_running):
    escalation_text, escalation_target = _dependency_escalation(node)
    if escalation_text is None and getattr(node, "role", None) == "human" and getattr(node, "needs", None):
        escalation_text = _park_escalation_text(node)

    item = store.get_node(node.item)
    flow = flow_service.flow_for(node)
    stat_line = _stat_line_step(store, node, flow_service, now, pool_halted)
    return HeaderData(
        id=node.id, title=item.title, project=project,
        stat_line=stat_line,
        workflow_text=_workflow_text(flow_service, node),
        glyph=_state_glyph(node, flow, pool_running),
        dependency_blocked=bool(node.blocked_by),
        escalation_text=escalation_text, escalation_target=escalation_target,
    )


def _state_glyph(node, flow, pool_running):
    bucket = row_bucket(node, flow, pool_running)
    if bucket == "done":
        return HUMAN_STEP_GLYPH if is_human_step(node) else DONE_GLYPH
    if bucket == "queued":
        return HUMAN_STEP_GLYPH if is_human_step(node) else STATE_GLYPHS["queued"]
    return STATE_GLYPHS[bucket]


def _display_glyph(node, active_frame, flow, pool_running):
    glyph = _state_glyph(node, flow, pool_running)
    if active_frame is not None and row_bucket(node, flow, pool_running) == "active":
        return glyph._replace(glyph=active_frame)
    return glyph


def hierarchy_usage_text(node):
    if node.type != "step":
        return "", ""
    cost = step_cost(node, {})
    if not cost.applicable or not cost.has_run:
        return "", ""
    n = cost.turn_count
    turns_text = "%s turn%s" % (format_tokens(n), "" if n == 1 else "s")
    cost_text = format_usd(cost.cost_usd) if cost.cost_usd else COST_NOT_RECORDED
    return turns_text, cost_text


def hierarchy_time_text(store, node, now):
    if node.type != "step":
        return ""
    if is_human_step(node):
        wait = _gate_wait_seconds(store, node, now)
        return format_elapsed(wait) if wait is not None else ""
    wall_active = _step_wall_active(store, node, now)
    return format_wall_and_active(*wall_active) if wall_active is not None else ""


def _hierarchy_stacked_first_line(
    row, layout, row_budget, active_frame=None, flow_service=None, store=None, now=None,
    pool_running=False,
):
    node = row.node
    glyph = _display_glyph(node, active_frame, _flow_for_bucket(node, flow_service), pool_running)
    icon_cell = Text(glyph.glyph, style=COLOURS[glyph.colour])
    if node.blocked_by:
        icon_cell = icon_cell + Text(
            DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
        )
    icon_field = pad_field(icon_cell, GLYPH_WIDTHS["icon"])
    id_field = pad_atomic_field(node.id, layout.atomic_widths["id"])
    turns_text, cost_text = hierarchy_usage_text(node)
    turns_field = pad_atomic_field(Text(turns_text, style=COLOURS["dim"]), layout.atomic_widths["turns"])
    time_field = pad_atomic_field(
        Text(hierarchy_time_text(store, node, now), style=COLOURS["dim"]), layout.atomic_widths["time"]
    )
    content_so_far = icon_field + id_field + turns_field + time_field
    cost_cell = Text(cost_text, style=COLOURS["dim"]) if cost_text else Text("")
    cost_area = max(0, row_budget - len(content_so_far.plain))
    return content_so_far + pad_field_right(cost_cell, cost_area)


def _hierarchy_label(node, flow_service, multi_pass):
    if node.type != "step":
        return node.title
    if flow_service is None:
        base, phase = node.stage, None
    else:
        base, phase = flow_service.display_for(node) or node.stage, flow_service.phase_for(node)
    n = pass_number(node.pass_id)
    parts = (["pass %d" % n] if multi_pass else []) + ([phase] if phase else [])
    return " · ".join(parts + [base]) if parts else base


def _row_node(rows, row_id):
    return next((r.node for r in rows if r.node.id == row_id), None)


def hierarchy_row_cells(
    row, layout=None, row_budget=None, active_frame=None, flow_service=None, multi_pass=False,
    store=None, now=None, pool_running=False,
):
    node = row.node
    if layout is not None and layout.stacked:
        first_line = _hierarchy_stacked_first_line(
            row, layout, row_budget, active_frame, flow_service, store, now, pool_running
        )
        indent = HIERARCHY_CONTINUATION_BASE_INDENT + row.depth
        label = _hierarchy_label(node, flow_service, multi_pass)
        return (stacked_cell(first_line, indent, label, row_budget),)
    glyph = _display_glyph(node, active_frame, _flow_for_bucket(node, flow_service), pool_running)
    icon_cell = Text(glyph.glyph, style=COLOURS[glyph.colour])
    if node.blocked_by:
        icon_cell = icon_cell + Text(
            DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
        )
    title_cell = ("  " * row.depth) + _hierarchy_label(node, flow_service, multi_pass)
    turns_text, cost_text = hierarchy_usage_text(node)
    turns_cell = Text(turns_text, style=COLOURS["dim"]) if turns_text else ""
    time_text = hierarchy_time_text(store, node, now)
    time_cell = Text(time_text, style=COLOURS["dim"]) if time_text else ""
    cost_cell = Text(cost_text, style=COLOURS["dim"]) if cost_text else ""
    return (icon_cell, node.id, title_cell, turns_cell, time_cell, cost_cell)


def _output_name_text(line):
    suffix = " +%d" % line.older if line.older else ""
    return ("  " if line.is_history else "") + line.title + suffix


def _output_value_style(line):
    return COLOURS["dim"] if line.is_history else COLOURS["cyan"]


def output_row_cells(line, layout=None, row_budget=None):
    name = Text(_output_name_text(line), style=COLOURS["dim"] if line.is_history else COLOURS["text"])
    step = Text(line.step or "", style=COLOURS["dim"])
    pass_cell = Text(line.pass_text, style=COLOURS["dim"])
    if layout is not None and layout.stacked:
        first_line = (
            pad_field(name, layout.atomic_widths["name"])
            + pad_field(step, layout.atomic_widths["step"])
            + pass_cell
        )
        return (
            stacked_cell(
                first_line, OUTPUTS_CONTINUATION_INDENT, line.value, row_budget,
                prose_style=_output_value_style(line),
            ),
        )
    return (name, Text(line.value, style=_output_value_style(line)), step, pass_cell)


def detail_value_is_block(value):
    return bool(value) and ("\n" in value or len(value) > DETAIL_BLOCK_THRESHOLD)


def _stacked_block_cell(key_field, indent, body, row_budget, style):
    cell = Text() + key_field
    for paragraph in body.splitlines() or [""]:
        for line in wrap_continuation(paragraph, row_budget - indent):
            cell = cell + Text("\n" + " " * indent) + Text(line, style=style)
    return cell


def detail_row_cells(field, layout=None, row_budget=None, titles=None):
    key, value = field
    label = _detail_field_label(key)
    style = COLOURS["cyan"] if key in ("pr", "spec-pr", "worktree", "ci-checks") else COLOURS["text"]
    block = detail_value_is_block(value)
    if layout is not None and layout.stacked:
        key_field = pad_field(Text(label, style=COLOURS["dim"]), layout.atomic_widths["key"])
        if block:
            return [(key, (_stacked_block_cell(key_field, DETAIL_CONTINUATION_INDENT, value, row_budget, style),))]
        return [(
            key,
            (stacked_cell(key_field, DETAIL_CONTINUATION_INDENT, value, row_budget, prose_style=style),),
        )]
    if block:
        return [
            (key, (Text(label, style=COLOURS["dim"]), Text(""))),
            (key + DETAIL_BODY_SUFFIX, (Text(""), prose_text(value, titles or {}, style))),
        ]
    return [(key, (Text(label, style=COLOURS["dim"]), Text(value, style=style)))]


def context_section_title(section, inputs_live):
    if section == SECTION_INPUTS and inputs_live:
        return CONTEXT_INPUTS_LIVE_TITLE
    return section.upper()


CONTEXT_SECTIONS = (SECTION_INPUTS, SECTION_OUTPUTS, SECTION_RECORDS)


def context_section_rows(rows):
    return {
        section: [(str(i), r) for i, r in enumerate(rows) if r.section == section]
        for section in CONTEXT_SECTIONS
    }


def context_row_key(row):
    if row.pass_id:
        return "%s (p%d)" % (row.key, pass_number(row.pass_id))
    return row.key


def _stacked_prose_cell(first, indent, prose, row_budget):
    cell = Text() + first
    console = Console(width=max(row_budget - indent, 1))
    for line in prose.split("\n"):
        for wrapped in line.wrap(console, max(row_budget - indent, 1)):
            wrapped.rstrip_end(max(row_budget - indent, 1))
            cell = cell + Text("\n" + " " * indent) + wrapped
    return cell


def context_row_cells(row, layout=None, row_budget=None, titles=None):
    style = COLOURS["cyan"] if row.kind in ("url", "filepath") else COLOURS["text"]
    prose = prose_text(row.value or "", titles or {}, style)
    key = context_row_key(row)
    if layout is not None and layout.stacked:
        first = pad_field(Text(key, style=COLOURS["dim"]), layout.atomic_widths["key"])
        return (_stacked_prose_cell(first, CONTEXT_CONTINUATION_INDENT, prose, row_budget),)
    return (Text(key, style=COLOURS["dim"]), prose)


def _cost_pane_screen_row_budget(pane, columns):
    return pane.screen.size.width - pane.scrollbar_gutter.width - COST_COLUMN_GAP * (columns - 1)


def _cost_row_text(label, value, layout, row_budget):
    if not label:
        return Text(value, style=COLOURS["dim"])
    key_field = pad_field(Text(label, style=COLOURS["dim"]), layout.atomic_widths["key"])
    if layout.stacked:
        return stacked_cell(key_field, COST_CONTINUATION_INDENT, value, row_budget, prose_style=COLOURS["text"])
    return key_field + Text("  ") + Text(value, style=COLOURS["text"])


def toast_text(success, message, kind, value, tab="outputs"):
    base_caption = TOAST_SUB_CAPTION_BY_TAB[tab]
    prefix = TOAST_SUCCESS_PREFIX if success else TOAST_FAILURE_PREFIX
    colour = COLOURS["cyan"] if success else COLOURS["red"]
    main, sub = message, base_caption
    if success and kind == "url":
        sub = "%s - %s" % (base_caption, TOAST_URL_SUB_SUFFIX)
    elif success and kind in ("filepath", "editor"):
        main = "Opened %s" % value
        destination = TOAST_EDITOR_DESTINATION if kind == "editor" else TOAST_FILEPATH_DESTINATION
        sub = "%s - %s" % (destination, base_caption)
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


def escalation_panel_text():
    return Text(ESCALATION_TAG, style="bold %s" % COLOURS["amber"])


def _identity_text(header):
    text = Text(header.glyph.glyph, style=COLOURS[header.glyph.colour])
    if header.dependency_blocked:
        text.append(
            DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph, style=COLOURS[DEPENDENCY_BLOCKED_EXTRA_GLYPH.colour]
        )
    text.append("  ")
    text.append(header.id, style=COLOURS["cyan"])
    if header.project:
        text.append("  %s" % header.project, style=COLOURS["dim"])
    text.append("  ")
    text.append(header.title or "", style=COLOURS["text"])
    return text


CONTEXT_WORKFLOW_GAP = "    "


def _context_text(header, width=None):
    if not header.workflow_text:
        return header.stat_line
    if header.stat_line:
        candidate = header.stat_line + CONTEXT_WORKFLOW_GAP + header.workflow_text
    else:
        candidate = header.workflow_text
    if width is not None and len(candidate) > width:
        return header.stat_line
    return candidate
