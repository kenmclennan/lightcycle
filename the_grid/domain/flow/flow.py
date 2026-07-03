"""Flow: the workflow graph assembled from the step roster (the aggregate root).

The flow is read from the step markdown (each role's frontmatter): a file with
`model` + `step` is an automated agent and owns its step as itself; a file with
`step` but NO `model` is a human step, owned by the literal role "human" (never
spawned, surfaces in tg inbox); a file with no `step` (the driver) owns nothing;
a route target absent from the owner map is a human terminal.
"""
from the_grid.domain.flow.transition import Transition


class Flow:

    def __init__(self, owner, routes, pr_merge, pr_close, pr_rework, epic_close=None,
                 retro_cadence=None, hooks=None):
        self._owner = owner
        self._routes = routes
        self._pr_merge = pr_merge
        self._pr_close = pr_close
        self._pr_rework = pr_rework
        self._epic_close = epic_close or set()
        self._retro_cadence = retro_cadence or set()
        self._hooks = hooks or {}

    @classmethod
    def assemble(cls, role_metas) -> "Flow":
        owner, routes, pr_merge, pr_close, pr_rework, epic_close, retro_cadence, hooks = (
            {}, {}, {}, {}, {}, set(), set(), {})
        for role, meta in role_metas.items():
            meta = meta or {}
            step = meta.get("step")
            if not step:
                continue
            owner[step] = role if meta.get("model") else "human"
            rts = meta.get("routes")
            routes[step] = dict(rts) if isinstance(rts, dict) else {}
            declared = meta.get("on_pr_merge")
            if declared:
                pr_merge[step] = declared
            declared_close = meta.get("on_pr_close")
            if declared_close:
                pr_close[step] = declared_close
            declared_rework = meta.get("on_pr_rework")
            if declared_rework:
                pr_rework[step] = declared_rework
            if meta.get("on_epic_close"):
                epic_close.add(step)
            if meta.get("on_retro_cadence"):
                retro_cadence.add(step)
            for key, val in meta.items():
                if key.startswith("on_") and val:
                    hooks.setdefault(key, set()).add(step)
        return cls(owner, routes, pr_merge, pr_close, pr_rework, epic_close, retro_cadence, hooks)

    def owner_of(self, step):
        return self._owner.get(step)

    def steps(self):
        return sorted(self._owner)

    def outcomes_for(self, step):
        return sorted((self._routes.get(step) or {}).keys())

    def targets_from(self, step):
        return list((self._routes.get(step) or {}).values())

    def pr_merge_outcome(self, step):
        return self._pr_merge.get(step)

    def pr_close_outcome(self, step):
        return self._pr_close.get(step)

    def pr_rework_outcome(self, step):
        return self._pr_rework.get(step)

    def epic_close_steps(self):
        return [(step, self._owner[step]) for step in sorted(self._epic_close) if step in self._owner]

    def retro_cadence_steps(self):
        return [(step, self._owner[step]) for step in sorted(self._retro_cadence) if step in self._owner]

    def hooks(self):
        return {hook: sorted(steps) for hook, steps in sorted(self._hooks.items())}

    def next(self, step, outcome):
        target = (self._routes.get(step) or {}).get(outcome)
        if not target:
            return None
        return Transition(from_step=step, outcome=outcome, to_step=target,
                          to_role=self._owner.get(target, "human"))
