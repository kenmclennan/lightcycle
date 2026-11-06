from dataclasses import dataclass

from lightcycle.application.work.item_outputs import ItemOutputs
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
    def __init__(self, store, flow, stack_layers):
        self._store = store
        self._flow = flow
        self._stack_layers = stack_layers

    def execute(self, input: ShowNodeInput) -> ShowNodeResponse:
        view = self._store.node_view(input.step)
        return ShowNodeResponse(
            view=view, surface=node_read_surface(
                self._store, self._flow, view, ItemOutputs(self._store, self._flow),
                self._stack_layers,
            ),
        )
