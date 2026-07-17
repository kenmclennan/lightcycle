from lightcycle.domain.flow.step_def import CiCap, StepDef
from lightcycle.domain.flow.transition import Transition

SPECS_WORKSPACE = "specs"


def phase_for_workspace(workspace):
    return "spec" if workspace == SPECS_WORKSPACE else "code"


class Flow:
    def __init__(self, steps, workspace_default="project"):
        self._steps = steps
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

        ci_cap = {}
        for occ in graph.hook_occurrences("ci_failed_cap"):
            ci_cap[occ[0]] = CiCap(occ[1], int(occ[2]), occ[3])

        mention_token, review_bot_allowlist = {}, {}
        for occ in graph.hook_occurrences("mention_token"):
            mention_token[occ[0]] = occ[1]
        for occ in graph.hook_occurrences("review_bot_allowlist"):
            review_bot_allowlist[occ[0]] = frozenset(occ[1:])

        step_hooks = {}
        for name, occs in graph.hooks.items():
            for occ in occs:
                if occ:
                    step_hooks.setdefault(occ[0], set()).add("on_" + name)

        workspaces = dict(graph.workspaces)

        steps = {}
        all_stages = (
            set(owner) | set(workspaces) | set(pr_merge) | set(pr_close) | set(pr_feedback)
            | set(pr_conflict) | set(pr_conflict_cap) | set(pr_conflict_escalate)
            | set(mention_token) | set(review_bot_allowlist) | set(ci_cap) | set(step_hooks)
        )
        for stage in all_stages:
            steps[stage] = StepDef(
                owner=owner.get(stage),
                routes=routes.get(stage, {}),
                pr_merge=pr_merge.get(stage),
                pr_close=pr_close.get(stage),
                pr_feedback=pr_feedback.get(stage),
                pr_conflict=pr_conflict.get(stage),
                pr_conflict_cap=pr_conflict_cap.get(stage),
                pr_conflict_escalate=pr_conflict_escalate.get(stage),
                mention_token=mention_token.get(stage),
                review_bot_allowlist=review_bot_allowlist.get(stage, frozenset()),
                ci_cap=ci_cap.get(stage),
                workspace=workspaces.get(stage),
                hooks=frozenset(step_hooks.get(stage, set())),
            )
        return cls(steps, graph.workspace)

    def owner_of(self, step):
        sd = self._steps.get(step)
        return sd.owner if sd else None

    def steps(self):
        return sorted(s for s, sd in self._steps.items() if sd.owner is not None)

    def outcomes_for(self, step):
        sd = self._steps.get(step)
        return sorted((sd.routes if sd else {}).keys())

    def targets_from(self, step):
        sd = self._steps.get(step)
        return [t for t in (sd.routes if sd else {}).values() if t]

    def merge_outcome(self, step):
        sd = self._steps.get(step)
        return sd.pr_merge if sd else None

    def close_outcome(self, step):
        sd = self._steps.get(step)
        return sd.pr_close if sd else None

    def merge_stages(self):
        return sorted(
            s for s, sd in self._steps.items()
            if "on_pr_merge" in sd.hooks or "on_pr_close" in sd.hooks
        )

    def workspace_of(self, stage):
        sd = self._steps.get(stage)
        if sd and sd.workspace is not None:
            return sd.workspace
        return self._workspace_default

    def phase_of(self, step):
        return phase_for_workspace(self.workspace_of(step))

    def pr_feedback_step(self, step):
        sd = self._steps.get(step)
        return sd.pr_feedback if sd else None

    def pr_conflict_outcome(self, step):
        sd = self._steps.get(step)
        return sd.pr_conflict if sd else None

    def pr_conflict_cap(self, step):
        sd = self._steps.get(step)
        return sd.pr_conflict_cap if sd else None

    def pr_conflict_escalate(self, step):
        sd = self._steps.get(step)
        return sd.pr_conflict_escalate if sd else None

    def mention_token(self, step):
        sd = self._steps.get(step)
        return sd.mention_token if sd else None

    def review_bot_allowlist(self, step):
        sd = self._steps.get(step)
        return set(sd.review_bot_allowlist) if sd else set()

    def ci_failed_cap_outcome(self, step):
        sd = self._steps.get(step)
        return sd.ci_cap.outcome if sd and sd.ci_cap else None

    def ci_failed_cap_n(self, step):
        sd = self._steps.get(step)
        return sd.ci_cap.n if sd and sd.ci_cap else None

    def ci_failed_cap_target(self, step):
        sd = self._steps.get(step)
        return sd.ci_cap.target if sd and sd.ci_cap else None

    def effective_transition(self, transition, outcome, prior_count):
        if transition is None:
            return None
        step = transition.from_step
        sd = self._steps.get(step)
        cap = sd.ci_cap if sd else None
        if cap is None or outcome != cap.outcome:
            return transition
        if prior_count < cap.n:
            return transition
        return Transition(
            from_step=step,
            outcome=outcome,
            to_step=cap.target,
            to_role=self.owner_of(cap.target) or "human",
        )

    def pr_conflict_transition(self, step, conflict_outcome, prior_count):
        sd = self._steps.get(step)
        if sd is None:
            return conflict_outcome
        if sd.pr_conflict_cap is None or not sd.pr_conflict_escalate:
            return conflict_outcome
        return sd.pr_conflict_escalate if prior_count >= sd.pr_conflict_cap else conflict_outcome

    def hook_steps(self):
        return [
            (s, sd.owner) for s, sd in sorted(self._steps.items()) if sd.hooks and sd.owner
        ]

    def hooks(self):
        out = {}
        for s, sd in self._steps.items():
            for hook in sd.hooks:
                out.setdefault(hook, []).append(s)
        return {hook: sorted(steps) for hook, steps in sorted(out.items())}

    def next(self, step, outcome):
        sd = self._steps.get(step)
        target = (sd.routes if sd else {}).get(outcome)
        if not target:
            return None
        return Transition(
            from_step=step,
            outcome=outcome,
            to_step=target,
            to_role=self.owner_of(target) or "human",
        )
