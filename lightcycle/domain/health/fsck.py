from lightcycle.domain.health.problem import Problem
from lightcycle.domain.work.state import State

_DANGLING_ARTIFACT_TYPES = ("resolves", "filed-from")


def fsck(nodes):
    by_id = {n.id: n for n in nodes}
    steps_by_parent = {}
    for n in nodes:
        if n.type == "step" and n.item:
            steps_by_parent.setdefault(n.item, []).append(n)
    problems = []
    for n in nodes:
        problems.extend(_orphan(n, by_id))
        problems.extend(_dangling_artifacts(n, by_id))
    for n in nodes:
        if n.type == "item":
            problems.extend(_stuck_state(n, steps_by_parent.get(n.id, [])))
    return problems


def _orphan(n, by_id):
    if n.type != "step" or not n.item:
        return []
    parent = by_id.get(n.item)
    if parent is None:
        return [Problem("store", "parent %r does not exist" % n.item, n.id)]
    if parent.state == State.DONE and n.state != State.DONE:
        return [Problem("store", "open under closed parent %s" % n.item, n.id)]
    return []


def _dangling_artifacts(n, by_id):
    watched = getattr(n, "watched_step", None)
    dangling = (
        [Problem("store", "watched-step points at missing node %r" % watched, n.id)]
        if watched and watched not in by_id else []
    )
    return dangling + [
        Problem("store", "%s artifact points at missing node %r" % (a.type, a.value), n.id)
        for a in getattr(n, "artifacts", ())
        if a.type in _DANGLING_ARTIFACT_TYPES and a.value not in by_id
    ]


def _stuck_state(item, children):
    if not children:
        return []
    all_done = all(c.state == State.DONE for c in children)
    if item.state == State.BACKLOGGED and not all_done:
        return [Problem("store", "backlogged but has %d step(s)" % len(children), item.id)]
    if item.state not in (State.DONE, State.BACKLOGGED) and all_done:
        return [Problem(
            "store", "%s but all %d step(s) are done - never closed"
            % (item.state, len(children)), item.id
        )]
    return []
