"""tg - the-grid domain CLI. Wires the pure core to the IO adapters; all cmd_*."""
import argparse
import json
import os
import sys
import time

from the_grid.core import config as cconfig
from the_grid.core import contracts as ccontracts
from the_grid.core import flow as cflow
from the_grid.core import reflect as creflect
from the_grid.core import retro as cretro
from the_grid.core import tasks as ctasks
from the_grid.core import workspace as cworkspace
from the_grid.core.contracts import (FILE_PROVIDES, optional_inputs, required_inputs,
                                 required_outputs)
from the_grid.core.logrender import render_log_line
from the_grid.core.tasks import task_from_bead

from the_grid.adapters import gitio
from the_grid.adapters.fsio import (step_roles, config_path, ensure_config, grid_root,
                                load_config, parse_step, read_md, store_ready, worktrees_dir)
from the_grid.adapters.spawner import spawn_worker
from the_grid.adapters.store import (add_artifact, all_tasks, bd, bd_json, ensure_beads,
                                 get_task, present_types, route_to_human,
                                 story_artifacts, task_view)
from the_grid.adapters.workers import (pid_alive, prune_workers, stamp_bead, workers_state)

# ---- config / roots ---------------------------------------------------------


def _home():
    return os.path.expanduser("~")


def projects_root():
    return cconfig.projects_root(load_config(), _home())


def specs_root():
    return cconfig.specs_root(load_config(), _home())


def branch_prefix():
    return cconfig.branch_prefix(load_config())


def max_agents():
    return int(os.environ.get("GRID_MAX_AGENTS") or cconfig.max_agents(load_config()))


# ---- flow assembly (IO gather -> pure decision) -----------------------------


def _role_metas():
    return {role: (parse_step(role) or {"meta": {}})["meta"] for role in step_roles()}


def load_flow():
    return cflow.load_flow(_role_metas())


def flow_next(step, outcome):
    owner, routes = load_flow()
    return cflow.flow_next(step, outcome, owner, routes)


def meta_for_step(step):
    owner, _ = load_flow()
    role = owner.get(step)
    if not role:
        return {}
    a = parse_step(role)
    return a["meta"] if a else {}


def ready_roles():
    return cflow.ready_roles_from_beads(bd_json("ready", "--json"))


# ---- claim / advance (pure decision + bd effect) ----------------------------


def claim_next(role):
    arr = bd_json("ready", "--label", "for:%s" % role, "--claim", "--json")
    if not arr:
        return None
    t = task_from_bead(arr[0])
    missing = required_inputs(meta_for_step(t["step"])) - present_types(t)
    if missing:
        route_to_human(t["id"],
                       "BLOCKED: missing required input(s): %s" % ", ".join(sorted(missing)),
                       role)
        return None
    return t


def advance(tid, outcome):
    t = get_task(tid)
    nxt = flow_next(t["step"], outcome)
    if nxt is None:
        return None
    ns, no = nxt
    return bd_json(*cflow.advance_create_args(t, ns, no))["id"]


# ---- worktrees (core decision + gitio effect) -------------------------------


def story_repo(story):
    return cworkspace.story_repo(story_artifacts(story), os.path.basename(grid_root()))


def worktree_path(story):
    return cworkspace.worktree_path(worktrees_dir(), story)


