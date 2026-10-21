from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Optional, Tuple

from lightcycle.domain.flow.hooks import (
    CI_FAILED_CAP,
    CI_FAILURE,
    CI_SUCCESS,
    HOOK_MIN_ARITY,
    MENTION_TOKEN,
    PR_CLOSE,
    PR_CONFLICT,
    PR_HEAD_MOVED,
    PR_CONFLICT_CAP,
    PR_CONFLICT_ESCALATE,
    PR_CONFLICT_TOTAL_CAP,
    PR_FEEDBACK,
    PR_MERGE,
    REVIEW_ROUNDS_CAP,
)

SKIP_OUTCOME = "done"


@dataclass(frozen=True)
class CiCap:
    outcome: str
    n: int
    target: str


@dataclass(frozen=True)
class ReviewRoundsCap:
    outcome: str
    target: str


@dataclass(frozen=True)
class StepDef:
    owner: Optional[str] = None
    escalation: bool = False
    routes: dict = field(default_factory=dict)
    pr_merge: Optional[str] = None
    pr_close: Optional[str] = None
    pr_feedback: Optional[str] = None
    pr_conflict: Optional[str] = None
    pr_head_moved: Optional[str] = None
    pr_conflict_cap: Optional[int] = None
    pr_conflict_escalate: Optional[str] = None
    pr_conflict_total_cap: Optional[int] = None
    ci_success: Optional[str] = None
    ci_failure: Optional[str] = None
    mention_token: Optional[str] = None
    ci_cap: Optional[CiCap] = None
    review_rounds_cap: Optional[ReviewRoundsCap] = None
    workspace: Optional[str] = None
    phase: Optional[str] = None
    hooks: frozenset = frozenset()
    primary: Optional[str] = None
    display: Optional[str] = None
    script: Optional[str] = None
    presents: Optional[str] = None
    detail: Optional[Tuple[str, ...]] = None
    github_heavy: bool = False
    always_run: bool = False

    def __post_init__(self):
        object.__setattr__(self, "routes", MappingProxyType(dict(self.routes)))

    @classmethod
    def from_graph(cls, graph, stage) -> "StepDef":
        def first(name, index=1):
            for occ in graph.hook_occurrences(name):
                if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[name]:
                    return occ[index]
            return None

        ci_cap = None
        for occ in graph.hook_occurrences(CI_FAILED_CAP):
            if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[CI_FAILED_CAP]:
                ci_cap = CiCap(occ[1], int(occ[2]), occ[3])

        pr_conflict_cap = None
        for occ in graph.hook_occurrences(PR_CONFLICT_CAP):
            if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[PR_CONFLICT_CAP]:
                pr_conflict_cap = int(occ[1])

        pr_conflict_total_cap = None
        for occ in graph.hook_occurrences(PR_CONFLICT_TOTAL_CAP):
            if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[PR_CONFLICT_TOTAL_CAP]:
                pr_conflict_total_cap = int(occ[1])

        review_rounds_cap = None
        for occ in graph.hook_occurrences(REVIEW_ROUNDS_CAP):
            if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[REVIEW_ROUNDS_CAP]:
                review_rounds_cap = ReviewRoundsCap(occ[1], occ[2])

        hooks = frozenset(
            "on_" + name
            for name, occs in graph.hooks.items()
            for occ in occs
            if occ and occ[0] == stage
        )

        return cls(
            routes=dict(graph.edges.get(stage) or {}),
            pr_merge=first(PR_MERGE),
            pr_close=first(PR_CLOSE),
            pr_feedback=first(PR_FEEDBACK),
            pr_conflict=first(PR_CONFLICT),
            pr_head_moved=first(PR_HEAD_MOVED),
            pr_conflict_cap=pr_conflict_cap,
            pr_conflict_escalate=first(PR_CONFLICT_ESCALATE),
            pr_conflict_total_cap=pr_conflict_total_cap,
            ci_success=first(CI_SUCCESS),
            ci_failure=first(CI_FAILURE),
            mention_token=first(MENTION_TOKEN),
            ci_cap=ci_cap,
            review_rounds_cap=review_rounds_cap,
            workspace=graph.workspaces.get(stage),
            phase=graph.phases.get(stage),
            hooks=hooks,
            primary=graph.primary.get(stage),
            display=graph.display.get(stage),
        )
