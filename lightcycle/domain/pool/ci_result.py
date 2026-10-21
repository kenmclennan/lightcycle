from dataclasses import dataclass

_PASSING_CONCLUSIONS = ("success", "skipped", "neutral")


MISSING_STATUS = "missing"


@dataclass(frozen=True)
class MissingCheck:
    name: str
    started_at: float
    status: str = MISSING_STATUS
    conclusion: None = None
    url: str = ""


def judged_checks(checks, required=None, since=0.0):
    if required is None:
        return tuple(checks)
    matched = tuple(c for c in checks if c.name in required)
    present = {c.name for c in matched}
    absent = tuple(
        MissingCheck(name=name, started_at=since)
        for name in sorted(required - present)
    )
    return matched + absent


def timed_out_check(checks, now, ceiling):
    if ceiling is None:
        return None
    return next(
        (c for c in checks
         if c.status in ("in_progress", MISSING_STATUS) and c.started_at > 0 and now - c.started_at > ceiling),
        None,
    )


def ci_outcome(checks, required=None, now=0.0, ceiling=None, since=0.0):
    judged = judged_checks(checks, required, since)
    if not judged:
        return "success"
    if timed_out_check(judged, now, ceiling) is not None:
        return "timeout"
    if any(c.status != "completed" for c in judged):
        return "pending"
    return "failure" if failing_check(judged) else "success"


def failing_check(checks):
    return next((c for c in checks if c.conclusion not in _PASSING_CONCLUSIONS), None)