def _ensure_worktrees_ignored(root):
    gi = os.path.join(root, ".gitignore")
    line = ".worktrees/"
    existing = ""
    if os.path.exists(gi):
        with open(gi) as f:
            existing = f.read()
    if line in (l.strip() for l in existing.splitlines()):
        return
    with open(gi, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")


def _story_branch(story):
    for a in story_artifacts(story):
        if a.get("type") == "branch":
            return a["value"]
    return None


def _ensure_branch_artifact(story, branch):
    if any(a.get("type") == "branch" for a in story_artifacts(story)):
        return
    add_artifact(story, "branch", branch)


def ensure_worktree(story):
    """Create (or reuse) the per-story git worktree on a feature-named branch so a
    worker never mutates the primary tree. The branch is computed once from the story
    title (its feature name) and the configured prefix, then stored as the `branch`
    artifact and reused on later claims. The target repo is resolved by name from the
    story's `repo` artifact (default: the engine itself). Idempotent: an existing
    worktree or branch is reused. Returns the workspace path, or None when no isolated
    tree can be made (not a git repo, or no origin/main to branch from)."""
    target = os.path.join(projects_root(), story_repo(story))
    if not gitio.is_git_repo(target):
        return None
    branch = _story_branch(story) or cworkspace.branch_for(get_task(story)["title"], branch_prefix())
    path = worktree_path(story)
    if gitio.worktree_registered(target, path) and os.path.isdir(path):
        _ensure_branch_artifact(story, branch)
        return path
    if gitio.branch_exists(target, branch):
        add_args = ["worktree", "add", path, branch]
    else:
        base = gitio.worktree_base(target)
        if base is None:
            return None
        add_args = ["worktree", "add", path, "-b", branch, base]
    os.makedirs(worktrees_dir(), exist_ok=True)
    _ensure_worktrees_ignored(grid_root())
    # Several pool workers may add worktrees against one target repo at once and race
    # on git's `.git/worktrees` lock; the add is idempotent, so retry the transient
    # lock failure with a short backoff before giving up.
    retries = int(os.environ.get("GRID_WORKTREE_RETRIES", "6"))
    backoff = float(os.environ.get("GRID_WORKTREE_RETRY_SLEEP", "0.25"))
    gitio.git(target, "worktree", "prune")
    res = gitio.git(target, *add_args)
    while res.returncode != 0 and retries > 0 and cworkspace.is_worktree_lock_error(res.stderr):
        retries -= 1
        time.sleep(backoff)
        gitio.git(target, "worktree", "prune")
        res = gitio.git(target, *add_args)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        return None
    _ensure_branch_artifact(story, branch)
    return path


# ---- store guard ------------------------------------------------------------


def require_store():
    if store_ready():
        return True
    sys.stderr.write("no grid store here - run `tg init` first.\n")
    return False


# ---- CLI dispatch -----------------------------------------------------------

# Command catalog: (group, [(verb, usage-args, description), ...]). The order is
# the help order; VERBS is derived from it, so adding a command here registers it.
COMMAND_GROUPS = [
    ("Setup", [
        ("init", "", "create the grid store and seed the HOME config (run once)"),
        ("config", "[--edit]", "show or edit the grid config (projects + specs roots)"),
    ]),
    ("Start working", [
        ("run", "[--once]", "the agent pool: each tick, sweep stale claims, then fill up to GRID_MAX_AGENTS (default 4) workers from the ready queue"),
        ("driver", "", "open the interactive driver - your seat to shape and file work"),
    ]),
    ("See what's happening", [
        ("status", "[--json]", "all buckets at once: mine / active / queue / blocked"),
        ("mine", "", "tasks waiting on you (for:human)"),
        ("active", "", "tasks a worker is running right now"),
        ("queue", "[N]", "the next N ready/blocked agent tasks"),
        ("ps", "[--json]", "running workers: role, task, pid, alive/dead"),
        ("logs", "<task|role|run> [-f]", "tail a worker's or the loop's log"),
        ("show", "<id>", "one task or story as JSON (artifacts, resume-state)"),
        ("trace", "<story> [--json]", "a story end to end: artifacts + child tasks + logs"),
        ("flow", "[--json]", "print and check the assembled flow (steps, routes, contracts, composition)"),
    ]),
    ("Drive work in", [
        ("file", "<spec> --step <step> [--repo/--epic/--project/--goal]",
         "create a story (for one repo) from a spec + its first task at <step>"),
        ("link", "<story> <type> <value> [--label]", "attach an artifact to a story"),
        ("add", '"<title>" [--goal/--project]', "create a standalone human task (no spec/flow)"),
        ("close", "<story> <reason>",
         "close a story + its tasks, remove the worktree, delete the merged branch"),
    ]),
    ("Agent verbs (workers call these)", [
        ("claim", "<role>", "atomically claim the next ready task for a role"),
        ("done", "<id> <outcome>", "close a task with a flow outcome and advance the chain"),
        ("block", "<id> --needs ... [--branch/--pr/--reason/--tried]",
         "escalate to a human with resume-state"),
        ("unblock", "<id>", "flip a blocked task back to its agent role so it re-claims and retries"),
        ("reflect", '<task> [--used/--skipped/--guess "<sections>"] [--missing/--noise "text"]',
         "record a structured spec-section reflection on the story (call before tg done)"),
        ("plan-add", '<epic> "<title>" --spec <path> [--blocked-by <id>]',
         "create a child story under an epic with a build task, optionally gated by a dep"),
    ]),
    ("Feedback loop", [
        ("retro", "<epic>", "aggregate child reflections + objective signals into a read digest"),
    ]),
    ("Maintenance", [
        ("sweep", "", "reclaim orphaned task claims and prune dead worker entries (kept: GRID_WORKER_HISTORY, default 20)"),
    ]),
    ("Plumbing (the loop uses these)", [
        ("advance", "<id> <outcome>", "create the next task for an outcome without closing"),
        ("ready-roles", "", "list roles that have a ready task"),
        ("spawn", "<role>", "spawn one worker for a role"),
    ]),
]

VERBS = tuple(verb for _, cmds in COMMAND_GROUPS for verb, _, _ in cmds)


def print_help():
    print("tg - the-grid domain CLI\n")
    print("Usage: tg <command> [args]\n")
    width = min(34, max(len(("%s %s" % (v, args)).rstrip())
                        for _, cmds in COMMAND_GROUPS for v, args, _ in cmds))
    for group, cmds in COMMAND_GROUPS:
        print("%s:" % group)
        for verb, args, desc in cmds:
            print("  %-*s  %s" % (width, ("%s %s" % (verb, args)).rstrip(), desc))
        print("")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print_help()
        return 0
    cmd = argv[0]
    if cmd not in VERBS:
        sys.stderr.write("unknown subcommand: %s\n" % cmd)
        return 2
    fn = globals().get("cmd_" + cmd.replace("-", "_"))
    if fn is None:
        sys.stderr.write("not implemented: %s\n" % cmd)
        return 2
    return fn(argv[1:]) or 0


# ---- commands ---------------------------------------------------------------


def cmd_show(argv):
    ap = argparse.ArgumentParser(prog="tg show")
    ap.add_argument("id")
    a = ap.parse_args(argv)
    print(json.dumps(task_view(a.id), indent=2))
    return 0


def cmd_claim(argv):
    ap = argparse.ArgumentParser(prog="tg claim")
    ap.add_argument("role")
    a = ap.parse_args(argv)
    t = claim_next(a.role)
    if t is None:
        return 0
    spawnid = os.environ.get("GRID_SPAWNID")
    if spawnid:
        stamp_bead(spawnid, t["id"])
    view = task_view(t["id"])
    story = t.get("parent") or t["id"]
    ws = ensure_worktree(story)
    if ws:
        view["workspace"] = ws
    branch = _story_branch(story)
    if branch:
        view["branch"] = branch
    spec = next((a["value"] for a in view.get("story_artifacts", []) if a.get("type") == "spec"), None)
    if spec:
        view["spec_path"] = spec if os.path.isabs(spec) else os.path.join(specs_root(), spec)
    print(json.dumps(view, indent=2))
    return 0


def cmd_spawn(argv):
    ap = argparse.ArgumentParser(prog="tg spawn")
    ap.add_argument("role")
    a = ap.parse_args(argv)
    return 0 if spawn_worker(a.role) else 1


def cmd_ps(argv):
    ap = argparse.ArgumentParser(prog="tg ps")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = [dict(w, alive=pid_alive(w.get("pid", -1))) for w in workers_state()]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for w in rows:
            print("  %-11s bead=%-18s pid=%s %s" % (
                w["role"], w.get("bead") or "-", w["pid"], "alive" if w["alive"] else "dead"))
    return 0


def cmd_logs(argv):
    ap = argparse.ArgumentParser(prog="tg logs")
    ap.add_argument("target")
    ap.add_argument("-f", action="store_true")
    a = ap.parse_args(argv)
    if a.target == "run":
        path = os.path.join(grid_root(), "logs", "run.log")
    else:
        path = None
        for w in reversed(workers_state()):
            if w.get("bead") == a.target or w.get("role") == a.target:
                path = w["log"]
                break
    if not path or not os.path.exists(path):
        sys.stderr.write("no log for %s\n" % a.target)
        return 1

    def emit(line):
        r = render_log_line(line)
        if r is not None:
            print(r, flush=True)
    if a.f:
        with open(path) as f:
            try:
                while True:
                    line = f.readline()
                    if line:
                        emit(line)
                    else:
                        time.sleep(0.3)
            except KeyboardInterrupt:
                pass
    else:
        for line in open(path):
            emit(line)
    return 0


def cmd_advance(argv):
    ap = argparse.ArgumentParser(prog="tg advance")
    ap.add_argument("id")
    ap.add_argument("outcome")
    a = ap.parse_args(argv)
    new = advance(a.id, a.outcome)
    if new:
        print(new)
    return 0


def cmd_ready_roles(argv):
    print(" ".join(ready_roles()))
    return 0


def cmd_flow(argv):
    ap = argparse.ArgumentParser(prog="tg flow")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    role_metas = _role_metas()
    owner, routes = cflow.load_flow(role_metas)
    an = ccontracts.analyze_flow(owner, routes, role_metas)
    steps, req, opt, prod = an["steps"], an["req"], an["opt"], an["prod"]
    entries, terminals = an["entries"], an["terminals"]
    unreachable, missing, dups, ok = an["unreachable"], an["missing"], an["dups"], an["ok"]

    if a.json:
        print(json.dumps({"owner": owner, "routes": routes,
                          "accepts": {s: {"required": sorted(req[s]),
                                          "optional": sorted(opt[s])} for s in steps},
                          "produces": {s: sorted(prod[s]) for s in steps},
                          "entries": entries, "terminals": terminals,
                          "unreachable": unreachable, "missing_inputs": missing,
                          "conflicts": dups, "ok": ok}, indent=2))
        return 0 if ok else 1

    for s in steps:
        print("%s  (%s)" % (s, owner[s]))
        accepts = ([t + " (required)" for t in sorted(req[s])]
                   + [t + " (optional)" for t in sorted(opt[s])])
        if accepts:
            print("  accepts   %s" % ", ".join(accepts))
        if prod[s]:
            print("  produces  %s" % ", ".join(sorted(prod[s])))
        for outcome, nxt in sorted(routes.get(s, {}).items()):
            print("  %-9s -> %s  [%s]" % (outcome, nxt, owner.get(nxt, "human")))
    if terminals:
        print("human terminals: %s" % ", ".join(terminals))
    if entries:
        print("entry steps: %s" % ", ".join(sorted(entries)))
    else:
        sys.stderr.write("warning: no entry step (none requires only %s)\n"
                         % ", ".join(sorted(FILE_PROVIDES)))
    for s, miss in sorted(missing.items()):
        sys.stderr.write("composition: step '%s' needs %s, not guaranteed upstream\n"
                         % (s, ", ".join(miss)))
    for s in unreachable:
        sys.stderr.write("warning: step '%s' is unreachable from any entry\n" % s)
    for d in dups:
        sys.stderr.write("conflict: %s\n" % d)
    return 0 if ok else 1


def cmd_done(argv):
    ap = argparse.ArgumentParser(prog="tg done")
    ap.add_argument("id")
    ap.add_argument("outcome")
    a = ap.parse_args(argv)
    t = get_task(a.id)
    meta = meta_for_step(t["step"])
    if flow_next(t["step"], a.outcome) is None and not meta.get("terminal"):
        sys.stderr.write(
            "no transition for step=%s outcome=%s; not closing. "
            "Fix the flow or use a defined outcome.\n" % (t["step"], a.outcome))
        return 1
    missing = required_outputs(meta_for_step(t["step"])) - present_types(t)
    if missing:
        sys.stderr.write(
            "cannot close %s: step '%s' must produce %s; none on the story. "
            "tg link the artifact first.\n" % (a.id, t["step"], ", ".join(sorted(missing))))
        return 1
    bd("note", a.id, "outcome: %s" % a.outcome)
    bd("close", a.id, "--reason", a.outcome)
    new = advance(a.id, a.outcome)
    if new:
        print(new)
    return 0


def cmd_block(argv):
    ap = argparse.ArgumentParser(prog="tg block")
    ap.add_argument("id")
    for opt in ("branch", "pr", "reason", "tried", "needs"):
        ap.add_argument("--%s" % opt)
    a = ap.parse_args(argv)
    if not a.needs:
        sys.stderr.write("tg block requires --needs (what the human must decide/provide)\n")
        return 2
    resume = {}
    for k in ("branch", "pr", "reason", "tried", "needs"):
        v = getattr(a, k, None)
        if v:
            resume[k] = v
    bd("update", a.id, "--metadata", json.dumps(resume))
    bd("note", a.id, "BLOCKED: %s" % a.needs)
    role = get_task(a.id)["role"]
    if role and role != "human":
        bd("label", "remove", a.id, "for:%s" % role)
    bd("label", "add", a.id, "for:human")
    bd("update", a.id, "--status", "open")
    bd("assign", a.id, "")
    print("blocked -> human")
    return 0


def cmd_unblock(argv):
    ap = argparse.ArgumentParser(prog="tg unblock")
    ap.add_argument("id")
    a = ap.parse_args(argv)
    t = get_task(a.id)
    owner, _ = load_flow()
    role = owner.get(t["step"])
    if not role or role == "human":
        sys.stderr.write(
            "nothing to unblock: step '%s' has no agent owner\n" % (t["step"] or "(none)"))
        return 1
    cur = t["role"]
    if cur and cur != role:
        bd("label", "remove", a.id, "for:%s" % cur)
    bd("label", "add", a.id, "for:%s" % role)
    bd("update", a.id, "--status", "open")
    bd("assign", a.id, "")
    print("unblocked -> %s" % role)
    return 0


def cmd_close(argv):
    ap = argparse.ArgumentParser(prog="tg close")
    ap.add_argument("story")
    ap.add_argument("reason")
    a = ap.parse_args(argv)
    target = os.path.join(projects_root(), story_repo(a.story))
    path = worktree_path(a.story)
    branch = _story_branch(a.story) or cworkspace.branch_for(get_task(a.story)["title"], branch_prefix())
    for k in bd_json("children", a.story, "--json"):
        kt = task_from_bead(k)
        if kt["status"] != "done":
            bd("close", kt["id"], "--reason", a.reason)
    bd("close", a.story, "--reason", a.reason)
    if gitio.is_git_repo(target):
        gitio.remove_worktree(target, path)
        gitio.delete_branch(target, branch)
    print("closed %s (%s)" % (a.story, a.reason))
    return 0


def cmd_link(argv):
    ap = argparse.ArgumentParser(prog="tg link")
    ap.add_argument("story")
    ap.add_argument("type")
    ap.add_argument("value")
    ap.add_argument("--label")
    a = ap.parse_args(argv)
    add_artifact(a.story, a.type, a.value, a.label)
    return 0


def _log_for_bead(bid):
    for w in reversed(workers_state()):
        if w.get("bead") == bid:
            return w.get("log")
    return None


def cmd_trace(argv):
    ap = argparse.ArgumentParser(prog="tg trace")
    ap.add_argument("story")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    story = get_task(a.story)
    arts = story_artifacts(a.story)
    tasks = []
    for k in bd_json("children", a.story, "--json"):
        kt = task_from_bead(k)
        tasks.append({"id": kt["id"], "step": kt["step"], "status": kt["status"],
                      "log": _log_for_bead(kt["id"])})
    out = {"story": {"id": story["id"], "title": story["title"], "status": story["status"]},
           "artifacts": arts, "tasks": tasks}
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print("story %s  %s  [%s]" % (story["id"], story["title"], story["status"]))
        for art in arts:
            print("  artifact %s: %s" % (art["type"], art["value"]))
        for t in tasks:
            log = "  log:" + t["log"] if t["log"] else ""
            print("  task %s  %s  [%s]%s" % (t["id"], t["step"] or "-", t["status"], log))
    return 0


def cmd_sweep(argv):
    # A task is owned by a live worker iff its assignee is the spawnid of a worker
    # whose pid is alive. The spawnid->pid mapping is written at spawn (before the
    # claim), so it never lags - a just-claimed task is protected immediately.
    live = {w.get("spawnid") for w in workers_state()
            if w.get("spawnid") and pid_alive(w.get("pid", -1))}
    for bead in bd_json("list", "--status", "in_progress", "--json"):
        if bead.get("assignee") in live:
            continue
        bid = bead["id"]
        bd("update", bid, "--status", "open")
        bd("assign", bid, "")
        print("swept %s" % bid)
    pruned = prune_workers()
    if pruned:
        print("pruned %d dead worker entr%s" % (pruned, "y" if pruned == 1 else "ies"))
    return 0


# ---- read views -------------------------------------------------------------


def _filter(status):
    return ctasks.filter_by_status(all_tasks(), status)


_MINE_ORDER = {"blocked": 0, "action": 1, "todo": 2}


def cmd_mine(argv):
    owner, routes = load_flow()
    rows = [(ctasks.classify_mine(t, owner, routes), t) for t in _filter("needs-human")]
    rows.sort(key=lambda r: (_MINE_ORDER.get(r[0][0], 9), r[1]["id"]))
    for (kind, _outcomes), t in rows:
        print("%-9s %s  %s" % ("[%s]" % kind, t["id"], t["title"] or t["step"]))
        story = t.get("parent") or t["id"]
        for art in story_artifacts(story):
            if art.get("type") == "plan-doc":
                print("          plan: %s" % art["value"])
    return 0


def cmd_active(argv):
    for t in _filter("in-progress"):
        print("  %s  %s" % (t["id"], t["title"]))
    return 0


def cmd_queue(argv):
    ap = argparse.ArgumentParser(prog="tg queue")
    ap.add_argument("n", nargs="?", type=int, default=10)
    a = ap.parse_args(argv)
    tasks = _filter("ready") + _filter("blocked")
    for t in tasks[:a.n]:
        print("  %-8s %s  %s" % (t["status"], t["id"], t["title"]))
    return 0


def cmd_file(argv):
    ap = argparse.ArgumentParser(prog="tg file")
    ap.add_argument("spec")
    ap.add_argument("--step", required=True)
    ap.add_argument("--epic")
    ap.add_argument("--project")
    ap.add_argument("--goal")
    ap.add_argument("--repo")
    a = ap.parse_args(argv)
    owner, _ = load_flow()
    role = owner.get(a.step)
    if not role:
        sys.stderr.write("unknown step '%s'; owned steps: %s\n"
                         % (a.step, ", ".join(sorted(owner)) or "(none)"))
        return 1
    unmet = required_inputs(meta_for_step(a.step)) - FILE_PROVIDES
    if unmet:
        sys.stderr.write(
            "step '%s' requires %s; a filed story only carries a spec. "
            "File at an entry step.\n" % (a.step, ", ".join(sorted(unmet))))
        return 1
    if a.repo:
        repo_path = os.path.join(projects_root(), a.repo)
        if not gitio.is_git_repo(repo_path):
            pr = projects_root()
            available = sorted(
                e.name for e in os.scandir(pr) if e.is_dir() and gitio.is_git_repo(e.path)
            ) if os.path.isdir(pr) else []
            avail_str = ", ".join(available) if available else "(none)"
            sys.stderr.write("unknown repo '%s'; available repos: %s\n" % (a.repo, avail_str))
            return 1
    base = os.path.splitext(os.path.basename(a.spec))[0]
    labels = []
    if a.project:
        labels.append("project:%s" % a.project)
    if a.goal:
        labels.append("goal:%s" % a.goal)
    create = ["create", base, "-t", "story", "--json"]
    if a.epic:
        create += ["--parent", a.epic]
    if labels:
        create += ["-l", ",".join(labels)]
    story = bd_json(*create)["id"]
    add_artifact(story, "spec", a.spec)
    if a.repo:
        add_artifact(story, "repo", a.repo)
    bd("create", "%s: %s" % (a.step, base), "-t", "task",
       "-l", "for:%s,step:%s" % (role, a.step), "--parent", story)
    print(story)
    return 0


def cmd_add(argv):
    ap = argparse.ArgumentParser(prog="tg add")
    ap.add_argument("title")
    ap.add_argument("--goal")
    ap.add_argument("--project")
    a = ap.parse_args(argv)
    labels = ["for:human"]
    if a.goal:
        labels.append("goal:%s" % a.goal)
    if a.project:
        labels.append("project:%s" % a.project)
    new = bd_json("create", a.title, "-t", "task", "-l", ",".join(labels), "--json")["id"]
    print(new)
    return 0


def cmd_plan_add(argv):
    ap = argparse.ArgumentParser(prog="tg plan-add")
    ap.add_argument("epic")
    ap.add_argument("title")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--blocked-by", action="append", default=[], dest="blocked_by",
                    metavar="id")
    a = ap.parse_args(argv)
    owner, _ = load_flow()
    role = owner.get("build")
    if not role:
        sys.stderr.write("no 'build' step in flow; cannot create child story\n")
        return 1
    story = bd_json("create", a.title, "-t", "story", "--parent", a.epic, "--json")["id"]
    add_artifact(story, "spec", a.spec)
    task_args = ["create", "build: %s" % a.title, "-t", "task",
                 "-l", "for:%s,step:build" % role, "--parent", story, "--json"]
    for dep in a.blocked_by:
        task_args += ["--deps", dep]
    bd_json(*task_args)
    print(story)
    return 0


