from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.work.resolve_backlog import link_resolves
from lightcycle.application.work.resolve_shortcode import resolve_shortcode


@dataclass(frozen=True)
class CreateItemInput:
    title: str
    description: str
    project: Optional[str] = None
    workflow: Optional[str] = None
    repo: Optional[str] = None
    backlog: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CreateItemResponse:
    id: str


class CreateItemUseCase:
    def __init__(self, store, config):
        self._store = store
        self._config = config

    def execute(self, input: CreateItemInput) -> CreateItemResponse:
        resolved = resolve_shortcode(self._store, self._config, input.project)
        with self._store.transaction():
            tid = self._store.create_item(
                input.title, input.description, project=input.project,
                workflow=input.workflow, shortcode=resolved.value,
            )
            if input.repo:
                self._store.add_artifact(tid, "repo", input.repo)
            if input.backlog:
                link_resolves(self._store, tid, input.backlog)
        return CreateItemResponse(id=tid)
