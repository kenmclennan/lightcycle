from dataclasses import dataclass

_PASSING_CONCLUSIONS = ("success", "skipped", "neutral")
_CANCELLED = "cancelled"


MISSING_STATUS = "missing"


@dataclass(frozen=True)
class MissingCheck:
    name: str
    started_at: float
    status: str = MISSING_STATUS
    conclusion: None = None
    url: str = ""
    completed_at: float = 0.0


def is_concluded(check):
    if not check.conclusion:
        return False
    return check.status == "completed" or check.completed_at > 0


def status_mismatch(check):
    return check.status == "completed" and not check.conclusion


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


def timed_out_check(checks, now, ceiling, since=0.0):
    if ceiling is None:
        return None
    return next(
        (c for c in checks
         if not is_concluded(c)
         and (c.started_at if c.started_at > 0 else since) > 0
         and now - (c.started_at if c.started_at > 0 else since) > ceiling),
        None,
    )


def _empty_outcome(now, ceiling, since, runs, expected, start_window, quiet_wait):
    if since <= 0 or runs is None:
        return "pending"
    elapsed = now - since
    if runs > 0:
        return "timeout" if ceiling is not None and elapsed > ceiling else "pending"
    if expected is None:
        return "pending"
    if expected:
        return "stalled" if start_window is not None and elapsed > start_window else "pending"
    return "success" if quiet_wait is not None and elapsed > quiet_wait else "pending"


def ci_outcome(
    checks, required=None, now=0.0, ceiling=None, since=0.0, *,
    runs=None, expected=None, start_window=None, quiet_wait=None,
):
    judged = judged_checks(checks, required, since)
    if not judged:
        return _empty_outcome(now, ceiling, since, runs, expected, start_window, quiet_wait)
    if timed_out_check(judged, now, ceiling, since) is not None:
        return "timeout"
    if any(not is_concluded(c) for c in judged):
        return "pending"
    if failing_check(judged):
        return "failure"
    return "cancelled" if cancelled_check(judged) else "success"


def failing_check(checks):
    return next(
        (c for c in checks if c.conclusion not in _PASSING_CONCLUSIONS and c.conclusion != _CANCELLED),
        None,
    )


def cancelled_check(checks):
    return next((c for c in checks if c.conclusion == _CANCELLED), None)
