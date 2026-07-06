from the_grid.domain.flow.transition import Transition


class Flow:
    def __init__(
        self,
        owner,
        routes,
        pr_merge,
        pr_close,
        pr_rework,
        epic_close=None,
        retro_cadence=None,
        hooks=None,
        pr_conflict=None,
        pr_conflict_cap=None,
        pr_conflict_escalate=None,
    ):
        self._owner = owner
        self._routes = routes
        self._pr_merge = pr_merge
        self._pr_close = pr_close
        self._pr_rework = pr_rework
        self._epic_close = epic_close or set()
        self._retro_cadence = retro_cadence or set()
        self._hooks = hooks or {}
        self._pr_conflict = pr_conflict or {}
        self._pr_conflict_cap = pr_conflict_cap or {}
        self._pr_conflict_escalate = pr_conflict_escalate or {}

    @classmethod
    def from_graph(cls, graph, step_metas) -> "Flow":
        stages = set()
        if graph.entry:
            stages.add(graph.entry)
        for frm, outs in graph.edges.items():
            stages.add(frm)
            stages.update(outs.values())
        for toks in graph.hooks.values():
            if toks:
                stages.add(toks[0])
        stages.update(graph.nodes.keys())
        stages.update(graph.signals.keys())

        owner, routes = {}, {}
        for stage in stages:
            meta = step_metas.get(graph.file_for(stage))
            if meta is None:
                continue
            owner[stage] = graph.file_for(stage) if meta.get("model") else "human"
        for stage in owner:
            routes[stage] = dict(graph.edges.get(stage) or {})

        pr_merge, pr_close, pr_rework = {}, {}, {}
        pr_conflict, pr_conflict_cap, pr_conflict_escalate = {}, {}, {}
        epic_close, retro_cadence, hooks = set(), set(), {}
        outcome_hooks = {
            "pr_merge": pr_merge,
            "pr_close": pr_close,
            "pr_rework": pr_rework,
            "pr_conflict": pr_conflict,
            "pr_conflict_escalate": pr_conflict_escalate,
        }
        for name, bucket in outcome_hooks.items():
            stage = graph.hook_stage(name)
            if stage:
                bucket[stage] = graph.hook_value(name)
        cap_stage = graph.hook_stage("pr_conflict_cap")
        if cap_stage:
            pr_conflict_cap[cap_stage] = int(graph.hook_value("pr_conflict_cap"))
        if graph.hook_stage("epic_close"):
            epic_close.add(graph.hook_stage("epic_close"))
        if graph.hook_stage("retro_cadence"):
            retro_cadence.add(graph.hook_stage("retro_cadence"))
        for name, toks in graph.hooks.items():
            if toks:
                hooks.setdefault("on_" + name, set()).add(toks[0])

        return cls(owner, routes, pr_merge, pr_close, pr_rework, epic_close, retro_cadence, hooks,
                   pr_conflict, pr_conflict_cap, pr_conflict_escalate)

    def owner_of(self, step):
        return self._owner.get(step)

    def steps(self):
        return sorted(self._owner)

    def outcomes_for(self, step):
        return sorted((self._routes.get(step) or {}).keys())

    def targets_from(self, step):
        return list((self._routes.get(step) or {}).values())

    def terminal_merge_outcome(self):
        return next(iter(self._pr_merge.values()), None)

    def terminal_close_outcome(self):
        return next(iter(self._pr_close.values()), None)

    def pr_rework_outcome(self, step):
        return self._pr_rework.get(step)

    def pr_conflict_outcome(self, step):
        return self._pr_conflict.get(step)

    def pr_conflict_cap(self, step):
        return self._pr_conflict_cap.get(step)

    def pr_conflict_escalate(self, step):
        return self._pr_conflict_escalate.get(step)

    def epic_close_steps(self):
        return [
            (step, self._owner[step]) for step in sorted(self._epic_close) if step in self._owner
        ]

    def retro_cadence_steps(self):
        return [(step, self._owner[step]) for step in sorted(self._retro_cadence) if step in self._owner]

    def hook_steps(self):
        steps = set()
        for hook_steps in self._hooks.values():
            steps.update(hook_steps)
        return [(step, self._owner[step]) for step in sorted(steps) if step in self._owner]

    def hooks(self):
        return {hook: sorted(steps) for hook, steps in sorted(self._hooks.items())}

    def next(self, step, outcome):
        target = (self._routes.get(step) or {}).get(outcome)
        if not target:
            return None
        return Transition(
            from_step=step,
            outcome=outcome,
            to_step=target,
            to_role=self._owner.get(target, "human"),
        )