# ---- run loop / launch ------------------------------------------------------


def _run_tick():
    cmd_sweep([])
    # The agent pool: fill up to GRID_MAX_AGENTS alive workers from the ready queue,
    # one worker per uncovered ready task, regardless of role. bd ready already hides
    # blocked-by tasks, so declared dependencies are honoured for free.
    alive = [w for w in workers_state() if pid_alive(w.get("pid", -1))]
    slots = max_agents() - len(alive)
    if slots <= 0:
        return
    # A worker that has spawned but not yet claimed (bead is None) and is still within
    # the boot window will claim one ready task of its role once it boots, so it covers
    # that task - don't double-spawn for it. claude's boot (~10-30s) far exceeds the
    # poll; without this cover the pool would pile redundant workers onto one task.
    # Past GRID_MAX_BOOT_SECONDS a stuck boot stops covering (the atomic claim keeps a
    # late extra spawn safe), so it can't wedge the queue.
    max_boot = int(os.environ.get("GRID_MAX_BOOT_SECONDS", "120"))
    now = time.time()
    inflight = {}
    for w in alive:
        if w.get("bead") is None and (now - w.get("started", 0)) < max_boot:
            inflight[w["role"]] = inflight.get(w["role"], 0) + 1
    ready = cflow.ready_task_roles(bd_json("ready", "--json"))
    for role in cflow.pool_plan(ready, inflight, slots):
        spawn_worker(role)


