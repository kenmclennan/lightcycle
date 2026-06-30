"""Pool planning: the role per ready task and the spawn decision for one tick."""
from the_grid.domain.task import label_value


def ready_task_roles(beads):
    """The role of each ready, non-human task - one entry per task, repeats kept.
    This is the agent pool's work queue: N copies of a role means N tasks waiting."""
    return [r for r in (label_value(b, "for:") for b in beads) if r and r != "human"]


def ready_roles_from_beads(beads):
    out = []
    for role in ready_task_roles(beads):
        if role not in out:
            out.append(role)
    return out


def pool_plan(ready_roles, inflight, slots):
    """Decide which roles to spawn this tick for the agent pool.

    ready_roles is the role per ready task (one entry each, repeats allowed). inflight
    maps role -> count of booting workers (alive, not yet claimed): each already covers
    one ready task of its role, so it is not re-spawned. slots is the number of free
    pool seats (max_agents - alive workers). Returns the roles to spawn, one entry per
    new worker, in queue order and capped at slots."""
    inflight = dict(inflight)
    out = []
    for role in ready_roles:
        if len(out) >= slots:
            break
        if inflight.get(role, 0) > 0:
            inflight[role] -= 1
            continue
        out.append(role)
    return out
