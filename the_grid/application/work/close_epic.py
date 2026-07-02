"""CloseEpic: close an epic only when all its child stories are already closed."""
from dataclasses import dataclass

from the_grid.application.errors import UseCaseError


@dataclass(frozen=True)
class CloseEpicInput:
    epic: str
    reason: str


class CloseEpicUseCase:

    def __init__(self, store):
        self._store = store

    def execute(self, input: CloseEpicInput) -> None:
        children = self._store.children(input.epic)
        open_stories = [c for c in children if c.type == "story" and c.status != "done"]
        if open_stories:
            ids = ", ".join(c.id for c in open_stories)
            raise UseCaseError(
                "epic %s has open stories: %s - close or abandon them first"
                % (input.epic, ids)
            )
        self._store.close(input.epic, input.reason)
