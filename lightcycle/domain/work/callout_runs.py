import json

from lightcycle.domain.work.timestamp import parse_timestamp

CALLOUT_RUNS = "callout-runs"
STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
PHASE_PREFLIGHT = "preflight"
PHASE_RUN = "run"
PHASE_CLEANUP = "cleanup"
CLEANUP_WINDOW_SECONDS = 604800
COST_BASIS_REPORTED = "reported"
INTERRUPTED_MESSAGE = "interrupted by a pool restart"


def parse_runs(value):
    if not value:
        return {}
    try:
        raw = json.loads(value)
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def dump_runs(runs):
    return json.dumps(runs, sort_keys=False)


def holds_gate(record):
    return (
        isinstance(record, dict) and record.get("status") == STATUS_RUNNING
        and bool(record.get("wait")))


def in_cleanup_window(step_closed_at, now):
    try:
        closed = parse_timestamp(step_closed_at)
    except (ValueError, TypeError):
        return False
    if closed is None:
        return False
    return now - closed.timestamp() <= CLEANUP_WINDOW_SECONDS


def cleanup_due(step_closed_at, record, now):
    if not isinstance(record, dict):
        return False
    if record.get("status") not in (STATUS_OK, STATUS_FAILED):
        return False
    if record.get("phase", PHASE_RUN) != PHASE_RUN:
        return False
    if record.get("subject") is None or "cleanup" in record:
        return False
    return in_cleanup_window(step_closed_at, now)
