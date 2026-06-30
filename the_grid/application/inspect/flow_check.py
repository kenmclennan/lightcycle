"""FlowCheck: assemble and analyze the flow (steps, routes, contracts, composition)."""
from the_grid.domain.contracts import FlowContracts
from the_grid.domain.flow import Flow


class FlowCheck:

    def __init__(self, flow):
        self._flow = flow

    def execute(self):
        role_metas = self._flow.role_metas()
        flow = Flow.assemble(role_metas)
        analysis = FlowContracts(flow, role_metas).as_dict()
        return {"owner": flow.owner_map(), "routes": flow.routes_map(), "analysis": analysis}
