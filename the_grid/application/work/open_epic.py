from dataclasses import dataclass
from typing import Optional

from the_grid.application.errors import UseCaseError


@dataclass(frozen=True)
class OpenEpicInput:
    objective: str
    backlog: Optional[str] = None
    project: Optional[str] = None


@dataclass(frozen=True)
class OpenEpicResponse:
    epic: str


class OpenEpicUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: OpenEpicInput) -> OpenEpicResponse:
        if input.backlog:
            try:
                self._store.get_task(input.backlog)
            except KeyError:
                raise UseCaseError("unknown backlog item '%s'" % input.backlog)
        epic = self._store.create_epic(input.objective, project=input.project)
        if input.backlog:
            self._store.add_artifact(epic, "backlog", input.backlog)
        return OpenEpicResponse(epic=epic)
