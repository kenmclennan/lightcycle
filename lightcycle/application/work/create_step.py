from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.errors import FieldRefusalError, UseCaseError
from lightcycle.application.flow.passes import PassBook
from lightcycle.application.work.title_guard import validate_title
from lightcycle.domain.work import State, refuse_fields


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
    def __init__(self, store, flow, config):
        self._store = store
        self._flow = flow
        self._config = config

    def execute(self, input: CreateStepInput) -> CreateStepResponse:
        validate_title(self._config, input.title)
        if input.parent:
            try:
                owner = self._store.get_node(input.parent)
            except KeyError:
                owner = None
            if owner is not None and owner.state == State.DONE:
                raise UseCaseError(
                    "item %s is closed; use lc reopen %s to bring it back"
                    % (owner.id, owner.id)
                )
        flow = None
        pin = None
        if input.workflow:
            try:
                selected = self._flow.resolve_selection(input.workflow)
                flow = self._flow.load_flow(selected)
                pin = selected
            except (UseCaseError, ValueError) as e:
                raise UseCaseError(str(e))
        elif input.parent:
            try:
                parent = self._store.get_node(input.parent)
            except KeyError:
                raise UseCaseError("unknown parent '%s'" % input.parent)
            flow = self._flow.flow_for(parent)
            try:
                pin = self._flow.resolve_selection(parent.workflow)
            except (UseCaseError, ValueError) as e:
                raise UseCaseError(str(e))
        if flow is None or not flow.steps():
            raise UseCaseError(
                "no workflow to resolve --step against; pass --workflow <origin>/<name> "
                "or --parent <item pinned to one>"
            )
        role = flow.step_def(input.step).owner
        if not role:
            raise UseCaseError(
                "step '%s' is not owned in this workflow; owned steps: %s"
                % (input.step, ", ".join(flow.steps()) or "(none)")
            )
        if input.title.strip():
            raise FieldRefusalError(refuse_fields("step", ("title",)))
        with self._store.transaction():
            tid = self._store.create_step(stage=input.step, role=role, item=input.parent)
            if input.note:
                self._store.note(tid, " ".join(input.note))
            PassBook(self._store, self._flow).enrol(input.parent, tid, input.step, pin)
        return CreateStepResponse(id=tid)
