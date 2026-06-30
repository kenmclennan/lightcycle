"""FlowService: assemble the flow from step files and answer flow questions.

The flow is read from the step markdown (each role's frontmatter) and composed by
the domain Flow aggregate. This service is the one place that gathers the step
metas and exposes the assembled flow; use cases depend on it rather than re-reading
step files.
"""
from the_grid.domain.flow import Flow
from the_grid.domain.pool import ready_roles_from_beads


class FlowService:

    def __init__(self, fs, store):
        self._fs = fs
        self._store = store

    def role_metas(self):
        return {role: (self._fs.parse_step(role) or {"meta": {}})["meta"]
                for role in self._fs.step_roles()}

    def load_flow(self):
        return Flow.assemble(self.role_metas())

    def flow_next(self, step, outcome):
        return self.load_flow().next(step, outcome)

    def meta_for_step(self, step):
        role = self.load_flow().owner_of(step)
        if not role:
            return {}
        a = self._fs.parse_step(role)
        return a["meta"] if a else {}

    def ready_roles(self):
        return ready_roles_from_beads(self._store.ready_beads())
