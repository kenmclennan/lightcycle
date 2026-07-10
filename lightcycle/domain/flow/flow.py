from lightcycle.domain.flow.transition import Transition


class Flow:
    def __init__(
        self,
        owner,
        routes,
        pr_merge,
        pr_close,
        pr_feedback,
        retro_cadence=None,
        hooks=None,
        pr_conflict=None,
        pr_conflict_cap=None,
        pr_conflict_escalate=None,
        mention_token=None,
        review_bot_allowlist=None,
    ):
        self._owner = owner
        self._routes = routes
        self._pr_merge = pr_merge
        self._pr_close = pr_close
        self._pr_feedback = pr_feedback
        self._retro_cadence = retro_cadence or set()
        self._hooks = hooks or {}
        self._pr_conflict = pr_conflict or {}
        self._pr_conflict_cap = pr_conflict_cap or {}
        self._pr_conflict_escalate = pr_conflict_escalate or {}
        self._mention_token = mention_token or {}
        self._review_bot_allowlist = review_bot_allowlist or {}

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
        if graph.hook_stage("pr_feedback"):
            stages.add(graph.hook_value("pr_feedback"))
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

        pr_merge, pr_close, pr_feedback = {}, {}, {}
        pr_conflict, pr_conflict_cap, pr_conflict_escalate = {}, {}, {}
        retro_cadence, hooks = set(), {}
        outcome_hooks = {
            "pr_merge": pr_merge,
            "pr_close": pr_close,
            "pr_feedback": pr_feedback,
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
        if graph.hook_stage("retro_cadence"):
            retro_cadence.add(graph.hook_stage("retro_cadence"))

        mention_token, review_bot_allowlist = {}, {}
        mention_stage = graph.hook_stage("mention_token")
        if mention_stage:
            mention_token[mention_stage] = graph.hook_value("mention_token")
        allowlist_stage = graph.hook_stage("review_bot_allowlist")
        if allowlist_stage:
            review_bot_allowlist[allowlist_stage] = set(
                graph.hooks["review_bot_allowlist"][1:]
            )

        for name, toks in graph.hooks.items():
            if toks:
                hooks.setdefault("on_" + name, set()).add(toks[0])

        return cls(owner, routes, pr_merge, pr_close, pr_feedback, retro_cadence, hooks,
                   pr_conflict, pr_conflict_cap, pr_conflict_escalate,
                   mention_token, review_bot_allowlist)

    def owner_of(self, step):
        return self._owner.get(step)

    def steps(self):
        return sorted(self._owner)

    def outcomes_for(self, step):
        return sorted((self._routes.get(step) or {}).keys())

    def targets_from(self, step):
        return [t for t in (self._routes.get(step) or {}).values() if t]

    def terminal_merge_outcome(self):
        return next(iter(self._pr_merge.values()), None)

    def terminal_close_outcome(self):
        return next(iter(self._pr_close.values()), None)

    def pr_feedback_step(self, step):
        return self._pr_feedback.get(step)

    def pr_conflict_outcome(self, step):
        return self._pr_conflict.get(step)

    def pr_conflict_cap(self, step):
        return self._pr_conflict_cap.get(step)

    def pr_conflict_escalate(self, step):
        return self._pr_conflict_escalate.get(step)

    def mention_token(self, step):
        return self._mention_token.get(step)

    def review_bot_allowlist(self, step):
        return self._review_bot_allowlist.get(step) or set()


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