def cmd_run(argv):
    ap = argparse.ArgumentParser(prog="tg run")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    if not require_store():
        return 1
    if a.once:
        _run_tick()
        return 0
    interval = int(os.environ.get("GRID_POLL_SECONDS", "5"))
    print("tg run (poll %ds)" % interval)
    while True:
        _run_tick()
        time.sleep(interval)


def _human_step_skills():
    """The skill bodies of human-performed steps (a `step` but no `model:`), each as
    (step, body), ordered by step. The Driver loads all of these - it is their performer."""
    skills = []
    for role in step_roles():
        a = parse_step(role)
        if a and a["meta"].get("step") and not a["meta"].get("model"):
            skills.append((a["meta"]["step"], a["body"]))
    return sorted(skills)


def cmd_driver(argv):
    if not require_store():
        return 1
    root = grid_root()
    seat = read_md("driver.md")
    if seat is None or not seat["meta"].get("model"):
        sys.stderr.write("driver.md is missing or has no 'model' in frontmatter\n")
        return 1
    body = cflow.compose_driver(seat["body"], _human_step_skills())
    os.execvp("claude", ["claude", "--model", seat["meta"]["model"], "--name", "driver",
                         "--append-system-prompt", body, "--add-dir", root,
                         "--dangerously-skip-permissions"])


