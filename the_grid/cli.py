"""tg - the-grid domain CLI. Wires the pure core to the IO adapters; all cmd_*."""
import argparse
import json
import os
import sys
import time

from the_grid.domain.contracts import FILE_PROVIDES
from the_grid.logrender import render_log_line

from the_grid.application.feedback import (ReflectInput, ReflectUseCase, RetroInput, RetroUseCase,
                                           WorklogInput, WorklogUseCase)
from the_grid.application.work import (ActiveTasksUseCase, AddTaskInput, AddTaskUseCase,
                                       BacklogInput, BacklogUseCase, CloseEpicInput,
                                       CloseEpicUseCase, CloseStoryInput,
                                       CloseStoryUseCase, EditTaskInput, EditTaskUseCase,
                                       FileStoryInput, FileStoryUseCase,
                                       InboxInput, InboxUseCase, LinkArtifactInput,
                                       LinkArtifactUseCase, QueueInput, QueueUseCase,
                                       ShowTaskInput, ShowTaskUseCase, StatusUseCase, TraceInput,
                                       TraceUseCase)
from the_grid.application.errors import UseCaseError
from the_grid.application.flow import (AdvanceInput, AdvanceTaskUseCase, BlockInput,
                                       BlockTaskUseCase, ClaimInput, ClaimTaskUseCase,
                                       CompleteInput, CompleteTaskUseCase, FlowCheckInput,
                                       FlowCheckUseCase, UnblockInput, UnblockTaskUseCase)
from the_grid.application.pool import (ListWorkersUseCase, MonitorPrsUseCase,
                                       ResolveLogInput, ResolveLogUseCase,
                                       RetroCadenceUseCase,
                                       SweepUseCase, TickInput, TickUseCase)
from the_grid.application.setup import InitGridUseCase
from the_grid.application.services.flow import FlowService
from the_grid.application.services.worktree import WorktreeService
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


# ---- flow assembly (IO gather -> pure decision) -----------------------------


def _flow():
    return FlowService(_container.fs, _container.store)


def ready_roles():
    return _flow().ready_roles()


# ---- claim / advance (pure decision + bd effect) ----------------------------


# ---- worktrees (core decision + gitio effect) -------------------------------


def _worktrees():
    return WorktreeService(_container.store, _container.git, _container.fs, _container.config)


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
        ("status", "[--json]", "all lanes at once: inbox / active / queue / blocked"),
        ("inbox", "[N]", "what needs you now: gates to clear and agents waiting on you"),
        ("backlog", "[N]", "backlog items to develop later (todo)"),
        ("active", "", "tasks a worker is running right now"),
        ("queue", "[N]", "the next N ready/blocked agent tasks"),
        ("ps", "[--all] [--json]", "running workers (alive only; --all includes dead)"),
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
        ("add", '"<title>" [--description/--goal/--project/--inbox]', "create a standalone human task (no spec/flow); --inbox surfaces it in tg inbox immediately"),
        ("edit", "<id> [--title/--description/--goal/--project/--parent]", "update a task's fields"),
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
        ("label", "<id> <label>", "add a label to a task"),
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
        ("specs-dir", "", "print the resolved specs directory (absolute path)"),
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
    view = ShowTaskUseCase(_container.store).execute(ShowTaskInput(task=a.id)).view
    print(json.dumps(view.as_dict(), indent=2))
    return 0


def cmd_claim(argv):
    ap = argparse.ArgumentParser(prog="tg claim")
    ap.add_argument("role")
    a = ap.parse_args(argv)
    resp = ClaimTaskUseCase(_container.store, _flow(), _worktrees(),
                            _container.workers, _container.config).execute(ClaimInput(role=a.role))
    if resp is None:
        return 0
    out = resp.view.as_dict()
    if resp.workspace:
        out["workspace"] = resp.workspace
    if resp.branch:
        out["branch"] = resp.branch
    if resp.spec_path:
        out["spec_path"] = resp.spec_path
    print(json.dumps(out, indent=2))
    return 0


def cmd_spawn(argv):
    ap = argparse.ArgumentParser(prog="tg spawn")
    ap.add_argument("role")
    a = ap.parse_args(argv)
    return 0 if _container.spawner.spawn_worker(a.role) else 1


def cmd_ps(argv):
    ap = argparse.ArgumentParser(prog="tg ps")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = ListWorkersUseCase(_container.workers).execute().workers
    if not a.all:
        rows = [w for w in rows if w["alive"]]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for w in rows:
            print("  %-11s task=%-18s pid=%s %s" % (
                w["role"], w.get("task") or "-", w["pid"], "alive" if w["alive"] else "dead"))
    return 0


