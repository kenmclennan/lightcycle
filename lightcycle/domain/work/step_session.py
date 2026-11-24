from dataclasses import dataclass
from datetime import datetime
from typing import Optional

ENDED_REASON_TEXT = {
    "stalled": "stalled, killed by the pool",
    "pool-stopped": "the pool stopped",
    "died": "the worker process died",
    "reclaimed": "the claim was reclaimed",
    "claim-failed": "the claim failed",
}


@dataclass(frozen=True)
class StepSession:
    n: int
    log_path: str
    started_at: Optional[str]
    ended_reason: Optional[str]


def reason_text(reason):
    return ENDED_REASON_TEXT.get(reason, "unknown")


def session_separator(session, total, previous_reason, local_zone=None) -> str:
    parts = ["session %d of %d" % (session.n, total)]
    if session.started_at:
        clock = datetime.fromisoformat(session.started_at).astimezone(local_zone)
        parts.append("started %s" % clock.strftime("%H:%M:%S"))
    parts.append("previous session ended: %s" % reason_text(previous_reason))
    return "--- %s ---" % " - ".join(parts)


def session_dicts(sessions):
    return [
        {"n": s.n, "log": s.log_path, "started_at": s.started_at, "ended": s.ended_reason}
        for s in sessions
    ]
