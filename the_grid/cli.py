"""tg - the-grid domain CLI. Wires the pure core to the IO adapters; all cmd_*."""
import argparse
import json
import os
import sys
import time

from the_grid.core import flow as cflow
from the_grid.core import reflect as creflect
from the_grid.core import retro as cretro
from the_grid.core import workspace as cworkspace
from the_grid.core.contracts import (FILE_PROVIDES, optional_inputs, required_inputs,
                                 required_outputs)
from the_grid.core.logrender import render_log_line
from the_grid.core.tasks import task_from_bead

from the_grid.application.inspect import (ActiveTasks, Backlog, FlowCheck, Inbox, Mine,
                                          Queue, ShowTask, Status, Worklog)
from the_grid.application.services.flow import FlowService
from the_grid.config import ConfigError
from the_grid.container import Container

# ---- composition root -------------------------------------------------------

_container = None


def set_container(impl):
    global _container
    _container = impl


def container():
    return _container

# ---- config / roots ---------------------------------------------------------


def projects_root():
    return _container.config.projects_root()


def specs_root():
    return _container.config.specs_root()


def branch_prefix():
    return _container.config.branch_prefix()


def max_agents():
    return _container.config.max_agents()


# ---- flow assembly (IO gather -> pure decision) -----------------------------


def _flow():
    return FlowService(_container.fs, _container.store)


def load_flow():
    return _flow().load_flow()


def flow_next(step, outcome):
    return _flow().flow_next(step, outcome)


def meta_for_step(step):
    return _flow().meta_for_step(step)


def ready_roles():
    return _flow().ready_roles()


# ---- claim / advance (pure decision + bd effect) ----------------------------


def claim_next(role):
    arr = _container.store.claim_ready(role)
    if not arr:
        return None
    t = task_from_bead(arr[0])
    missing = required_inputs(meta_for_step(t["step"])) - _container.store.present_types(t)
    if missing:
        _container.store.route_to_human(t["id"],
                              "BLOCKED: missing required input(s): %s" % ", ".join(sorted(missing)),
                              role)
        return None
    return t


def advance(tid, outcome):
    t = _container.store.get_task(tid)
    nxt = flow_next(t["step"], outcome)
    if nxt is None:
        return None
    ns, no = nxt
    return _container.store.create_task(**cflow.advance_create_kwargs(t, ns, no))


# ---- worktrees (core decision + gitio effect) -------------------------------


def story_repo(story):
    return cworkspace.story_repo(_container.store.story_artifacts(story), os.path.basename(_container.config.grid_root()))


def worktree_path(story):
    return cworkspace.worktree_path(_container.fs.worktrees_dir(), story)


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
    for a in _container.store.story_artifacts(story):
        if a.get("type") == "branch":
            return a["value"]
    return None


def _ensure_branch_artifact(story, branch):
    if any(a.get("type") == "branch" for a in _container.store.story_artifacts(story)):
        return
    _container.store.add_artifact(story, "branch", branch)


