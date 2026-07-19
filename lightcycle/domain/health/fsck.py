from lightcycle.domain.health.problem import Problem
from lightcycle.domain.work.state import State

_DANGLING_ARTIFACT_TYPES = ("resolves", "filed-from", "watched-step")


def fsck(nodes):
    by_id = {n.id: n for n in nodes}
    steps_by_parent = {}
    for n in nodes:
        if n.parent:
            steps_by_parent.setdefault(n.parent, []).append(n)
    problems = []
    for n in nodes:
        problems.extend(_orphan(n, by_id))
        problems.extend(_dangling_artifacts(n, by_id))
    for n in nodes:
        if n.type == "item":
            problems.extend(_stuck_state(n, steps_by_parent.get(n.id, [])))
    return problems


def _orphan(n, by_id):
    if not n.parent:
        return []
    parent = by_id.get(n.parent)
    if parent is None:
        return [Problem("store", "parent %r does not exist" % n.parent, n.id)]
    if parent.state == State.DONE and n.state != State.DONE:
        return [Problem("store", "open under closed parent %s" % n.parent, n.id)]
    return []


def _dangling_artifacts(n, by_id):
    return [
        Problem("store", "%s artifact points at missing node %r" % (a.type, a.value), n.id)
        for a in n.artifacts
        if a.type in _DANGLING_ARTIFACT_TYPES and a.value not in by_id
    ]


def _stuck_state(item, children):
    problems = []
    if children and item.state == State.BACKLOGGED:
        problems.append(
            Problem("store", "backlogged but has %d step(s)" % len(children), item.id))
    steps = [c for c in children if c.type == "step"]
    if steps and item.state != State.DONE and all(s.state == State.DONE for s in steps):
        problems.append(
            Problem("store", "%s but all %d step(s) are done - never closed"
                    % (item.state, len(steps)), item.id))
    return problems