def cmd_init(argv):
    argparse.ArgumentParser(prog="tg init").parse_args(argv)
    existed = store_ready()
    ensure_beads()
    os.makedirs(os.path.join(grid_root(), "logs"), exist_ok=True)
    print("grid store already initialised" if existed else "grid store initialised")
    created = ensure_config()
    print("config %s at %s" % ("created" if created else "already exists", config_path()))
    return 0


def cmd_config(argv):
    ap = argparse.ArgumentParser(prog="tg config")
    ap.add_argument("--edit", action="store_true")
    a = ap.parse_args(argv)
    if a.edit:
        ensure_config()
        editor = os.environ.get("EDITOR") or "vi"
        os.execvp(editor, [editor, config_path()])
    p = config_path()
    print("config: %s" % p)
    print("exists" if os.path.exists(p) else "(using defaults)")
    print("projects: %s" % projects_root())
    print("specs: %s" % specs_root())
    return 0


def cmd_status(argv):
    ap = argparse.ArgumentParser(prog="tg status")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    buckets = ctasks.bucket(all_tasks())
    if a.json:
        print(json.dumps(buckets, indent=2))
    else:
        for name in ("mine", "active", "queue", "blocked"):
            print("== %s (%d) ==" % (name, len(buckets[name])))
            for t in buckets[name]:
                print("  %s  %s" % (t["id"], t["title"]))
    return 0


