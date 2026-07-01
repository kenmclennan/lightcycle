"""Flow: the workflow graph assembled from the step roster (the aggregate root).

The flow is read from the step markdown (each role's frontmatter): a file with
`model` + `step` is an automated agent and owns its step as itself; a file with
`step` but NO `model` is a human step, owned by the literal role "human" (never
spawned, surfaces in tg inbox); a file with no `step` (the driver) owns nothing;
a route target absent from the owner map is a human terminal.
"""
from the_grid.domain.flow.transition import Transition


class Flow:

    def __init__(self, owner, routes):
        self._owner = owner
        self._routes = routes

    @classmethod
    def assemble(cls, role_metas) -> "Flow":
        owner, routes = {}, {}
        for role, meta in role_metas.items():
            meta = meta or {}
            step = meta.get("step")
            if not step:
                continue
            owner[step] = role if meta.get("model") else "human"
            rts = meta.get("routes")
            routes[step] = dict(rts) if isinstance(rts, dict) else {}
        return cls(owner, routes)

    def owner_of(self, step):
        return self._owner.get(step)

    def steps(self):
        return sorted(self._owner)

    def outcomes_for(self, step):
        return sorted((self._routes.get(step) or {}).keys())

    def targets_from(self, step):
        return list((self._routes.get(step) or {}).values())

    def next(self, step, outcome):
        target = (self._routes.get(step) or {}).get(outcome)
        if not target:
            return None
        return Transition(from_step=step, outcome=outcome, to_step=target,
                          to_role=self._owner.get(target, "human"))
