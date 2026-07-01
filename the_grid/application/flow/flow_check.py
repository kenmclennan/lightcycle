"""FlowCheck: assemble and analyze the flow (steps, routes, contracts, composition)."""
from dataclasses import dataclass
from typing import Dict

from the_grid.domain.contracts import FlowContracts
from the_grid.domain.flow import Flow


@dataclass(frozen=True)
class FlowCheckInput:
    pass


@dataclass(frozen=True)
class FlowCheckResponse:
    owner: Dict[str, str]
    routes: Dict[str, Dict[str, str]]
    analysis: dict


class FlowCheckUseCase:

    def __init__(self, flow):
        self._flow = flow

    def execute(self, input: FlowCheckInput) -> FlowCheckResponse:
        role_metas = self._flow.role_metas()
        flow = Flow.assemble(role_metas)
        steps = flow.steps()
        owner = {s: flow.owner_of(s) for s in steps}
        routes = {s: {o: flow.next(s, o).to_step for o in flow.outcomes_for(s)} for s in steps}
        return FlowCheckResponse(owner=owner, routes=routes,
                                 analysis=FlowContracts(flow, role_metas).as_dict())
