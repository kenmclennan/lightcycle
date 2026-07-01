"""UnblockTask: flip a blocked task back to its agent role so it re-claims."""
from dataclasses import dataclass

from the_grid.application.errors import UseCaseError


@dataclass(frozen=True)
class UnblockInput:
    task: str


@dataclass(frozen=True)
class UnblockResponse:
    role: str


class UnblockTaskUseCase:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: UnblockInput) -> UnblockResponse:
        t = self._store.get_task(input.task)
        role = self._flow.load_flow().owner_of(t.step)
        if not role or role == "human":
            raise UseCaseError(
                "nothing to unblock: step '%s' has no agent owner" % (t.step or "(none)"))
        cur = t.role
        if cur and cur != role:
            self._store.label_remove(input.task, "for:%s" % cur)
        self._store.label_add(input.task, "for:%s" % role)
        self._store.update_status(input.task, "open")
        self._store.assign(input.task, "")
        return UnblockResponse(role=role)
