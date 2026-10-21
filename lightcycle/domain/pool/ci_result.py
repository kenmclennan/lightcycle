_PASSING_CONCLUSIONS = ("success", "skipped", "neutral")


def judged_checks(checks, required=None):
    if required is None:
        return tuple(checks)
    matched = tuple(c for c in checks if c.name in required)
    return matched or tuple(checks)


def timed_out_check(checks, now, ceiling):
    if ceiling is None:
        return None
    return next(
        (c for c in checks
         if c.status == "in_progress" and c.started_at > 0 and now - c.started_at > ceiling),
        None,
    )


def ci_outcome(checks, required=None, now=0.0, ceiling=None):
    judged = judged_checks(checks, required)
    if not judged:
        return "success"
    if timed_out_check(judged, now, ceiling) is not None:
        return "timeout"
    if any(c.status != "completed" for c in judged):
        return "pending"
    return "failure" if failing_check(judged) else "success"


def failing_check(checks):
    return next((c for c in checks if c.conclusion not in _PASSING_CONCLUSIONS), None)
