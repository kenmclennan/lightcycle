"""Pure flow engine: assemble owner/routes from agent metas; routing decisions."""
import re

from the_grid.core import tasks


def load_flow(role_metas):
    """Assemble the flow from agent frontmatter metas.

    role_metas maps role -> meta. Returns (owner, routes): owner maps step -> role;
    routes maps step -> {outcome: next_step}. A file with `model` + `step` is an
    automated agent and owns its step as itself. A file with `step` but NO `model`
    is a human step: it owns its step as the literal role "human" (never spawned,
    surfaces in tg mine). A file with no `step` (the driver) owns nothing. A route
    target absent from owner is a human terminal.
    """
    owner, routes = {}, {}
    for role, meta in role_metas.items():
        meta = meta or {}
        step = meta.get("step")
        if not step:
            continue
        owner[step] = role if meta.get("model") else "human"
        rts = meta.get("routes")
        routes[step] = dict(rts) if isinstance(rts, dict) else {}
    return owner, routes


def compose_driver(base_body, skills):
    """The Driver's system prompt: its base persona (driver.md) plus a skill per
    human-performed step. The Driver is the performer of human-facing steps, so it
    carries their procedures. skills is a list of (step, body), already ordered."""
    if not skills:
        return base_body
    parts = [base_body,
             "\n\n# Skills for human-facing steps\n",
             "These steps surface in `tg mine`. When the human picks one, run the skill "
             "for its step: assist them, and record the outcome (`tg done` / `tg close`).\n"]
    for step, body in skills:
        parts.append("\n## %s\n\n%s" % (step, body.strip()))
    return "\n".join(parts)


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


def ready_task_roles(beads):
    """The role of each ready, non-human task - one entry per task, repeats kept.
    This is the agent pool's work queue: N copies of a role means N tasks waiting."""
    return [r for r in (tasks.label_value(b, "for:") for b in beads) if r and r != "human"]


def ready_roles_from_beads(beads):
    out = []
    for role in ready_task_roles(beads):
        if role not in out:
            out.append(role)
    return out


def forward_note(step, outcome, text):
    """Provenance-prefixed note for forwarding onto the next task."""
    return "from %s (%s): %s" % (step, outcome, text)


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