# ---- spec feedback loop (R1, R3, R4) ----------------------------------------


def _spec_hash(task):
    story = task.get("parent") or task["id"]
    arts = story_artifacts(story)
    spec = next((a["value"] for a in arts if a["type"] == "spec"), None)
    if not spec or not os.path.exists(spec):
        return "unknown"
    with open(spec, "rb") as f:
        return creflect.spec_hash_from_bytes(f.read())


def _story_signals(story_id):
    children = bd_json("children", story_id, "--json")
    tasks = [task_from_bead(b) for b in children]
    task_histories = {
        t["id"]: bd_json("history", t["id"], "--json")
        for t in tasks if t.get("step") == "build"
    }
    return cretro.derive_signals(tasks, task_histories)


def cmd_reflect(argv):
    ap = argparse.ArgumentParser(prog="tg reflect")
    ap.add_argument("id")
    ap.add_argument("--used", default="",
                    help="comma-separated spec section names you actively used")
    ap.add_argument("--skipped", default="",
                    help="comma-separated spec section names that were irrelevant")
    ap.add_argument("--guess", default="",
                    help="comma-separated spec section names where info was missing")
    ap.add_argument("--missing", action="append", default=[],
                    help="information you needed but had to infer (repeatable)")
    ap.add_argument("--noise", action="append", default=[],
                    help="content that added no signal (repeatable)")
    a = ap.parse_args(argv)

    t = get_task(a.id)
    story = t.get("parent") or a.id
    reflection = creflect.build_reflection(
        a.id, a.used, a.skipped, a.guess, a.missing, a.noise, _spec_hash(t))
    add_artifact(story, "reflection", json.dumps(reflection))
    print("reflected")
    return 0


