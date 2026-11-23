EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def effort_problem(value):
    if isinstance(value, str) and value in EFFORT_LEVELS:
        return None
    return "effort %r is not one of %s" % (value, ", ".join(EFFORT_LEVELS))
