from dataclasses import dataclass

from lightcycle.adapters.tui.hub import _item_cost_text, _item_wall_active
from lightcycle.application.work.project_of import short_project_label, short_repo_label
from lightcycle.render import format_wall_and_active


@dataclass(frozen=True)
class DoneRow:
    id: str
    project: str
    repo: str
    title: str
    cost: str
    time: str


def _cost_and_time_text(store, item, cache, now):
    cached = cache.get(item.id)
    if cached is not None and cached[0] == item.closed_at:
        return cached[1], cached[2]
    children = store.children(item.id)
    cost_text = _item_cost_text(children)
    wall_active = _item_wall_active(store, item, children, now)
    time_text = format_wall_and_active(*wall_active) if wall_active is not None else ""
    cache[item.id] = (item.closed_at, cost_text, time_text)
    return cost_text, time_text


def build_done_rows(store, human_node_rows, now, cache):
    rows = []
    for r in human_node_rows:
        cost_text, time_text = _cost_and_time_text(store, r.step, cache, now)
        rows.append(DoneRow(
            id=r.step.id, project=short_project_label(r.project),
            repo=short_repo_label(r.repo), title=r.step.title,
            cost=cost_text, time=time_text,
        ))
    return rows