def cmd_retro(argv):
    ap = argparse.ArgumentParser(prog="tg retro")
    ap.add_argument("epic")
    a = ap.parse_args(argv)

    children = bd_json("children", a.epic, "--json")
    stories = [task_from_bead(b) for b in children if b.get("issue_type") == "story"]

    all_reflections = []
    story_rows = []
    for story in stories:
        arts = story_artifacts(story["id"])
        refs = [art for art in arts if art["type"] == "reflection"]
        parsed = []
        for r in refs:
            try:
                parsed.append(json.loads(r["value"]))
            except (ValueError, KeyError):
                pass
        all_reflections.extend(parsed)
        sigs = _story_signals(story["id"])
        story_rows.append((story, sigs, len(parsed)))

    n = len(all_reflections)
    print("== retro: %s  (N=%d) ==" % (a.epic, n))

    if n > 0:
        agg = cretro.aggregate_reflections(all_reflections)
        section_counts = agg["section_counts"]
        missing_counts = agg["missing_counts"]
        noise_counts = agg["noise_counts"]

        if section_counts:
            print("\nSections:")
            for sec, counts in sorted(section_counts.items()):
                parts = ["%s=%d" % (v, counts[v]) for v in ("used", "skipped", "guess") if counts[v]]
                print("  %-22s  %s" % (sec, "  ".join(parts)))

        if missing_counts:
            print("\nMissing (most frequent):")
            for text, count in missing_counts.most_common():
                print("  x%d  %s" % (count, text))

        if noise_counts:
            print("\nNoise (most frequent):")
            for text, count in noise_counts.most_common():
                print("  x%d  %s" % (count, text))
    else:
        print("no reflections yet - coders call `tg reflect` before `tg done`")

    print("\nPer-story signals:")
    for story, sigs, nrefs in story_rows:
        conflict_str = "conflict" if sigs["conflict"] else "-"
        print("  %-20s  blocks=%-2d  rounds=%-2d  conflict=%-5s  (N=%d)" % (
            story["id"], sigs["blocks"], sigs["review_rounds"], conflict_str, nrefs))

    return 0
