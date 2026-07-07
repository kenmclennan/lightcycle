from dataclasses import dataclass

from lightcycle.domain.work import NodeView


@dataclass(frozen=True)
class ShowNodeInput:
    step: str


@dataclass(frozen=True)
class ShowNodeResponse:
    view: NodeView


class ShowNodeUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: ShowNodeInput) -> ShowNodeResponse:
        return ShowNodeResponse(view=self._store.node_view(input.step))
