from dataclasses import dataclass, replace
from typing import Optional

from lightcycle.domain.flow.hooks import (
    CI_FAILED_CAP,
    CONSECUTIVE,
    FAILURES,
    HOOK_MIN_ARITY,
    PR_FEEDBACK,
    TOTAL,
    graph_caps,
)
from lightcycle.domain.flow.step_def import StepDef
from lightcycle.domain.flow.transition import Escalation, Transition
from lightcycle.domain.work.detail import parse_detail
from lightcycle.domain.workflows.step_config import step_config_keys

GUIDANCE_WORKSPACE = "guidance"
LEGACY_KNOWLEDGE_WORKSPACE = "knowledge"
PROJECT_WORKSPACE = "project"


@dataclass(frozen=True)
class RebaseRetry:
    retry_outcomes: frozenset
    failure_outcome: Optional[str]


def consecutive_outcome_count(history, outcome):
    count = 0
    for s in history:
        count = count + 1 if s.outcome == outcome else 0
    return count


def since_last_firing(history, firing_ids):
    cut = 0
    for i, s in enumerate(history):
        if s.id in firing_ids:
            cut = i + 1
    return list(history[cut:])


def total_outcome_count(history, outcome):
    return sum(1 for s in history if s.outcome == outcome)


def pr_conflict_failures(prior_tips, current_tip, escalated):
    seq = list(prior_tips) + [current_tip]
    pairs = sum(1 for a, b in zip(seq, seq[1:]) if a and b and a == b)
    return escalated + pairs


def outcome_counts(history, outcome, failures=0):
    return {
        TOTAL: total_outcome_count(history, outcome),
        CONSECUTIVE: consecutive_outcome_count(history, outcome),
        FAILURES: failures,
    }


def _limit_of(cap, limit_for):
    if cap.limit is not None:
        return cap.limit
    if cap.limit_key:
        return limit_for(cap.limit_key)
    return None


class Flow:
    def __init__(self, steps, workspace_default="project", disposition=None,
                 workspace_declared=False):
        self._steps = steps
        self._workspace_default = workspace_default
        self._workspace_declared = workspace_declared
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
            if len(occ) >= HOOK_MIN_ARITY[PR_FEEDBACK]:
                stages.add(occ[1])
        for _stage, cap in graph_caps(graph):
            if cap.escalate_stage:
                stages.add(cap.escalate_stage)
        stages.update(graph.nodes.keys())
        stages.update(graph.signals.keys())
        stages.discard(None)

        owner = {}
        escalation = {}
        github_heavy = {}
        always_run = {}
        review = {}
        sends_back = {}
        scripts = {}
        presents = {}
        details = {}
        config_keys = {}
        for stage in stages:
            meta = step_metas.get(graph.file_for(stage))
            if meta is None:
                continue
            escalation[stage] = bool(meta.get("escalation"))
            github_heavy[stage] = str(meta.get("github") or "").strip() == "heavy"
            always_run[stage] = str(meta.get("always-run") or "").strip().lower() == "true"
            review[stage] = str(meta.get("review") or "").strip() or None
            sends_back[stage] = tuple(
                o.strip() for o in str(meta.get("sends-back") or "").split(",") if o.strip())
            declared = meta.get("presents")
            if declared:
                presents[stage] = str(declared).strip()
            parsed_detail = parse_detail(meta.get("detail"))
            if parsed_detail:
                details[stage] = parsed_detail
            try:
                config_keys[stage] = step_config_keys(meta)
            except ValueError:
                config_keys[stage] = ()
            script = meta.get("script")
            if script:
                scripts[stage] = str(script).strip()
            if meta.get("engine") or script:
                owner[stage] = "engine"
            elif meta.get("model"):
                owner[stage] = "agent"
            else:
                owner[stage] = "human"

        step_stages = stages | set(graph.workspaces) | set(graph.phases) | set(graph.display)
        steps = {
            stage: replace(
                StepDef.from_graph(graph, stage),
                owner=owner.get(stage),
                escalation=escalation.get(stage, False),
                github_heavy=github_heavy.get(stage, False),
                always_run=always_run.get(stage, False),
                review=review.get(stage),
                sends_back=sends_back.get(stage, ()),
                script=scripts.get(stage),
                presents=presents.get(stage),
                detail=details.get(stage),
                config_keys=config_keys.get(stage, ()),
            )
            for stage in step_stages
        }
        return cls(steps, graph.workspace, dict(graph.disposition), graph.workspace_declared)

    def step_def(self, stage) -> StepDef:
        return self._steps.get(stage) or StepDef()

    def rebase_retry(self, stage):
        routes = self.step_def(stage).routes
        for name, ci in self._steps.items():
            if ci.ci_failure is None or ci.routes.get(ci.ci_failure) != stage:
                continue
            outcomes = frozenset(o for o, target in routes.items() if target == name)
            if not outcomes:
                continue
            cap = self.step_def(stage).caps.get(CI_FAILED_CAP)
            return RebaseRetry(outcomes, cap.outcome if cap else None)
        return None

    def declared(self, stage):
        return stage in self._steps

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

    def declared_workspace_of(self, stage):
        sd = self.step_def(stage)
        if sd.workspace is not None:
            return sd.workspace
        return self._workspace_default if self._workspace_declared else None

    def _firing_escalation(self, step, outcome, history, limit_for):
        fired = None
        for cap in self.step_def(step).caps.values():
            if cap.escalate_stage is None or outcome != cap.outcome:
                continue
            limit = _limit_of(cap, limit_for)
            if limit is None:
                continue
            count = outcome_counts(history(), outcome)[cap.counting]
            if count < limit:
                continue
            fired = Escalation(cap, count, limit)
        return fired

    def escalated_transition(self, transition, outcome, history, limit_for):
        if transition is None:
            return None
        step = transition.from_stage
        fired = self._firing_escalation(step, outcome, history, limit_for)
        if fired is None:
            return transition
        target = self.step_def(fired.cap.escalate_stage)
        return Transition(
            from_stage=step,
            outcome=outcome,
            to_stage=fired.cap.escalate_stage,
            to_role=target.owner or "human",
            to_terminal=target.owner is None,
            escalation=fired,
        )

    def fired_cap(self, stage, outcome, counts):
        for cap in self.step_def(stage).caps.values():
            if not cap.escalate_outcome or outcome != cap.outcome:
                continue
            if counts[cap.counting] >= cap.limit:
                return cap
        return None

    def escalated_outcome(self, stage, outcome, counts):
        cap = self.fired_cap(stage, outcome, counts)
        return outcome if cap is None else cap.escalate_outcome

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
            from_stage=step,
            outcome=outcome,
            to_stage=target,
            to_role=self.step_def(target).owner or "human",
            to_terminal=self.step_def(target).owner is None,
        )
