from dataclasses import dataclass, replace

from lightcycle.adapters.tui.design_system import DEPENDENCY_BLOCKED_EXTRA_GLYPH, STATE_GLYPHS
from lightcycle.adapters.tui.row_grid import STEP_PHRASE_BUDGET, truncate_field
from lightcycle.application.work.project_of import project_of, short_project_label
from lightcycle.domain.feedback import Duration, format_elapsed
from lightcycle.domain.work import Item


@dataclass(frozen=True)
class PriorityRow:
    id: str
    group: str
    icon: str
    icon_colour: str
    dependency_icon: str
    project: str
    title: str
    step: str
    step_colour: str
    time: str


def _project(store, node):
    owning_id = node.parent or node.id
    return short_project_label(project_of(store, Item(owning_id)))


def _elapsed_text(store, node, now):
    delta = Duration(store.history(node.id)).elapsed_since_claim(now)
    return format_elapsed(delta.total_seconds()) if delta is not None else ""


def _resolved_step(node, flow):
    if not node.step:
        return ""
    phrase = flow.display_of(node.step)
    return truncate_field(phrase, STEP_PHRASE_BUDGET) if phrase else node.step


def _attention_row(store, node, flow):
    kind, _ = node.classify_for_human(flow)
    escalation = kind == "blocked"
    glyph = STATE_GLYPHS["escalation"] if escalation else STATE_GLYPHS["gate"]
    step = _resolved_step(node, flow)
    return PriorityRow(
        id=node.id,
        group="attention",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title=node.title,
        step="stuck · %s" % step if escalation else step,
        step_colour="amber",
        time="",
    )


def _active_row(store, node, now, flow):
    glyph = STATE_GLYPHS["active"]
    return PriorityRow(
        id=node.id,
        group="active",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title=node.title,
        step=_resolved_step(node, flow),
        step_colour="dim",
        time=_elapsed_text(store, node, now),
    )


def _queued_row(store, node, flow):
    glyph = STATE_GLYPHS["queued"]
    if node.blocked_by:
        blocker_id = sorted(node.blocked_by)[0]
        return PriorityRow(
            id=node.id,
            group="queued",
            icon=glyph.glyph,
            icon_colour=glyph.colour,
            dependency_icon=DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph,
            project=_project(store, node),
            title=node.title,
            step="blocked · %s" % blocker_id,
            step_colour="dim",
            time="",
        )
    return PriorityRow(
        id=node.id,
        group="queued",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title=node.title,
        step=_resolved_step(node, flow),
        step_colour="dim",
        time="",
    )


def build_priority_rows(store, lanes, now, flow_service):
    claimed = set()
    attention, active, queued = [], [], []
    runnable = [n for n in lanes["queue"] if not n.blocked_by]
    held = [n for n in lanes["queue"] if n.blocked_by]
    inbox = sorted(
        ((n, flow_service.flow_for(n)) for n in lanes["inbox"]),
        key=lambda pair: pair[0].classify_for_human(pair[1])[0] != "blocked",
    )
    for group_rows, nodes_and_row in (
        (attention, [(n, _attention_row(store, n, flow)) for n, flow in inbox]),
        (active, [(n, _active_row(store, n, now, flow_service.flow_for(n))) for n in lanes["active"]]),
        (queued, [(n, _queued_row(store, n, flow_service.flow_for(n))) for n in runnable]
         + [(n, _queued_row(store, n, flow_service.flow_for(n))) for n in held]),
    ):
        for node, row in nodes_and_row:
            owning_id = node.parent or node.id
            if owning_id in claimed:
                continue
            claimed.add(owning_id)
            owning_node = store.get_node(owning_id)
            group_rows.append(replace(row, id=owning_node.id, title=owning_node.title))
    return attention, active, queued


def assemble_rows(attention_rows, active_rows, queued_rows):
    return attention_rows + active_rows + queued_rows
