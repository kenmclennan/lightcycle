from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Optional, Tuple

from lightcycle.domain.flow.hooks import (
    CI_FAILURE,
    CI_SUCCESS,
    HOOK_MIN_ARITY,
    MENTION_TOKEN,
    PR_CLOSE,
    PR_CONFLICT,
    PR_HEAD_MOVED,
    PR_FEEDBACK,
    PR_MERGE,
    parse_caps,
)

SKIP_OUTCOME = "done"


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
    ci_success: Optional[str] = None
    ci_failure: Optional[str] = None
    mention_token: Optional[str] = None
    caps: dict = field(default_factory=dict)
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
        object.__setattr__(self, "caps", MappingProxyType(dict(self.caps)))

    @classmethod
    def from_graph(cls, graph, stage) -> "StepDef":
        def first(name, index=1):
            for occ in graph.hook_occurrences(name):
                if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[name]:
                    return occ[index]
            return None

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
            ci_success=first(CI_SUCCESS),
            ci_failure=first(CI_FAILURE),
            mention_token=first(MENTION_TOKEN),
            caps=parse_caps(graph, stage),
            workspace=graph.workspaces.get(stage),
            phase=graph.phases.get(stage),
            hooks=hooks,
            primary=graph.primary.get(stage),
            display=graph.display.get(stage),
        )