def ensure_worktree(story):
    """Create (or reuse) the per-story git worktree on a feature-named branch so a
    worker never mutates the primary tree. The branch is computed once from the story
    title (its feature name) and the configured prefix, then stored as the `branch`
    artifact and reused on later claims. The target repo is resolved by name from the
    story's `repo` artifact (default: the engine itself). Idempotent: an existing
    worktree or branch is reused. Returns the workspace path, or None when no isolated
    tree can be made (not a git repo, or no origin/main to branch from)."""
    target = os.path.join(projects_root(), story_repo(story))
    if not _container.git.is_git_repo(target):
        return None
    branch = _story_branch(story) or cworkspace.branch_for(_container.store.get_task(story)["title"], branch_prefix())
    path = worktree_path(story)
    if _container.git.worktree_registered(target, path) and os.path.isdir(path):
        _ensure_branch_artifact(story, branch)
        return path
    if _container.git.branch_exists(target, branch):
        add_args = ["worktree", "add", path, branch]
    else:
        base = _container.git.worktree_base(target)
        if base is None:
            return None
        add_args = ["worktree", "add", path, "-b", branch, base]
    os.makedirs(_container.fs.worktrees_dir(), exist_ok=True)
    _ensure_worktrees_ignored(_container.config.grid_root())
    # Several pool workers may add worktrees against one target repo at once and race
    # on git's `.git/worktrees` lock; the add is idempotent, so retry the transient
    # lock failure with a short backoff before giving up.
    retries = _container.config.worktree_retries()
    backoff = _container.config.worktree_retry_sleep()
    _container.git.git(target, "worktree", "prune")
    res = _container.git.git(target, *add_args)
    while res.returncode != 0 and retries > 0 and cworkspace.is_worktree_lock_error(res.stderr):
        retries -= 1
        time.sleep(backoff)
        _container.git.git(target, "worktree", "prune")
        res = _container.git.git(target, *add_args)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        return None
    _ensure_branch_artifact(story, branch)
    return path


# ---- store guard ------------------------------------------------------------


