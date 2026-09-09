from dataclasses import dataclass

from lightcycle.application.work.node_read_surface import node_read_surface
from lightcycle.domain.work import NodeView


@dataclass(frozen=True)
class ShowNodeInput:
    step: str


@dataclass(frozen=True)
class ShowNodeResponse:
    view: NodeView
    surface: dict

    def as_dict(self) -> dict:
        return self.surface


class ShowNodeUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: ShowNodeInput) -> ShowNodeResponse:
        view = self._store.node_view(input.step)
        return ShowNodeResponse(view=view, surface=node_read_surface(self._store, self._flow, view))
