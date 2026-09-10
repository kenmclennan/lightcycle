from dataclasses import replace

from lightcycle.domain.flow.hooks import CI_FAILED_CAP, PR_FEEDBACK
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.flow.transition import Transition

SPECS_WORKSPACE = "specs"
PROJECT_WORKSPACE = "project"


def consecutive_outcome_count(history, outcome):
    count = 0
    for s in history:
        count = count + 1 if s.outcome == outcome else 0
    return count


def total_outcome_count(history, outcome):
    return sum(1 for s in history if s.outcome == outcome)


class Flow:
    def __init__(self, steps, workspace_default="project", disposition=None):
        self._steps = steps
        self._workspace_default = workspace_default
        self._disposition = disposition or {}

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
        for occ in graph.hook_occurrences(PR_FEEDBACK):
            if len(occ) > 1:
                stages.add(occ[1])
        for occ in graph.hook_occurrences(CI_FAILED_CAP):
            if len(occ) > 3:
                stages.add(occ[3])
        stages.update(graph.nodes.keys())
        stages.update(graph.signals.keys())

        owner = {}
        for stage in stages:
            meta = step_metas.get(graph.file_for(stage))
            if meta is None:
                continue
            owner[stage] = "agent" if meta.get("model") else "human"

        step_stages = stages | set(graph.workspaces) | set(graph.phases) | set(graph.display)
        steps = {
            stage: replace(StepDef.from_graph(graph, stage), owner=owner.get(stage))
            for stage in step_stages
        }
        return cls(steps, graph.workspace, dict(graph.disposition))

    def step_def(self, stage) -> StepDef:
        return self._steps.get(stage) or StepDef()

    def steps(self):
        return sorted(s for s, sd in self._steps.items() if sd.owner is not None)

    def merge_stages(self):
        return sorted(
            s for s, sd in self._steps.items()
            if "on_pr_merge" in sd.hooks or "on_pr_close" in sd.hooks
        )

    def workspace_of(self, stage):
        sd = self.step_def(stage)
        return sd.workspace if sd.workspace is not None else self._workspace_default

    def effective_transition(self, transition, outcome, prior_count):
        if transition is None:
            return None
        step = transition.from_step
        cap = self.step_def(step).ci_cap
        if cap is None or outcome != cap.outcome:
            return transition
        if prior_count < cap.n:
            return transition
        return Transition(
            from_step=step,
            outcome=outcome,
            to_step=cap.target,
            to_role=self.step_def(cap.target).owner or "human",
            to_terminal=self.step_def(cap.target).owner is None,
        )

    def pr_conflict_transition(self, step, conflict_outcome, prior_count):
        sd = self.step_def(step)
        if sd.pr_conflict_cap is None or not sd.pr_conflict_escalate:
            return conflict_outcome
        return sd.pr_conflict_escalate if prior_count >= sd.pr_conflict_cap else conflict_outcome

    def hook_steps(self):
        return [s for s, sd in sorted(self._steps.items()) if sd.hooks and sd.owner]

    def hooks(self):
        out = {}
        for s, sd in self._steps.items():
            for hook in sd.hooks:
                out.setdefault(hook, []).append(s)
        return {hook: sorted(steps) for hook, steps in sorted(out.items())}

    def disposition_for(self, outcome):
        return self._disposition.get(outcome)

    def next(self, step, outcome):
        target = self.step_def(step).routes.get(outcome)
        if not target:
            return None
        return Transition(
            from_step=step,
            outcome=outcome,
            to_step=target,
            to_role=self.step_def(target).owner or "human",
            to_terminal=self.step_def(target).owner is None,
        )
