from dataclasses import dataclass, replace

from lightcycle.adapters.tui.design_system import (
    DEPENDENCY_BLOCKED_EXTRA_GLYPH, HUMAN_STEP_GLYPH, STATE_GLYPHS,
)
from lightcycle.adapters.tui.hub import COST_NOT_RECORDED
from lightcycle.adapters.tui.row_grid import STEP_PHRASE_BUDGET, truncate_field
from lightcycle.application.flow.engine_steps import engine_display_of
from lightcycle.application.work.cost import CostInput, CostUseCase
from lightcycle.application.work.project_of import project_of, short_project_label
from lightcycle.domain.work import is_human_step, item_active_seconds, row_bucket
from lightcycle.render import format_elapsed, format_usd


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
    owning_id = node.parent or node.id
    return short_project_label(project_of(store, owning_id))


def _resolved_step(node, flow):
    if not node.step:
        return ""
    phrase = flow.step_def(node.step).display or engine_display_of(node.step)
    return truncate_field(phrase, STEP_PHRASE_BUDGET) if phrase else node.step


def _attention_row(store, node, flow):
    escalation = row_bucket(node, flow) == "escalation"
    glyph = STATE_GLYPHS["escalation"] if escalation else STATE_GLYPHS["gate"]
    step = _resolved_step(node, flow)
    return PriorityRow(
        id=node.id,
        step_id=node.id,
        group="attention",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title=node.title,
        step="stuck · %s" % step if escalation else step,
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
        title=node.title,
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
            title=node.title,
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
        title=node.title,
        step=_resolved_step(node, flow),
        step_colour="dim",
        cost="",
        time="",
    )


def _rolled_up_cost_text(store, item_id):
    cost = CostUseCase(store).execute(CostInput(node=item_id))
    if cost.turn_count == 0 and not cost.cost_usd:
        return ""
    return format_usd(cost.cost_usd) if cost.cost_usd else COST_NOT_RECORDED


def _rolled_up_time_text(store, item_id):
    total = item_active_seconds(store.children(item_id))
    return format_elapsed(total) if total > 0 else ""


def build_priority_rows(store, lanes, flow_service):
    claimed = set()
    attention, active, queued = [], [], []
    runnable = [n for n in lanes["queue"] if not n.blocked_by]
    held = [n for n in lanes["queue"] if n.blocked_by]
    inbox = sorted(
        ((n, flow_service.flow_for(n)) for n in lanes["inbox"]),
        key=lambda pair: row_bucket(pair[0], pair[1]) != "escalation",
    )
    for group_rows, nodes_and_row in (
        (attention, [(n, _attention_row(store, n, flow)) for n, flow in inbox]),
        (active, [(n, _active_row(store, n, flow_service.flow_for(n))) for n in lanes["active"]]),
        (queued, [(n, _queued_row(store, n, flow_service.flow_for(n))) for n in runnable]
         + [(n, _queued_row(store, n, flow_service.flow_for(n))) for n in held]),
    ):
        for node, row in nodes_and_row:
            owning_id = node.parent or node.id
            if owning_id in claimed:
                continue
            claimed.add(owning_id)
            owning_node = store.get_node(owning_id)
            group_rows.append(replace(
                row, id=owning_node.id, title=owning_node.title,
                cost=_rolled_up_cost_text(store, owning_id),
                time=_rolled_up_time_text(store, owning_id),
            ))
    return attention, active, queued


def assemble_rows(attention_rows, active_rows, queued_rows):
    return attention_rows + active_rows + queued_rows