def cmd_logs(argv):
    ap = argparse.ArgumentParser(prog="tg logs")
    ap.add_argument("target")
    ap.add_argument("-f", action="store_true")
    a = ap.parse_args(argv)
    path = ResolveLogUseCase(_container.workers, _container.config).execute(
        ResolveLogInput(target=a.target)).path
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
    resp = AdvanceTaskUseCase(_container.store, _flow()).execute(
        AdvanceInput(task=a.id, outcome=a.outcome))
    if resp.next_task:
        print(resp.next_task)
    return 0


def cmd_ready_roles(argv):
    print(" ".join(ready_roles()))
    return 0


def cmd_specs_dir(argv):
    argparse.ArgumentParser(prog="tg specs-dir").parse_args(argv)
    print(_container.config.specs_root())
    return 0


def cmd_flow(argv):
    ap = argparse.ArgumentParser(prog="tg flow")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    resp = FlowCheckUseCase(_flow()).execute(FlowCheckInput())
    owner, routes, an = resp.owner, resp.routes, resp.analysis
    steps, req, opt, prod = an["steps"], an["req"], an["opt"], an["prod"]
    entries, terminals = an["entries"], an["terminals"]
    unreachable, missing, dups, ok = an["unreachable"], an["missing"], an["dups"], an["ok"]

    hooks = resp.hooks
    if a.json:
        print(json.dumps({"owner": owner, "routes": routes,
                          "accepts": {s: {"required": sorted(req[s]),
                                          "optional": sorted(opt[s])} for s in steps},
                          "produces": {s: sorted(prod[s]) for s in steps},
                          "entries": entries, "terminals": terminals,
                          "hooks": hooks,
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
    if hooks:
        print("on_* hooks:")
        for hook, hook_steps in hooks.items():
            print("  %s -> %s" % (hook, ", ".join(hook_steps)))
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
    ap.add_argument("--note", nargs="+",
                    help="a note to forward to the next task; unquoted multi-word is fine")
    a = ap.parse_args(argv)
    note = " ".join(a.note) if a.note else None
    try:
        resp = CompleteTaskUseCase(_container.store, _flow()).execute(
            CompleteInput(task=a.id, outcome=a.outcome, note=note))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if resp.next_task:
        print(resp.next_task)
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
    BlockTaskUseCase(_container.store).execute(BlockInput(
        task=a.id, needs=a.needs, branch=a.branch, pr=a.pr, reason=a.reason, tried=a.tried))
    print("blocked -> human")
    return 0


def cmd_unblock(argv):
    ap = argparse.ArgumentParser(prog="tg unblock")
    ap.add_argument("id")
    a = ap.parse_args(argv)
    try:
        resp = UnblockTaskUseCase(_container.store, _flow()).execute(UnblockInput(task=a.id))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print("unblocked -> %s" % resp.role)
    return 0


def cmd_close(argv):
    ap = argparse.ArgumentParser(prog="tg close")
    ap.add_argument("story")
    ap.add_argument("reason")
    a = ap.parse_args(argv)
    children = _container.store.children(a.story)
    is_epic = any(c.type == "story" for c in children)
    try:
        if is_epic:
            resp = CloseEpicUseCase(_container.store, _flow()).execute(
                CloseEpicInput(epic=a.story, reason=a.reason))
        else:
            CloseStoryUseCase(_container.store, _worktrees()).execute(
                CloseStoryInput(story=a.story, reason=a.reason))
            resp = None
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print("closed %s (%s)" % (a.story, a.reason))
    if resp is not None:
        _print_retro(resp.retro)
    return 0


def cmd_link(argv):
    ap = argparse.ArgumentParser(prog="tg link")
    ap.add_argument("story")
    ap.add_argument("type")
    ap.add_argument("value")
    ap.add_argument("--label")
    a = ap.parse_args(argv)
    LinkArtifactUseCase(_container.store).execute(
        LinkArtifactInput(story=a.story, atype=a.type, value=a.value, label=a.label))
    return 0


def cmd_trace(argv):
    ap = argparse.ArgumentParser(prog="tg trace")
    ap.add_argument("story")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    resp = TraceUseCase(_container.store, _container.workers).execute(TraceInput(story=a.story))
    if a.json:
        print(json.dumps(resp.as_dict(), indent=2))
    else:
        print("story %s  %s  [%s]" % (resp.story.id, resp.story.title, resp.story.status))
        for art in resp.artifacts:
            print("  artifact %s: %s" % (art.type, art.value))
        for t in resp.tasks:
            log = "  log:" + t.log if t.log else ""
            print("  task %s  %s  [%s]%s" % (t.id, t.step or "-", t.status, log))
    return 0


def cmd_sweep(argv):
    result = SweepUseCase(_container.store, _container.workers).execute()
    for bid in result.swept:
        print("swept %s" % bid)
    if result.pruned:
        print("pruned %d dead worker entr%s" % (result.pruned, "y" if result.pruned == 1 else "ies"))
    return 0


# ---- read views -------------------------------------------------------------


def _print_human_row(kind, t, show_description=False):
    plan = next((art.value for art in t.artifacts if art.type == "plan-doc"), None)
    extra = "  plan:%s" % plan if plan else ""
    if show_description and t.description:
        snippet = t.description[:60] + ("..." if len(t.description) > 60 else "")
        extra += "  desc:%s" % snippet
    print("%-9s %s  %s%s" % ("[%s]" % kind, t.id, t.title or t.step, extra))


def cmd_inbox(argv):
    ap = argparse.ArgumentParser(prog="tg inbox")
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args(argv)
    resp = InboxUseCase(_container.store, _flow()).execute(InboxInput(n=a.n))
    for row in resp.rows:
        _print_human_row(row.kind, row.task)
    if resp.candidate_epics:
        print("close-candidate epics:")
        for e in resp.candidate_epics:
            print("  %s  %s (%d %s closed)  -- tg close %s <reason>"
                  % (e.id, e.title, e.closed_story_count,
                     "story" if e.closed_story_count == 1 else "stories", e.id))
    return 0


def cmd_backlog(argv):
    ap = argparse.ArgumentParser(prog="tg backlog")
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args(argv)
    for row in BacklogUseCase(_container.store, _flow()).execute(BacklogInput(n=a.n)).rows:
        _print_human_row(row.kind, row.task, show_description=True)
    return 0


def cmd_active(argv):
    for t in ActiveTasksUseCase(_container.store).execute().tasks:
        print("  %s  %s" % (t.id, t.title))
    return 0


def cmd_queue(argv):
    ap = argparse.ArgumentParser(prog="tg queue")
    ap.add_argument("n", nargs="?", type=int, default=10)
    a = ap.parse_args(argv)
    for t in QueueUseCase(_container.store).execute(QueueInput(n=a.n)).tasks:
        print("  %-8s %s  %s" % (t.status, t.id, t.title))
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
    try:
        resp = FileStoryUseCase(_container.store, _flow(), _container.git, _container.fs,
                                _container.config).execute(FileStoryInput(
            spec=a.spec, step=a.step, epic=a.epic, project=a.project, goal=a.goal,
            repo=a.repo, blocked_by=a.blocked_by))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print(resp.story)
    return 0


def cmd_add(argv):
    ap = argparse.ArgumentParser(prog="tg add")
    ap.add_argument("title")
    ap.add_argument("--goal")
    ap.add_argument("--project")
    ap.add_argument("--description")
    ap.add_argument("--inbox", action="store_true", dest="attention")
    a = ap.parse_args(argv)
    resp = AddTaskUseCase(_container.store).execute(
        AddTaskInput(title=a.title, goal=a.goal, project=a.project, description=a.description,
                     attention=a.attention))
    print(resp.task)
    return 0


def cmd_edit(argv):
    ap = argparse.ArgumentParser(prog="tg edit")
    ap.add_argument("id")
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--goal")
    ap.add_argument("--project")
    ap.add_argument("--parent")
    a = ap.parse_args(argv)
    EditTaskUseCase(_container.store).execute(
        EditTaskInput(task=a.id, title=a.title, description=a.description,
                      goal=a.goal, project=a.project, parent=a.parent))
    return 0


# ---- run loop / launch ------------------------------------------------------


def _render_tick(result):
    for sid in result.merged:
        print("merged %s" % sid)
    for sid in result.abandoned:
        print("abandoned %s" % sid)
    for sid in result.reworked:
        print("rework %s" % sid)
    for sid in result.conflicted:
        print("conflicted %s" % sid)
    for bid in result.swept:
        print("swept %s" % bid)
    if result.pruned:
        print("pruned %d dead worker entr%s" % (result.pruned, "y" if result.pruned == 1 else "ies"))


def cmd_run(argv):
    ap = argparse.ArgumentParser(prog="tg run")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    if not require_store():
        return 1
    flow_service = _flow()
    flow = flow_service.load_flow()
    complete = CompleteTaskUseCase(_container.store, flow_service)
    monitor = MonitorPrsUseCase(_container.store, _container.github, _worktrees(), flow, complete)
    cadence_gate = RetroCadenceUseCase(_container.store, flow_service, _container.config)
    tick = TickUseCase(_container.store, _container.workers, _container.spawner, _container.config,
                       monitor=monitor, cadence_gate=cadence_gate)
    if a.once:
        _render_tick(tick.execute(TickInput(now=time.time())))
        return 0
    interval = _container.config.poll_seconds()
    print("tg run (poll %ds)" % interval)
    while True:
        _render_tick(tick.execute(TickInput(now=time.time())))
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


def _compose_driver(base_body, skills):
    """The Driver's system prompt: its base persona (driver.md) plus a skill per
    human-performed step. The Driver is the performer of human-facing steps, so it
    carries their procedures. skills is a list of (step, body), already ordered."""
    if not skills:
        return base_body
    parts = [base_body,
             "\n\n# Skills for human-facing steps\n",
             "These steps surface in `tg inbox`. When the human picks one, run the skill "
             "for its step: assist them, and record the outcome (`tg done` / `tg close`).\n"]
    for step, body in skills:
        parts.append("\n## %s\n\n%s" % (step, body.strip()))
    return "\n".join(parts)


def cmd_driver(argv):
    if not require_store():
        return 1
    root = _container.config.grid_root()
    seat = _container.fs.read_md("driver.md")
    if seat is None or not seat["meta"].get("model"):
        sys.stderr.write("driver.md is missing or has no 'model' in frontmatter\n")
        return 1
    body = _compose_driver(seat["body"], _human_step_skills())
    os.execvp("claude", ["claude", "--model", seat["meta"]["model"], "--name", "driver",
                         "--append-system-prompt", body, "--add-dir", root,
                         "--dangerously-skip-permissions"])


def cmd_init(argv):
    argparse.ArgumentParser(prog="tg init").parse_args(argv)
    r = InitGridUseCase(_container.store, _container.fs, _container.config).execute()
    print("grid store already initialised" if r.existed else "grid store initialised")
    print("config %s at %s" % ("created" if r.created else "already exists", r.config_path))
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
    lanes = StatusUseCase(_container.store).execute().lanes
    if a.json:
        print(json.dumps({k: [t.as_dict() for t in v] for k, v in lanes.items()}, indent=2))
    else:
        for key in ("inbox", "active", "queue", "blocked"):
            print("== %s (%d) ==" % (key, len(lanes[key])))
            for t in lanes[key]:
                print("  %s  %s" % (t.id, t.title))
    return 0


# ---- spec feedback loop ------------------------------------------------------


def cmd_label(argv):
    ap = argparse.ArgumentParser(prog="tg label")
    ap.add_argument("id")
    ap.add_argument("label")
    a = ap.parse_args(argv)
    _container.store.label_add(a.id, a.label)
    return 0


def cmd_reflect(argv):
    ap = argparse.ArgumentParser(prog="tg reflect")
    ap.add_argument("id")
    ap.add_argument("--feedback", default="",
                    help="freeform feedback for the retro: what went well, what got in the way, "
                         "tooling friction, spec gaps - whatever is worth surfacing (your step "
                         "file says what to look for)")
    a = ap.parse_args(argv)
    ReflectUseCase(_container.store, _container.fs).execute(
        ReflectInput(task=a.id, feedback=a.feedback))
    print("reflected")
    return 0


def cmd_worklog(argv):
    ap = argparse.ArgumentParser(prog="tg worklog")
    ap.add_argument("start", nargs="?")
    ap.add_argument("end", nargs="?")
    a = ap.parse_args(argv)
    import datetime as _dt
    now = _dt.datetime.now().astimezone()
    today, tz = now.date(), now.tzinfo
    args = [x for x in (a.start, a.end) if x is not None]
    resp = WorklogUseCase(_container.store).execute(
        WorklogInput(period_args=args, today=today, tz=tz))
    if not resp.entries:
        print("no stories shipped in that period")
        return 0
    for e in resp.entries:
        pr = "  %s" % e.pr if e.pr else ""
        print("%s  %s  [%s]%s" % (e.id, e.title, e.outcome or "-", pr))
    return 0


def _print_retro(resp):
    print("== retro: %s  (N=%d) ==" % (resp.subject, resp.reflection_count))
    if resp.feedback:
        print("\nFeedback (read it; an analyser agent can later):")
        for item in resp.feedback:
            print("  [%s] %s" % (item.task, item.text))
    elif resp.reflection_count == 0:
        print("no reflections yet - agents call `tg reflect --feedback` before `tg done`")
    print("\nPer-story signals:")
    for row in resp.story_signals:
        sig_str = "  ".join("%s=%s" % (k, row.signals[k]) for k in sorted(row.signals))
        print("  %-20s  %s  (N=%d)" % (row.story.id, sig_str, row.reflections))


def cmd_retro(argv):
    ap = argparse.ArgumentParser(prog="tg retro")
    ap.add_argument("id", nargs="?", default=None, help="story or epic id")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="aggregate tasks closed on/after date")
    ap.add_argument("--last", type=int, metavar="N", help="aggregate last N closed epics")
    a = ap.parse_args(argv)

    flags = [a.id is not None, a.since is not None, a.last is not None]
    if sum(flags) != 1:
        ap.error("provide exactly one of: <id>, --since, --last")

    inp = RetroInput(subject=a.id, since=a.since, last=a.last)
    resp = RetroUseCase(_container.store, _flow()).execute(inp)
    _print_retro(resp)
    return 0
