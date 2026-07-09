from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.contracts import StepContract
from lightcycle.domain.work import State


@dataclass(frozen=True)
class ActivateItemInput:
    item: str
    workflow: Optional[str] = None
    theme: Optional[str] = None
    step: Optional[str] = None


@dataclass(frozen=True)
class ActivateItemResponse:
    step: str


class ActivateItemUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: ActivateItemInput) -> ActivateItemResponse:
        node = self._store.get_node(input.item)
        if node.type != "item":
            raise UseCaseError("'%s' is not an item (type=%s)" % (input.item, node.type))
        if node.state != State.BACKLOGGED:
            raise UseCaseError("item '%s' is not a todo (state=%s)" % (input.item, node.state))
        if input.theme is not None:
            self._store.edit_node(input.item, parent=input.theme)
            node = self._store.get_node(input.item)
        workflow = input.workflow or self._flow.workflow_for(node)
        project = self._flow.project_for(node)
        step_name = input.step or self._flow.load_graph(workflow, project).entry
        flow = self._flow.load_flow(workflow, project)
        role = flow.owner_of(step_name)
        if not role:
            raise UseCaseError(
                "step '%s' is not owned in workflow '%s'; owned steps: %s"
                % (step_name, workflow, ", ".join(flow.steps()) or "(none)")
            )
        present = {a.type for a in self._store.item_artifacts(input.item)}
        unmet = StepContract.from_meta(
            self._flow.meta_for_step(step_name, workflow, project)
        ).missing_inputs(present)
        if unmet:
            raise UseCaseError(
                "step '%s' requires %s; attach them before activating"
                % (step_name, ", ".join(sorted(unmet)))
            )
        self._store.edit_node(input.item, workflow=input.workflow)
        step = self._store.create_step(
            "%s: %s" % (step_name, node.title), step=step_name, role=role, parent=input.item
        )
        return ActivateItemResponse(step=step)
