from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class OpenThemeInput:
    objective: str
    backlog: Optional[str] = None
    project: Optional[str] = None
    workflow: Optional[str] = None


@dataclass(frozen=True)
class OpenThemeResponse:
    theme: str


class OpenThemeUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: OpenThemeInput) -> OpenThemeResponse:
        if input.backlog:
            try:
                self._store.get_node(input.backlog)
            except KeyError:
                raise UseCaseError("unknown backlog item '%s'" % input.backlog)
        theme = self._store.create_theme(
            input.objective, project=input.project, workflow=input.workflow
        )
        if input.backlog:
            self._store.add_artifact(theme, "backlog", input.backlog)
        return OpenThemeResponse(theme=theme)
