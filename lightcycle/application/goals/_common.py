from lightcycle.application.errors import UseCaseError


def require_goal(store, goal_id):
    goal = store.get_goal(goal_id)
    if goal is None:
        raise UseCaseError("no such goal: %s" % goal_id)
    return goal


def require_text(value, what):
    text = (value or "").strip()
    if not text:
        raise UseCaseError("%s must not be empty" % what)
    return text
