from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class ResolveWorkflowSelectionInput:
    node_type: str
    selector: str


@dataclass(frozen=True)
class ResolveWorkflowSelectionResponse:
    value: str
    resolved: bool


class ResolveWorkflowSelectionUseCase:
    def __init__(self, flow):
        self._flow = flow

    def execute(self, input: ResolveWorkflowSelectionInput) -> ResolveWorkflowSelectionResponse:
        if input.node_type == "theme":
            return ResolveWorkflowSelectionResponse(value=input.selector, resolved=False)
        try:
            pin = self._flow.resolve_selection(input.selector)
            self._flow.load_graph(pin)
        except ValueError as e:
            raise UseCaseError(str(e))
        return ResolveWorkflowSelectionResponse(value=pin, resolved=True)
