from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Optional

from lightcycle.domain.flow.hooks import CI_FAILED_CAP, PR_CONFLICT, PR_FEEDBACK, PR_MERGE


@dataclass(frozen=True)
class CiCap:
    outcome: str
    n: int
    target: str


@dataclass(frozen=True)
class StepDef:
    owner: Optional[str] = None
    routes: dict = field(default_factory=dict)
    pr_merge: Optional[str] = None
    pr_close: Optional[str] = None
    pr_feedback: Optional[str] = None
    pr_conflict: Optional[str] = None
    pr_conflict_cap: Optional[int] = None
    pr_conflict_escalate: Optional[str] = None
    mention_token: Optional[str] = None
    review_bot_allowlist: frozenset = frozenset()
    ci_cap: Optional[CiCap] = None
    workspace: Optional[str] = None
    phase: Optional[str] = None
    hooks: frozenset = frozenset()
    primary: Optional[str] = None
    display: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "routes", MappingProxyType(dict(self.routes)))

    @classmethod
    def from_graph(cls, graph, stage) -> "StepDef":
        def first(name, index=1):
            for occ in graph.hook_occurrences(name):
                if occ[0] == stage and len(occ) > index:
                    return occ[index]
            return None

        ci_cap = None
        for occ in graph.hook_occurrences(CI_FAILED_CAP):
            if occ[0] == stage:
                ci_cap = CiCap(occ[1], int(occ[2]), occ[3])

        pr_conflict_cap = None
        for occ in graph.hook_occurrences("pr_conflict_cap"):
            if occ[0] == stage and len(occ) > 1:
                pr_conflict_cap = int(occ[1])

        review_bot_allowlist = frozenset()
        for occ in graph.hook_occurrences("review_bot_allowlist"):
            if occ[0] == stage:
                review_bot_allowlist = frozenset(occ[1:])

        hooks = frozenset(
            "on_" + name
            for name, occs in graph.hooks.items()
            for occ in occs
            if occ and occ[0] == stage
        )

        return cls(
            routes=dict(graph.edges.get(stage) or {}),
            pr_merge=first(PR_MERGE),
            pr_close=first("pr_close"),
            pr_feedback=first(PR_FEEDBACK),
            pr_conflict=first(PR_CONFLICT),
            pr_conflict_cap=pr_conflict_cap,
            pr_conflict_escalate=first("pr_conflict_escalate"),
            mention_token=first("mention_token"),
            review_bot_allowlist=review_bot_allowlist,
            ci_cap=ci_cap,
            workspace=graph.workspaces.get(stage),
            phase=graph.phases.get(stage),
            hooks=hooks,
            primary=graph.primary.get(stage),
            display=graph.display.get(stage),
        )
