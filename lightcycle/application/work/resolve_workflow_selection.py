from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class ResolveWorkflowSelectionInput:
    node_id: str
    node_type: str
    selector: str


@dataclass(frozen=True)
class ResolveWorkflowSelectionResponse:
    value: str
    resolved: bool
    shadowed_by: list


class ResolveWorkflowSelectionUseCase:
    def __init__(self, flow, store):
        self._flow = flow
        self._store = store

    def _shadowed_by(self, node_id):
        shadowed = []
        for child in self._store.children(node_id):
            if child.workflow:
                shadowed.append(child.id)
            else:
                shadowed.extend(self._shadowed_by(child.id))
        return shadowed

    def execute(self, input: ResolveWorkflowSelectionInput) -> ResolveWorkflowSelectionResponse:
        shadowed = self._shadowed_by(input.node_id)
        if input.node_type == "theme":
            return ResolveWorkflowSelectionResponse(
                value=input.selector, resolved=False, shadowed_by=shadowed)
        try:
            pin = self._flow.resolve_selection(input.selector)
            self._flow.load_graph(pin)
        except ValueError as e:
            raise UseCaseError(str(e))
        return ResolveWorkflowSelectionResponse(value=pin, resolved=True, shadowed_by=shadowed)
