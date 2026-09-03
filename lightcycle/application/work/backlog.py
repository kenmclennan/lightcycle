from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.application.work.project_of import project_of
from lightcycle.domain.work import State


def _project_matches(store, item, short_ref):
    if short_ref is None:
        return True
    raw = project_of(store, item)
    return raw is not None and raw.rsplit("/", 1)[-1] == short_ref


@dataclass(frozen=True)
class BacklogInput:
    n: Optional[int] = None
    project: Optional[str] = None


@dataclass(frozen=True)
class BacklogResponse:
    rows: List[HumanNodeRow]


@dataclass(frozen=True)
class ProjectCount:
    project: str
    count: int


@dataclass(frozen=True)
class BacklogCountsResponse:
    projects: List[ProjectCount]
    unscoped: int
    total: int


class BacklogUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow
        self._backlogged_items_cache = None

    def execute(self, input: BacklogInput) -> BacklogResponse:
        items = self._backlogged_items()
        items = [t for t in items if _project_matches(self._store, t, input.project)]
        items.sort(key=lambda t: t.id)
        if input.n is not None:
            items = items[:input.n]
        rows = [
            HumanNodeRow(
                kind="todo", outcomes=[], step=t,
                project=project_of(self._store, t),
                description=t.description, artifacts=t.artifacts,
            )
            for t in items
        ]
        return BacklogResponse(rows=rows)

    def counts(self) -> BacklogCountsResponse:
        items = self._backlogged_items()
        projects = [
            ProjectCount(
                project=p.identity.rsplit("/", 1)[-1],
                count=sum(
                    1 for t in items
                    if _project_matches(self._store, t, p.identity.rsplit("/", 1)[-1])
                ),
            )
            for p in self._store.list_projects()
        ]
        unscoped = sum(1 for t in items if project_of(self._store, t) is None)
        return BacklogCountsResponse(projects=projects, unscoped=unscoped, total=len(items))

    def _backlogged_items(self):
        if self._backlogged_items_cache is None:
            self._backlogged_items_cache = [
                n for n in self._store.all_nodes()
                if n.type == "item" and n.state == State.BACKLOGGED
            ]
        return self._backlogged_items_cache
