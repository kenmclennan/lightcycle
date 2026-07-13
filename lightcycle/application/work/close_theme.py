from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.resolve_backlog import retire_resolved
from lightcycle.domain.work import State


@dataclass(frozen=True)
class CloseThemeInput:
    theme: str
    reason: str


class CloseThemeUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: CloseThemeInput) -> None:
        children = self._store.children(input.theme)
        open_stories = [c for c in children if c.type == "item" and c.state != State.DONE]
        if open_stories:
            ids = ", ".join(c.id for c in open_stories)
            raise UseCaseError(
                "theme %s has open items: %s - close or abandon them first" % (input.theme, ids)
            )
        self._store.close(input.theme, input.reason)
        retire_resolved(self._store, input.theme)
