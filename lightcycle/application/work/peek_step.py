from dataclasses import dataclass

from lightcycle.adapters.workflow_source import resolve_agent_for_pin
from lightcycle.application.errors import UseCaseError
from lightcycle.domain.workflows.identity import parse_pin


@dataclass(frozen=True)
class PeekStepInput:
    node_id: str
    role: str


@dataclass(frozen=True)
class PeekStepResponse:
    pin: str
    body: str


class PeekStepUseCase:
    def __init__(self, store, flow, config, workflow_source):
        self._store = store
        self._flow = flow
        self._config = config
        self._workflow_source = workflow_source

    def execute(self, input: PeekStepInput) -> PeekStepResponse:
        node = self._store.get_node(input.node_id)
        frozen_pin = self._flow.workflow_for(node)
        if frozen_pin is None:
            raise UseCaseError("no workflow pin found for %r" % input.node_id)
        origin, name, _sha = parse_pin(frozen_pin)
        try:
            fresh_pin = self._flow.resolve_selection("%s/%s" % (origin, name))
        except ValueError as e:
            raise UseCaseError(str(e))
        parsed = resolve_agent_for_pin(self._config, input.role, fresh_pin)
        if parsed is None:
            raise UseCaseError("no step %r in %s" % (input.role, fresh_pin))
        return PeekStepResponse(pin=fresh_pin, body=parsed["body"])
