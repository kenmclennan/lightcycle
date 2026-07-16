from lightcycle.domain.flow.transition import Transition


class Flow:
    def __init__(
        self,
        owner,
        routes,
        pr_merge,
        pr_close,
        pr_feedback,
        hooks=None,
        pr_conflict=None,
        pr_conflict_cap=None,
        pr_conflict_escalate=None,
        mention_token=None,
        review_bot_allowlist=None,
        ci_failed_cap_outcome=None,
        ci_failed_cap_n=None,
        ci_failed_cap_target=None,
        workspaces=None,
        workspace_default="project",
    ):
        self._owner = owner
        self._routes = routes
        self._pr_merge = pr_merge
        self._pr_close = pr_close
        self._pr_feedback = pr_feedback
        self._hooks = hooks or {}
        self._pr_conflict = pr_conflict or {}
        self._pr_conflict_cap = pr_conflict_cap or {}
        self._pr_conflict_escalate = pr_conflict_escalate or {}
        self._mention_token = mention_token or {}
        self._review_bot_allowlist = review_bot_allowlist or {}
        self._ci_failed_cap_outcome = ci_failed_cap_outcome or {}
        self._ci_failed_cap_n = ci_failed_cap_n or {}
        self._ci_failed_cap_target = ci_failed_cap_target or {}
        self._workspaces = workspaces or {}
        self._workspace_default = workspace_default

    @classmethod
    def from_graph(cls, graph, step_metas) -> "Flow":
        stages = set()
        if graph.entry:
            stages.add(graph.entry)
        for frm, outs in graph.edges.items():
            stages.add(frm)
            stages.update(outs.values())
        for occs in graph.hooks.values():
            for occ in occs:
                if occ:
                    stages.add(occ[0])
        for occ in graph.hook_occurrences("pr_feedback"):
            if len(occ) > 1:
                stages.add(occ[1])
        for occ in graph.hook_occurrences("ci_failed_cap"):
            if len(occ) > 3:
                stages.add(occ[3])
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
        hooks = {}
        outcome_hooks = {
            "pr_merge": pr_merge,
            "pr_close": pr_close,
            "pr_feedback": pr_feedback,
            "pr_conflict": pr_conflict,
            "pr_conflict_escalate": pr_conflict_escalate,
        }
        for name, bucket in outcome_hooks.items():
            for occ in graph.hook_occurrences(name):
                bucket[occ[0]] = occ[1] if len(occ) > 1 else None
        for occ in graph.hook_occurrences("pr_conflict_cap"):
            pr_conflict_cap[occ[0]] = int(occ[1])

        ci_failed_cap_outcome, ci_failed_cap_n, ci_failed_cap_target = {}, {}, {}
        for occ in graph.hook_occurrences("ci_failed_cap"):
            ci_failed_cap_outcome[occ[0]] = occ[1]
            ci_failed_cap_n[occ[0]] = int(occ[2])
            ci_failed_cap_target[occ[0]] = occ[3]

        mention_token, review_bot_allowlist = {}, {}
        for occ in graph.hook_occurrences("mention_token"):
            mention_token[occ[0]] = occ[1]
        for occ in graph.hook_occurrences("review_bot_allowlist"):
            review_bot_allowlist[occ[0]] = set(occ[1:])

        for name, occs in graph.hooks.items():
            for occ in occs:
                if occ:
                    hooks.setdefault("on_" + name, set()).add(occ[0])

        return cls(owner, routes, pr_merge, pr_close, pr_feedback, hooks,
                   pr_conflict, pr_conflict_cap, pr_conflict_escalate,
                   mention_token, review_bot_allowlist,
                   ci_failed_cap_outcome, ci_failed_cap_n, ci_failed_cap_target,
                   dict(graph.workspaces), graph.workspace)

    def owner_of(self, step):
        return self._owner.get(step)

    def steps(self):
        return sorted(self._owner)

    def outcomes_for(self, step):
        return sorted((self._routes.get(step) or {}).keys())

    def targets_from(self, step):
        return [t for t in (self._routes.get(step) or {}).values() if t]

    def merge_outcome(self, step):
        return self._pr_merge.get(step)

    def close_outcome(self, step):
        return self._pr_close.get(step)

    def merge_stages(self):
        return sorted(set(self._pr_merge) | set(self._pr_close))

    def workspace_of(self, stage):
        return self._workspaces.get(stage, self._workspace_default)

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

    def ci_failed_cap_outcome(self, step):
        return self._ci_failed_cap_outcome.get(step)

    def ci_failed_cap_n(self, step):
        return self._ci_failed_cap_n.get(step)

    def ci_failed_cap_target(self, step):
        return self._ci_failed_cap_target.get(step)

    def effective_transition(self, transition, outcome, prior_count):
        if transition is None:
            return None
        step = transition.from_step
        cap_outcome = self._ci_failed_cap_outcome.get(step)
        if cap_outcome is None or outcome != cap_outcome:
            return transition
        cap_n = self._ci_failed_cap_n.get(step)
        cap_target = self._ci_failed_cap_target.get(step)
        if cap_n is None or not cap_target:
            return transition
        if prior_count < cap_n:
            return transition
        return Transition(
            from_step=step,
            outcome=outcome,
            to_step=cap_target,
            to_role=self.owner_of(cap_target) or "human",
        )

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
