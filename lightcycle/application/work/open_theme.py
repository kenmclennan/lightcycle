from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.resolve_backlog import link_resolves


@dataclass(frozen=True)
class OpenThemeInput:
    objective: str
    backlog: Optional[List[str]] = None
    project: Optional[str] = None
    workflow: Optional[str] = None


@dataclass(frozen=True)
class OpenThemeResponse:
    theme: str


class OpenThemeUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: OpenThemeInput) -> OpenThemeResponse:
        theme = self._store.create_theme(
            input.objective, project=input.project, workflow=input.workflow
        )
        if input.backlog:
            link_resolves(self._store, theme, input.backlog)
        return OpenThemeResponse(theme=theme)
