from dataclasses import dataclass

from lightcycle.adapters.tui.design_system import DEPENDENCY_BLOCKED_EXTRA_GLYPH, STATE_GLYPHS
from lightcycle.application.work.project_of import project_of, short_project_label
from lightcycle.domain.feedback import Duration, format_elapsed
from lightcycle.domain.work import Item

GAP_KEY_PREFIX = "__gap-"


def is_gap_key(key):
    return key.startswith(GAP_KEY_PREFIX)


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


def _attention_row(store, node, source_lane):
    glyph = STATE_GLYPHS["needs-attention"]
    if source_lane == "blocked":
        blocker_id = sorted(node.blocked_by)[0]
        return PriorityRow(
            id=node.id,
            group="attention",
            icon=glyph.glyph,
            icon_colour=glyph.colour,
            dependency_icon=DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph,
            project=_project(store, node),
            title=node.title,
            step="blocked · %s" % blocker_id,
            step_colour="amber",
            time="",
        )
    return PriorityRow(
        id=node.id,
        group="attention",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title=node.title,
        step=node.step or "",
        step_colour="amber",
        time="",
    )


def _active_row(store, node, now):
    glyph = STATE_GLYPHS["active"]
    return PriorityRow(
        id=node.id,
        group="active",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title=node.title,
        step=node.step or "",
        step_colour="dim",
        time=_elapsed_text(store, node, now),
    )


def _queued_row(store, node):
    glyph = STATE_GLYPHS["queued"]
    return PriorityRow(
        id=node.id,
        group="queued",
        icon=glyph.glyph,
        icon_colour=glyph.colour,
        dependency_icon="",
        project=_project(store, node),
        title=node.title,
        step=node.step or "",
        step_colour="dim",
        time="",
    )


def build_priority_rows(store, lanes, now):
    attention = [_attention_row(store, n, "inbox") for n in lanes["inbox"]] + [
        _attention_row(store, n, "blocked") for n in lanes["blocked"]
    ]
    active = [_active_row(store, n, now) for n in lanes["active"]]
    queued = [_queued_row(store, n) for n in lanes["queue"]]
    return attention, active, queued


def _gap_row(index):
    return PriorityRow(
        id="%s%d__" % (GAP_KEY_PREFIX, index),
        group="gap",
        icon="",
        icon_colour="",
        dependency_icon="",
        project="",
        title="",
        step="",
        step_colour="",
        time="",
    )


def assemble_rows(attention_rows, active_rows, queued_rows):
    groups = [group for group in (attention_rows, active_rows, queued_rows) if group]
    rows = []
    for index, group in enumerate(groups):
        if index:
            rows.append(_gap_row(index - 1))
        rows.extend(group)
    return rows
