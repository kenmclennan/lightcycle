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
