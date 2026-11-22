import json

CALLOUT_RUNS = "callout-runs"
STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
PHASE_PREFLIGHT = "preflight"
PHASE_RUN = "run"
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
