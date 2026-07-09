from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work import State


@dataclass(frozen=True)
class CloseThemeInput:
    theme: str
    reason: str


class CloseThemeUseCase:
    def __init__(self, store):
        self._store = store

    def _linked_backlog(self, theme):
        for artifact in self._store.item_artifacts(theme):
            if artifact.type == "backlog":
                return artifact.value
        return None

    def execute(self, input: CloseThemeInput) -> None:
        children = self._store.children(input.theme)
        open_stories = [c for c in children if c.type == "item" and c.state != State.DONE]
        if open_stories:
            ids = ", ".join(c.id for c in open_stories)
            raise UseCaseError(
                "theme %s has open items: %s - close or abandon them first" % (input.theme, ids)
            )
        self._store.close(input.theme, input.reason)
        backlog = self._linked_backlog(input.theme)
        if backlog:
            self._store.close(backlog, "resolved by theme close: %s" % input.theme)
