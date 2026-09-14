_PASSING_CONCLUSIONS = ("success", "skipped", "neutral")


def ci_outcome(checks):
    if not checks:
        return "success"
    if any(c.status != "completed" for c in checks):
        return "pending"
    return "failure" if failing_check(checks) else "success"


def failing_check(checks):
    return next((c for c in checks if c.conclusion not in _PASSING_CONCLUSIONS), None)
