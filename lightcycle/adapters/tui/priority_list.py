from dataclasses import dataclass, replace

from lightcycle.adapters.tui.design_system import (
    DEPENDENCY_BLOCKED_EXTRA_GLYPH, HUMAN_STEP_GLYPH, STATE_GLYPHS,
)
from lightcycle.adapters.tui.hub import _item_cost_text
from lightcycle.adapters.tui.row_grid import STEP_PHRASE_BUDGET, truncate_field
from lightcycle.application.flow.engine_steps import engine_display_of
from lightcycle.application.work.behind_reason import behind_reason
from lightcycle.application.work.priority_rows import select_priority_rows
from lightcycle.application.work.project_of import project_of, short_project_label
from lightcycle.domain.work import State, is_human_step, item_active_seconds, row_bucket
from lightcycle.render import format_elapsed


@dataclass(frozen=True)
class PriorityRow:
    id: str
    step_id: str
    group: str
    icon: str
    icon_colour: str
    dependency_icon: str
    project: str
    title: str
    step: str
    step_colour: str
    cost: str
    time: str


def _project(store, node):
    owning_id = getattr(node, "item", None) or node.id
    return short_project_label(project_of(store, owning_id))


def _resolved_step(node, flow):
    if not node.stage:
        return ""
    phrase = flow.step_def(node.stage).display or engine_display_of(node.stage)
    return truncate_field(phrase, STEP_PHRASE_BUDGET) if phrase else node.stage


def _attention_row(store, node, flow):
    escalation = row_bucket(node, flow, True) == "escalation"
    glyph = STATE_GLYPHS["escalation"] if escalation else STATE_GLYPHS["gate"]
    step = _resolved_step(node, flow)
    behind = not escalation and behind_reason(store, node.id) is not None
    return PriorityRow(
        id=node.id,
        step_id=node.id,
        group="attention",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title="",
        step="stuck · %s" % step if escalation else "behind · %s" % step if behind else step,
        step_colour="amber",
        cost="",
        time="",
    )


def _active_row(store, node, flow):
    glyph = STATE_GLYPHS["active"]
    return PriorityRow(
        id=node.id,
        step_id=node.id,
        group="active",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title="",
        step=_resolved_step(node, flow),
        step_colour="dim",
        cost="",
        time="",
    )


def _queued_row(store, node, flow):
    glyph = HUMAN_STEP_GLYPH if is_human_step(node) else STATE_GLYPHS["queued"]
    if node.blocked_by:
        blocker_id = sorted(node.blocked_by)[0]
        return PriorityRow(
            id=node.id,
            step_id=node.id,
            group="queued",
            icon=glyph.glyph,
            icon_colour=glyph.colour,
            dependency_icon=DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph,
            project=_project(store, node),
            title="",
            step="blocked · %s" % blocker_id,
            step_colour="dim",
            cost="",
            time="",
        )
    return PriorityRow(
        id=node.id,
        step_id=node.id,
        group="queued",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title="",
        step=_resolved_step(node, flow),
        step_colour="dim",
        cost="",
        time="",
    )


def _rolled_up_time_text(children):
    total = item_active_seconds(children)
    return format_elapsed(total) if total > 0 else ""


def _open_slice_gates(children):
    return sorted(
        (c for c in children if c.slice > 0 and c.state != State.DONE and is_human_step(c)),
        key=lambda c: c.slice,
    )


def _slice_runs(store, owning):
    pass_record = store.current_pass(owning.id)
    if pass_record is None:
        return {}
    return {r.slice: r for r in store.runs_of(owning.id, pass_record.id) if r.slice > 0}


def _gate_row(gate, run, total, project):
    glyph = STATE_GLYPHS["gate"]
    label = "slice %d/%d" % (gate.slice, total)
    if run is not None and run.slice_name:
        label = "%s %s" % (label, run.slice_name)
    if run is not None and run.pr:
        label = "%s  %s" % (label, run.pr)
    return PriorityRow(
        id=gate.id,
        step_id=gate.id,
        group="attention",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=project,
        title=label,
        step="",
        step_colour="amber",
        cost="",
        time="",
    )


def _rows_for(store, row_builder, selected):
    row = row_builder(store, selected.node, selected.flow)
    children = store.children(selected.owning_node.id)
    gates = (
        _open_slice_gates(children)
        if row.group == "attention" and getattr(selected.node, "slice", 0) > 0
        else []
    )
    row = replace(
        row, id=selected.owning_node.id, title=selected.owning_node.title,
        cost=_item_cost_text(children),
        time=_rolled_up_time_text(children),
    )
    if not gates:
        return [row]
    runs = _slice_runs(store, selected.owning_node)
    total = len(runs) or max(g.slice for g in gates)
    header = replace(row, step="stack of %d slices" % total)
    return [header] + [
        _gate_row(g, runs.get(g.slice), total, row.project) for g in gates
    ]


def _row_for(store, row_builder, selected):
    return _rows_for(store, row_builder, selected)[0]


def build_priority_rows(store, lanes, flow_service, pool_running):
    selection = select_priority_rows(store, lanes, flow_service, pool_running)
    return build_priority_rows_from_selection(store, selection)


def build_priority_rows_from_selection(store, selection):
    return (
        [r for s in selection.attention for r in _rows_for(store, _attention_row, s)],
        [_row_for(store, _active_row, s) for s in selection.active],
        [_row_for(store, _queued_row, s) for s in selection.queued],
    )


def assemble_rows(attention_rows, active_rows, queued_rows):
    return attention_rows + active_rows + queued_rows
