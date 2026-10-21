from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.resolve_backlog import link_resolves
from lightcycle.application.work.resolve_shortcode import resolve_shortcode
from lightcycle.application.work.title_guard import validate_title


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
        validate_title(self._config, input.title)
        if not (input.description or "").strip():
            raise UseCaseError(
                "a description is required for an item; a paragraph or two describing "
                "the work, which the entry step reads"
            )
        resolved = resolve_shortcode(self._store, input.project, input.repo)
        project = resolved.project
        repo = input.repo or resolved.identity
        with self._store.transaction():
            tid = self._store.create_item(
                input.title, input.description, project=project,
                workflow=input.workflow, shortcode=resolved.value,
            )
            if repo:
                self._store.add_artifact(tid, "repo", repo)
            if input.backlog:
                link_resolves(self._store, tid, input.backlog)
        return CreateItemResponse(id=tid)