def require_store():
    if _container.fs.store_ready():
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
        ("status", "[--json]", "all buckets at once: inbox / active / queue / blocked"),
        ("inbox", "[N]", "what needs you now: gates to clear and agents waiting on you"),
        ("backlog", "[N]", "backlog items to develop later (todo)"),
        ("mine", "", "(deprecated) use tg inbox and tg backlog"),
        ("active", "", "tasks a worker is running right now"),
        ("queue", "[N]", "the next N ready/blocked agent tasks"),
        ("ps", "[--json]", "running workers: role, task, pid, alive/dead"),
        ("logs", "<task|role|run> [-f]", "tail a worker's or the loop's log"),
        ("show", "<id>", "one task or story as JSON (artifacts, resume-state)"),
        ("trace", "<story> [--json]", "a story end to end: artifacts + child tasks + logs"),
        ("flow", "[--json]", "print and check the assembled flow (steps, routes, contracts, composition)"),
        ("worklog", "[start] [end]", "stories shipped in a period (today, yesterday, YYYY-MM-DD)"),
    ]),
    ("Drive work in", [
        ("file", "<spec> --step <step> [--repo/--epic/--project/--goal/--blocked-by]",
         "create a story (for one repo) from a spec + its first task at <step>"),
        ("link", "<story> <type> <value> [--label]", "attach an artifact to a story"),
        ("add", '"<title>" [--goal/--project]', "create a standalone human task (no spec/flow)"),
        ("close", "<story> <reason>",
         "close a story + its tasks, remove the worktree, delete the merged branch"),
    ]),
    ("Agent verbs (workers call these)", [
        ("claim", "<role>", "atomically claim the next ready task for a role"),
        ("done", "<id> <outcome> [--note \"<text>\"]", "close a task with a flow outcome and advance the chain"),
        ("block", "<id> --needs ... [--branch/--pr/--reason/--tried]",
         "escalate to a human with resume-state"),
        ("unblock", "<id>", "flip a blocked task back to its agent role so it re-claims and retries"),
        ("reflect", '<task> [--feedback "text"]',
         "record freeform feedback on the story for the retro (call before tg done)"),
    ]),
    ("Feedback loop", [
        ("retro", "<epic>", "gather child feedback + objective signals into a read digest"),
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
    set_container(Container())
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
    print(json.dumps(ShowTask(_container.store).execute(a.id), indent=2))
    return 0


def cmd_claim(argv):
    ap = argparse.ArgumentParser(prog="tg claim")
    ap.add_argument("role")
    a = ap.parse_args(argv)
    t = claim_next(a.role)
    if t is None:
        return 0
    spawnid = _container.config.spawn_id()
    if spawnid:
        _container.workers.stamp_bead(spawnid, t["id"])
    view = _container.store.task_view(t["id"])
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
    return 0 if _container.spawner.spawn_worker(a.role) else 1


def cmd_ps(argv):
    ap = argparse.ArgumentParser(prog="tg ps")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = [dict(w, alive=_container.workers.pid_alive(w.get("pid", -1))) for w in _container.workers.workers_state()]
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
        path = os.path.join(_container.config.grid_root(), "logs", "run.log")
    else:
        path = None
        for w in reversed(_container.workers.workers_state()):
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
    result = FlowCheck(_flow()).execute()
    owner, routes, an = result["owner"], result["routes"], result["analysis"]
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
    ap.add_argument("--note")
    a = ap.parse_args(argv)
    t = _container.store.get_task(a.id)
    if flow_next(t["step"], a.outcome) is None:
        sys.stderr.write(
            "no transition for step=%s outcome=%s; not closing. "
            "Fix the flow or use a defined outcome.\n" % (t["step"], a.outcome))
        return 1
    missing = required_outputs(meta_for_step(t["step"])) - _container.store.present_types(t)
    if missing:
        sys.stderr.write(
            "cannot close %s: step '%s' must produce %s; none on the story. "
            "tg link the artifact first.\n" % (a.id, t["step"], ", ".join(sorted(missing))))
        return 1
    step = t["step"]
    _container.store.note(a.id, "outcome: %s" % a.outcome)
    _container.store.close(a.id, a.outcome)
    new = advance(a.id, a.outcome)
    if a.note:
        target = new if new else a.id
        _container.store.note(target, cflow.forward_note(step, a.outcome, a.note))
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
    _container.store.update_metadata(a.id, resume)
    _container.store.note(a.id, "BLOCKED: %s" % a.needs)
    role = _container.store.get_task(a.id)["role"]
    if role and role != "human":
        _container.store.label_remove(a.id, "for:%s" % role)
    _container.store.label_add(a.id, "for:human")
    _container.store.update_status(a.id, "open")
    _container.store.assign(a.id, "")
    print("blocked -> human")
    return 0


def cmd_unblock(argv):
    ap = argparse.ArgumentParser(prog="tg unblock")
    ap.add_argument("id")
    a = ap.parse_args(argv)
    t = _container.store.get_task(a.id)
    owner, _ = load_flow()
    role = owner.get(t["step"])
    if not role or role == "human":
        sys.stderr.write(
            "nothing to unblock: step '%s' has no agent owner\n" % (t["step"] or "(none)"))
        return 1
    cur = t["role"]
    if cur and cur != role:
        _container.store.label_remove(a.id, "for:%s" % cur)
    _container.store.label_add(a.id, "for:%s" % role)
    _container.store.update_status(a.id, "open")
    _container.store.assign(a.id, "")
    print("unblocked -> %s" % role)
    return 0


def cmd_close(argv):
    ap = argparse.ArgumentParser(prog="tg close")
    ap.add_argument("story")
    ap.add_argument("reason")
    a = ap.parse_args(argv)
    target = os.path.join(projects_root(), story_repo(a.story))
    path = worktree_path(a.story)
    branch = _story_branch(a.story) or cworkspace.branch_for(_container.store.get_task(a.story)["title"], branch_prefix())
    for k in _container.store.children(a.story):
        kt = task_from_bead(k)
        if kt["status"] != "done":
            _container.store.close(kt["id"], a.reason)
    _container.store.close(a.story, a.reason)
    if _container.git.is_git_repo(target):
        _container.git.remove_worktree(target, path)
        _container.git.delete_branch(target, branch)
    print("closed %s (%s)" % (a.story, a.reason))
    return 0


def cmd_link(argv):
    ap = argparse.ArgumentParser(prog="tg link")
    ap.add_argument("story")
    ap.add_argument("type")
    ap.add_argument("value")
    ap.add_argument("--label")
    a = ap.parse_args(argv)
    _container.store.add_artifact(a.story, a.type, a.value, a.label)
    return 0


def _log_for_bead(bid):
    for w in reversed(_container.workers.workers_state()):
        if w.get("bead") == bid:
            return w.get("log")
    return None


def cmd_trace(argv):
    ap = argparse.ArgumentParser(prog="tg trace")
    ap.add_argument("story")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    story = _container.store.get_task(a.story)
    arts = _container.store.story_artifacts(a.story)
    tasks = []
    for k in _container.store.children(a.story):
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
    live = {w.get("spawnid") for w in _container.workers.workers_state()
            if w.get("spawnid") and _container.workers.pid_alive(w.get("pid", -1))}
    for bead in _container.store.list_beads_by_status("in_progress"):
        if bead.get("assignee") in live:
            continue
        bid = bead["id"]
        _container.store.update_status(bid, "open")
        _container.store.assign(bid, "")
        print("swept %s" % bid)
    pruned = _container.workers.prune_workers()
    if pruned:
        print("pruned %d dead worker entr%s" % (pruned, "y" if pruned == 1 else "ies"))
    return 0


# ---- read views -------------------------------------------------------------


def _print_mine_row(kind, t):
    plan = next((art["value"] for art in t.get("artifacts", []) if art["type"] == "plan-doc"), None)
    extra = "  plan:%s" % plan if plan else ""
    print("%-9s %s  %s%s" % ("[%s]" % kind, t["id"], t["title"] or t["step"], extra))


def cmd_inbox(argv):
    ap = argparse.ArgumentParser(prog="tg inbox")
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args(argv)
    for (kind, _outcomes), t in Inbox(_container.store, _flow()).execute(a.n):
        _print_mine_row(kind, t)
    return 0


def cmd_backlog(argv):
    ap = argparse.ArgumentParser(prog="tg backlog")
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args(argv)
    for (kind, _outcomes), t in Backlog(_container.store, _flow()).execute(a.n):
        _print_mine_row(kind, t)
    return 0


def cmd_mine(argv):
    sys.stderr.write("warning: 'tg mine' is deprecated; use 'tg inbox' and 'tg backlog'\n")
    for (kind, _outcomes), t in Mine(_container.store, _flow()).execute():
        _print_mine_row(kind, t)
    return 0


def cmd_active(argv):
    for t in ActiveTasks(_container.store).execute():
        print("  %s  %s" % (t["id"], t["title"]))
    return 0


def cmd_queue(argv):
    ap = argparse.ArgumentParser(prog="tg queue")
    ap.add_argument("n", nargs="?", type=int, default=10)
    a = ap.parse_args(argv)
    for t in Queue(_container.store).execute(a.n):
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
    ap.add_argument("--blocked-by", action="append", dest="blocked_by", metavar="ID")
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
        if not _container.git.is_git_repo(repo_path):
            pr = projects_root()
            available = sorted(
                e.name for e in os.scandir(pr) if e.is_dir() and _container.git.is_git_repo(e.path)
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
    story = _container.store.create_story(base, epic=a.epic, labels=labels or None)
    _container.store.add_artifact(story, "spec", a.spec)
    if a.repo:
        _container.store.add_artifact(story, "repo", a.repo)
    task = _container.store.create_task("%s: %s" % (a.step, base), step=a.step, role=role, parent=story)
    for blocker in (a.blocked_by or []):
        _container.store.dep_add(task, blocker)
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
    new = _container.store.create_task(a.title, labels=labels)
    print(new)
    return 0


# ---- run loop / launch ------------------------------------------------------


def _run_tick():
    cmd_sweep([])
    # The agent pool: fill up to GRID_MAX_AGENTS alive workers from the ready queue,
    # one worker per uncovered ready task, regardless of role. bd ready already hides
    # blocked-by tasks, so declared dependencies are honoured for free.
    alive = [w for w in _container.workers.workers_state() if _container.workers.pid_alive(w.get("pid", -1))]
    slots = max_agents() - len(alive)
    if slots <= 0:
        return
    # A worker that has spawned but not yet claimed (bead is None) and is still within
    # the boot window will claim one ready task of its role once it boots, so it covers
    # that task - don't double-spawn for it. claude's boot (~10-30s) far exceeds the
    # poll; without this cover the pool would pile redundant workers onto one task.
    # Past GRID_MAX_BOOT_SECONDS a stuck boot stops covering (the atomic claim keeps a
    # late extra spawn safe), so it can't wedge the queue.
    max_boot = _container.config.max_boot_seconds()
    now = time.time()
    inflight = {}
    for w in alive:
        if w.get("bead") is None and (now - w.get("started", 0)) < max_boot:
            inflight[w["role"]] = inflight.get(w["role"], 0) + 1
    ready = cflow.ready_task_roles(_container.store.ready_beads())
    for role in cflow.pool_plan(ready, inflight, slots):
        _container.spawner.spawn_worker(role)


def cmd_run(argv):
    ap = argparse.ArgumentParser(prog="tg run")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    if not require_store():
        return 1
    if a.once:
        _run_tick()
        return 0
    interval = _container.config.poll_seconds()
    print("tg run (poll %ds)" % interval)
    while True:
        _run_tick()
        time.sleep(interval)


def _human_step_skills():
    """The skill bodies of human-performed steps (a `step` but no `model:`), each as
    (step, body), ordered by step. The Driver loads all of these - it is their performer."""
    skills = []
    for role in _container.fs.step_roles():
        a = _container.fs.parse_step(role)
        if a and a["meta"].get("step") and not a["meta"].get("model"):
            skills.append((a["meta"]["step"], a["body"]))
    return sorted(skills)


def cmd_driver(argv):
    if not require_store():
        return 1
    root = _container.config.grid_root()
    seat = _container.fs.read_md("driver.md")
    if seat is None or not seat["meta"].get("model"):
        sys.stderr.write("driver.md is missing or has no 'model' in frontmatter\n")
        return 1
    body = cflow.compose_driver(seat["body"], _human_step_skills())
    os.execvp("claude", ["claude", "--model", seat["meta"]["model"], "--name", "driver",
                         "--append-system-prompt", body, "--add-dir", root,
                         "--dangerously-skip-permissions"])


def cmd_init(argv):
    argparse.ArgumentParser(prog="tg init").parse_args(argv)
    existed = _container.fs.store_ready()
    _container.store.ensure_beads()
    os.makedirs(os.path.join(_container.config.grid_root(), "logs"), exist_ok=True)
    print("grid store already initialised" if existed else "grid store initialised")
    created = _container.config.ensure_config()
    print("config %s at %s" % ("created" if created else "already exists", _container.config.config_path()))
    return 0


def cmd_config(argv):
    ap = argparse.ArgumentParser(prog="tg config")
    ap.add_argument("--edit", action="store_true")
    a = ap.parse_args(argv)
    if a.edit:
        _container.config.ensure_config()
        editor = _container.config.editor()
        os.execvp(editor, [editor, _container.config.config_path()])
    p = _container.config.config_path()
    print("config: %s" % p)
    print("exists" if os.path.exists(p) else "not found - run `tg init` to seed it")
    for key, getter in (("projects", projects_root), ("specs", specs_root)):
        try:
            print("%s: %s" % (key, getter()))
        except ConfigError:
            print("%s: (not set - run `tg init`)" % key)
    return 0


def cmd_status(argv):
    ap = argparse.ArgumentParser(prog="tg status")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    buckets = Status(_container.store).execute()
    if a.json:
        print(json.dumps(buckets, indent=2))
    else:
        for display, key in (("inbox", "mine"), ("active", "active"),
                              ("queue", "queue"), ("blocked", "blocked")):
            print("== %s (%d) ==" % (display, len(buckets[key])))
            for t in buckets[key]:
                print("  %s  %s" % (t["id"], t["title"]))
    return 0


# ---- spec feedback loop (R1, R3, R4) ----------------------------------------


def _spec_hash(task):
    story = task.get("parent") or task["id"]
    arts = _container.store.story_artifacts(story)
    spec = next((a["value"] for a in arts if a["type"] == "spec"), None)
    if not spec or not os.path.exists(spec):
        return "unknown"
    with open(spec, "rb") as f:
        return creflect.spec_hash_from_bytes(f.read())


def _story_signals(story_id):
    children = _container.store.children(story_id)
    tasks = [task_from_bead(b) for b in children]
    task_histories = {
        t["id"]: _container.store.history(t["id"])
        for t in tasks if t.get("step") == "build"
    }
    return cretro.derive_signals(tasks, task_histories)


def cmd_reflect(argv):
    ap = argparse.ArgumentParser(prog="tg reflect")
    ap.add_argument("id")
    ap.add_argument("--feedback", default="",
                    help="freeform feedback for the retro: what went well, what got in the way, "
                         "tooling friction, spec gaps - whatever is worth surfacing (your step "
                         "file says what to look for)")
    a = ap.parse_args(argv)

    t = _container.store.get_task(a.id)
    reflection = creflect.build_reflection(a.id, a.feedback, _spec_hash(t))
    _container.store.add_artifact(a.id, "reflection", json.dumps(reflection))  # on the task that gave it
    print("reflected")
    return 0


def cmd_worklog(argv):
    ap = argparse.ArgumentParser(prog="tg worklog")
    ap.add_argument("start", nargs="?")
    ap.add_argument("end", nargs="?")
    a = ap.parse_args(argv)
    import datetime as _dt
    today = _dt.date.today()
    args = [x for x in (a.start, a.end) if x is not None]
    entries = Worklog(_container.store).execute(args, today)
    if not entries:
        print("no stories shipped in that period")
        return 0
    for e in entries:
        pr = "  %s" % e["pr"] if e["pr"] else ""
        print("%s  %s  [%s]%s" % (e["id"], e["title"], e["outcome"] or "-", pr))
    return 0


def cmd_retro(argv):
    ap = argparse.ArgumentParser(prog="tg retro")
    ap.add_argument("epic")
    a = ap.parse_args(argv)

    children = _container.store.children(a.epic)
    stories = [task_from_bead(b) for b in children if b.get("issue_type") == "story"]

    def _reflections_of(bead_id):
        out = []
        for art in _container.store.story_artifacts(bead_id):
            if art.get("type") == "reflection":
                try:
                    out.append(json.loads(art["value"]))
                except (ValueError, KeyError):
                    pass
        return out

    all_reflections = []
    story_rows = []
    for story in stories:
        nrefs = 0
        for task in _container.store.children(story["id"]):  # feedback sits on the task that gave it
            refs = _reflections_of(task["id"])
            all_reflections.extend(refs)
            nrefs += len(refs)
        sigs = _story_signals(story["id"])
        story_rows.append((story, sigs, nrefs))

    # non-story epic children (e.g. the planner's plan task) reflect on themselves
    for child in children:
        if child.get("issue_type") != "story":
            all_reflections.extend(_reflections_of(child["id"]))

    n = len(all_reflections)
    print("== retro: %s  (N=%d) ==" % (a.epic, n))

    feedback = cretro.gather_feedback(all_reflections)
    if feedback:
        print("\nFeedback (read it; an analyser agent can later):")
        for item in feedback:
            print("  [%s] %s" % (item["task"], item["feedback"]))
    elif n == 0:
        print("no reflections yet - agents call `tg reflect --feedback` before `tg done`")

    print("\nPer-story signals:")
    for story, sigs, nrefs in story_rows:
        conflict_str = "conflict" if sigs["conflict"] else "-"
        print("  %-20s  blocks=%-2d  rounds=%-2d  conflict=%-5s  (N=%d)" % (
            story["id"], sigs["blocks"], sigs["review_rounds"], conflict_str, nrefs))

    return 0
