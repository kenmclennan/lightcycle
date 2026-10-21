from dataclasses import dataclass
from typing import Callable, Optional

PR_MERGE = "pr_merge"
PR_CLOSE = "pr_close"
PR_FEEDBACK = "pr_feedback"
PR_CONFLICT = "pr_conflict"
PR_HEAD_MOVED = "pr_head_moved"
PR_CONFLICT_CAP = "pr_conflict_cap"
PR_CONFLICT_ESCALATE = "pr_conflict_escalate"
PR_CONFLICT_TOTAL_CAP = "pr_conflict_total_cap"
CI_FAILED_CAP = "ci_failed_cap"
CI_SUCCESS = "ci_success"
CI_FAILURE = "ci_failure"
REVIEW_ROUNDS_CAP = "review_rounds_cap"
MENTION_TOKEN = "mention_token"

HOOK_MIN_ARITY = {
    PR_MERGE: 2,
    PR_CLOSE: 2,
    PR_FEEDBACK: 2,
    PR_CONFLICT: 2,
    PR_HEAD_MOVED: 2,
    PR_CONFLICT_CAP: 2,
    PR_CONFLICT_ESCALATE: 2,
    PR_CONFLICT_TOTAL_CAP: 2,
    CI_FAILED_CAP: 4,
    CI_SUCCESS: 2,
    CI_FAILURE: 2,
    REVIEW_ROUNDS_CAP: 3,
    MENTION_TOKEN: 2,
}


CONSECUTIVE = "consecutive"
TOTAL = "total"
FAILURES = "failures"

PR_CONFLICT_TOTAL_CAP_MULTIPLIER = 3


@dataclass(frozen=True)
class Cap:
    hook: str
    outcome: Optional[str]
    counting: str
    limit: Optional[int] = None
    limit_key: Optional[str] = None
    escalate_stage: Optional[str] = None
    escalate_outcome: Optional[str] = None
    trigger_hook: Optional[str] = None
    retry: bool = False


@dataclass(frozen=True)
class CapSpec:
    hook: str
    parse: Callable
    target_index: Optional[int] = None
    derive: Optional[Callable] = None


def _parse_ci_failed_cap(occ, companion):
    return Cap(
        CI_FAILED_CAP, occ[1], CONSECUTIVE, limit=int(occ[2]), escalate_stage=occ[3], retry=True,
    )


def _parse_pr_conflict_cap(occ, companion):
    return Cap(
        PR_CONFLICT_CAP, companion(PR_CONFLICT), FAILURES, limit=int(occ[1]),
        escalate_outcome=companion(PR_CONFLICT_ESCALATE), trigger_hook=PR_CONFLICT,
    )


def _parse_pr_conflict_total_cap(occ, companion):
    return Cap(
        PR_CONFLICT_TOTAL_CAP, companion(PR_CONFLICT), TOTAL, limit=int(occ[1]),
        escalate_outcome=companion(PR_CONFLICT_ESCALATE), trigger_hook=PR_CONFLICT,
    )


def _derive_pr_conflict_total_cap(caps):
    base = caps.get(PR_CONFLICT_CAP)
    if base is None:
        return None
    return Cap(
        PR_CONFLICT_TOTAL_CAP, base.outcome, TOTAL,
        limit=PR_CONFLICT_TOTAL_CAP_MULTIPLIER * base.limit,
        escalate_outcome=base.escalate_outcome, trigger_hook=PR_CONFLICT,
    )


def _parse_review_rounds_cap(occ, companion):
    return Cap(
        REVIEW_ROUNDS_CAP, occ[1], CONSECUTIVE, limit_key="review-rounds-cap",
        escalate_stage=occ[2],
    )


CAP_SPECS = (
    CapSpec(CI_FAILED_CAP, _parse_ci_failed_cap, target_index=3),
    CapSpec(PR_CONFLICT_CAP, _parse_pr_conflict_cap),
    CapSpec(PR_CONFLICT_TOTAL_CAP, _parse_pr_conflict_total_cap, derive=_derive_pr_conflict_total_cap),
    CapSpec(REVIEW_ROUNDS_CAP, _parse_review_rounds_cap, target_index=2),
)


def _first_for_stage(graph, stage):
    def companion(name):
        for occ in graph.hook_occurrences(name):
            if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[name]:
                return occ[1]
        return None
    return companion


def parse_caps(graph, stage):
    companion = _first_for_stage(graph, stage)
    caps = {}
    for spec in CAP_SPECS:
        for occ in graph.hook_occurrences(spec.hook):
            if occ[0] == stage and len(occ) >= HOOK_MIN_ARITY[spec.hook]:
                caps[spec.hook] = spec.parse(occ, companion)
        if spec.hook not in caps and spec.derive is not None:
            derived = spec.derive(caps)
            if derived is not None:
                caps[spec.hook] = derived
    return caps


def graph_caps(graph):
    out = []
    for spec in CAP_SPECS:
        for occ in graph.hook_occurrences(spec.hook):
            if occ and len(occ) >= HOOK_MIN_ARITY[spec.hook]:
                out.append((occ[0], spec.parse(occ, _first_for_stage(graph, occ[0]))))
    return out


def cap_target_occurrences(graph):
    return [
        (spec.hook, occ, spec.target_index)
        for spec in CAP_SPECS
        if spec.target_index is not None
        for occ in graph.hook_occurrences(spec.hook)
    ]
