from lightcycle.domain.work import State


_RAW_STORAGE_STATE = {
    State.BACKLOGGED: "backlogged",
    State.BLOCKED: "backlogged",
    State.QUEUED: "ready",
    State.WAITING: "ready",
    State.RUNNING: "in_progress",
    State.DONE: "done",
}

_ITEM_COLUMNS = (
    "id", "title", "description", "state", "repo", "workflow", "outcome", "disposition",
    "note", "project", "created_at", "closed_at",
)

_STEP_COLUMNS = (
    "id", "item", "stage", "pass_id", "role", "state", "assignee", "model",
    "outcome", "notes", "watched_step",
    "park_reason", "park_needs", "park_tried",
    "created_at", "fired_at", "closed_at", "active_seconds",
    "usage_input_tokens", "usage_output_tokens", "usage_cache_read_tokens",
    "usage_cache_creation_tokens", "usage_cost_usd", "usage_cost_basis", "usage_rates_used",
    "usage_thinking_tokens", "usage_api_calls", "turn_count", "previous_step", "report", "log_path",
)

_PARK_COLUMNS = {"needs": "park_needs", "reason": "park_reason", "tried": "park_tried"}

_RUN_SELECT = (
    "SELECT id, item, pass_id, phase, branch, pr, content_pin, "
    "comments_dispatched_through, comments_handled_through, state, opened_at, closed_at "
    "FROM phase_runs"
)
