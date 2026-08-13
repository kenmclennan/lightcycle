from dataclasses import dataclass

from lightcycle.application.work.project_of import project_of
from lightcycle.domain.feedback import Duration
from lightcycle.domain.work import Item

ATTENTION_ICON = "●"
ACTIVE_ICON = "▸"
QUEUED_ICON = "○"


@dataclass(frozen=True)
class PriorityRow:
    id: str
    group: str
    icon: str
    project: str
    title: str
    step: str
    step_attention: bool
    time: str


def format_elapsed(delta):
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return "%ds" % total_seconds
    minutes = total_seconds // 60
    if minutes < 60:
        return "%dm" % minutes
    hours, minutes = divmod(minutes, 60)
    return "%dh %dm" % (hours, minutes)


def _project(store, node):
    owning_id = node.parent or node.id
    return project_of(store, Item(owning_id)) or ""


def _elapsed_text(store, node, now):
    delta = Duration(store.history(node.id)).elapsed_since_claim(now)
    return format_elapsed(delta) if delta is not None else ""


def _row(store, node, group, icon, now):
    return PriorityRow(
        id=node.id,
        group=group,
        icon=icon,
        project=_project(store, node),
        title=node.title,
        step=node.step or "",
        step_attention=group == "attention",
        time=_elapsed_text(store, node, now) if group == "active" else "",
    )


def build_snapshot(store, lanes, now):
    attention = [_row(store, n, "attention", ATTENTION_ICON, now) for n in lanes["inbox"] + lanes["blocked"]]
    active = [_row(store, n, "active", ACTIVE_ICON, now) for n in lanes["active"]]
    queued = [_row(store, n, "queued", QUEUED_ICON, now) for n in lanes["queue"]]
    return attention, active, queued
