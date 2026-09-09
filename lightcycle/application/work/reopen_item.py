from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work import State


@dataclass(frozen=True)
class ReopenItemInput:
    item: str


@dataclass(frozen=True)
class ReopenItemResponse:
    item: str


class ReopenItemUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: ReopenItemInput) -> ReopenItemResponse:
        node = self._store.get_node(input.item)
        if node.type == "step":
            raise UseCaseError(
                "'%s' is a step; use --state ready to hand it back to its lane" % input.item
            )
        if node.type != "item":
            raise UseCaseError("'%s' is not an item (type=%s)" % (input.item, node.type))
        if node.state != State.DONE:
            raise UseCaseError("'%s' is not closed (state=%s)" % (input.item, node.state))
        self._store.reopen(input.item)
        return ReopenItemResponse(item=input.item)
