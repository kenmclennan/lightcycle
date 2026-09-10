from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class CreateStepInput:
    title: str
    step: str
    parent: str
    workflow: Optional[str] = None
    note: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CreateStepResponse:
    id: str


class CreateStepUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: CreateStepInput) -> CreateStepResponse:
        flow = None
        if input.workflow:
            try:
                selected = self._flow.resolve_selection(input.workflow)
                flow = self._flow.load_flow(selected)
            except (UseCaseError, ValueError) as e:
                raise UseCaseError(str(e))
        elif input.parent:
            try:
                parent = self._store.get_node(input.parent)
            except KeyError:
                raise UseCaseError("unknown parent '%s'" % input.parent)
            flow = self._flow.flow_for(parent)
        if flow is None or not flow.steps():
            raise UseCaseError(
                "no workflow to resolve --step against; pass --workflow <origin>/<name> "
                "or --parent <item pinned to one>"
            )
        role = flow.owner_of(input.step)
        if not role:
            raise UseCaseError(
                "step '%s' is not owned in this workflow; owned steps: %s"
                % (input.step, ", ".join(flow.steps()) or "(none)")
            )
        with self._store.transaction():
            tid = self._store.create_step(
                input.title, step=input.step, role=role, parent=input.parent)
            if input.note:
                self._store.note(tid, " ".join(input.note))
        return CreateStepResponse(id=tid)
