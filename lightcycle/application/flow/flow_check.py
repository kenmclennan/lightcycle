from dataclasses import dataclass
from typing import Dict

from lightcycle.domain.contracts import FlowContracts
from lightcycle.domain.flow import Flow


@dataclass(frozen=True)
class FlowCheckInput:
    pass


@dataclass(frozen=True)
class FlowCheckResponse:
    owner: Dict[str, str]
    routes: Dict[str, Dict[str, str]]
    analysis: dict
    hooks: Dict[str, list]


class FlowCheckUseCase:
    def __init__(self, flow):
        self._flow = flow

    def execute(self, input: FlowCheckInput) -> FlowCheckResponse:
        role_metas = self._flow.role_metas()
        graph = self._flow.load_graph()
        flow = Flow.from_graph(graph, role_metas)
        steps = flow.steps()
        owner = {s: flow.owner_of(s) for s in steps}
        routes = {s: {o: flow.next(s, o).to_step for o in flow.outcomes_for(s)} for s in steps}
        return FlowCheckResponse(
            owner=owner,
            routes=routes,
            analysis=FlowContracts(flow, graph, role_metas).as_dict(),
            hooks=flow.hooks(),
        )
