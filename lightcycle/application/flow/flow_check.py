from dataclasses import dataclass
from typing import Dict, Optional

from lightcycle.domain.contracts import FlowContracts
from lightcycle.domain.flow import Flow


@dataclass(frozen=True)
class FlowCheckInput:
    workflow: Optional[str] = None


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
        role_metas = self._flow.role_metas(input.workflow)
        graph = self._flow.load_graph(input.workflow)
        flow = Flow.from_graph(graph, role_metas)
        steps = flow.steps()
        owner = {s: flow.owner_of(s) for s in steps}
        routes = {
            s: {
                o: transition.to_step
                for o in flow.outcomes_for(s)
                if (transition := flow.next(s, o)) is not None
            }
            for s in steps
        }
        return FlowCheckResponse(
            owner=owner,
            routes=routes,
            analysis=FlowContracts(flow, graph, role_metas).as_dict(),
            hooks=flow.hooks(),
        )
