"""FlowService: assemble the flow from step files and answer flow questions.

The flow is read from the step markdown (each role's frontmatter) and composed
by core.flow into an owner map (step -> owning role) and a routes map. This
service is the one place that gathers the step metas and exposes the assembled
flow; use cases depend on it rather than re-reading step files.
"""
from the_grid.domain import flow as cflow


class FlowService:

    def __init__(self, fs, store):
        self._fs = fs
        self._store = store

    def role_metas(self):
        return {role: (self._fs.parse_step(role) or {"meta": {}})["meta"]
                for role in self._fs.step_roles()}

    def load_flow(self):
        return cflow.load_flow(self.role_metas())

    def flow_next(self, step, outcome):
        owner, routes = self.load_flow()
        return cflow.flow_next(step, outcome, owner, routes)

    def meta_for_step(self, step):
        owner, _ = self.load_flow()
        role = owner.get(step)
        if not role:
            return {}
        a = self._fs.parse_step(role)
        return a["meta"] if a else {}

    def ready_roles(self):
        return cflow.ready_roles_from_beads(self._store.ready_beads())
