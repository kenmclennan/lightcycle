"""FlowCheck: assemble and analyze the flow (steps, routes, contracts, composition)."""
from the_grid.domain import contracts as ccontracts
from the_grid.domain import flow as cflow


class FlowCheck:

    def __init__(self, flow):
        self._flow = flow

    def execute(self):
        role_metas = self._flow.role_metas()
        owner, routes = cflow.load_flow(role_metas)
        analysis = ccontracts.analyze_flow(owner, routes, role_metas)
        return {"owner": owner, "routes": routes, "analysis": analysis}
