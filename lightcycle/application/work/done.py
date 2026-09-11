import datetime
from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.backlog import ProjectCount
from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.application.work.item_filter import project_matches, text_matches
from lightcycle.application.work.project_of import project_of
from lightcycle.domain.work import ProjectIdentity, State, node_id_key, parse_timestamp

_MIN_TIMESTAMP = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


@dataclass(frozen=True)
class DoneInput:
    project: Optional[str] = None
    text: Optional[str] = None


@dataclass(frozen=True)
class DoneResponse:
    rows: List[HumanNodeRow]


@dataclass(frozen=True)
class DoneCountsResponse:
    projects: List[ProjectCount]
    unscoped: int
    total: int


class DoneUseCase:
    def __init__(self, store):
        self._store = store
        self._closed_items_cache = None

    def execute(self, input: DoneInput) -> DoneResponse:
        items = self._closed_items()
        items = [t for t in items if project_matches(self._store, t, input.project)]
        items = [t for t in items if text_matches(self._store, t, input.text)]
        items.sort(
            key=lambda t: (parse_timestamp(t.closed_at) or _MIN_TIMESTAMP, node_id_key(t.id)),
            reverse=True,
        )
        rows = [
            HumanNodeRow(
                kind="done", outcomes=[], step=t,
                project=project_of(self._store, t),
                description=t.description, artifacts=t.artifacts,
            )
            for t in items
        ]
        return DoneResponse(rows=rows)

    def counts(self) -> DoneCountsResponse:
        items = self._closed_items()
        projects = [
            ProjectCount(
                project=ProjectIdentity.short_name(p.identity),
                count=sum(
                    1 for t in items
                    if project_matches(self._store, t, ProjectIdentity.short_name(p.identity))
                ),
            )
            for p in self._store.list_projects()
        ]
        unscoped = sum(1 for t in items if project_of(self._store, t) is None)
        return DoneCountsResponse(projects=projects, unscoped=unscoped, total=len(items))

    def _closed_items(self):
        if self._closed_items_cache is None:
            self._closed_items_cache = [
                n for n in self._store.all_nodes_including_done()
                if n.type == "item" and n.state == State.DONE
            ]
        return self._closed_items_cache
