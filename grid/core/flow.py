"""Pure flow engine: assemble owner/routes from agent metas; routing decisions."""
import re

from grid.core import tasks


def load_flow(role_metas):
    """Assemble the flow from agent frontmatter metas.

    role_metas maps role -> meta. Returns (owner, routes): owner maps step -> role;
    routes maps step -> {outcome: next_step}. An agent with no `step` (the driver)
    owns nothing. A route target absent from owner is a human terminal.
    """
    owner, routes = {}, {}
    for role, meta in role_metas.items():
        step = (meta or {}).get("step")
        if not step:
            continue
        owner[step] = role
        rts = (meta or {}).get("routes")
        routes[step] = dict(rts) if isinstance(rts, dict) else {}
    return owner, routes


def flow_next(step, outcome, owner, routes):
    next_step = (routes.get(step) or {}).get(outcome)
    if not next_step:
        return None
    return (next_step, owner.get(next_step, "human"))


def advance_create_args(task, next_step, next_role):
    """The bd `create` args for the next task in the chain. Pure string building."""
    title = re.sub(r"^[a-z-]+:\s*", "", task["title"])
    args = ["create", "%s: %s" % (next_step, title), "-t", "task",
            "-l", "for:%s,step:%s" % (next_role, next_step), "--deps", task["id"], "--json"]
    if task.get("parent"):
        args += ["--parent", task["parent"]]
    return args


def ready_roles_from_beads(beads):
    out = []
    for b in beads:
        role = tasks.label_value(b, "for:")
        if role and role != "human" and role not in out:
            out.append(role)
    return out
