import argparse
import json
import os
import signal
import sys
import time

from lightcycle.banner import show_banner
from lightcycle.domain.contracts import FILE_PROVIDES
from lightcycle.logrender import render_log_line

from lightcycle.application.feedback import (
    ReflectInput,
    ReflectUseCase,
    RetroInput,
    RetroUseCase,
    WorklogInput,
    WorklogUseCase,
)
from lightcycle.application.work import (
    ActiveStepsUseCase,
    AddItemInput,
    AddItemUseCase,
    BacklogInput,
    BacklogUseCase,
    CloseThemeInput,
    CloseThemeUseCase,
    CloseItemInput,
    CloseItemUseCase,
    EditNodeInput,
    EditNodeUseCase,
    FileItemInput,
    FileItemUseCase,
    InboxInput,
    InboxUseCase,
    LinkArtifactInput,
    LinkArtifactUseCase,
    OpenThemeInput,
    OpenThemeUseCase,
    QueueInput,
    QueueUseCase,
    ShowNodeInput,
    ShowNodeUseCase,
    StatusUseCase,
    TraceInput,
    TraceUseCase,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import (
    AdvanceInput,
    AdvanceStepUseCase,
    BlockInput,
    BlockStepUseCase,
    ClaimInput,
    ClaimStepUseCase,
    CompleteInput,
    CompleteStepUseCase,
    FlowCheckInput,
    FlowCheckUseCase,
    UnblockInput,
    UnblockStepUseCase,
)
from lightcycle.application.pool import (
    AcquireRunLockUseCase,
    BreakerGateUseCase,
    HookCompletionsUseCase,
    ListWorkersUseCase,
    MonitorPrsUseCase,
    ReleaseRunLockUseCase,
    ResolveLogInput,
    ResolveLogUseCase,
    RetroCadenceUseCase,
    SweepUseCase,
    TickInput,
    TickUseCase,
)
from lightcycle.application.setup import (
    InitGridUseCase,
    InitProjectInput,
    InitProjectUseCase,
    migrate_legacy,
)
from lightcycle.application.services.flow import FlowService
from lightcycle.application.services.worktree import WorktreeService
from lightcycle.config import Config, ConfigError
from lightcycle.container import Container


_container = None


def set_container(impl):
    global _container
    _container = impl


def container():
    return _container


def projects_root():
    return _container.config.projects_root()


def specs_root():
    return _container.config.specs_root()


def _flow():
    return FlowService(_container.fs, _container.store, _container.config)


def ready_roles():
    return _flow().ready_roles()


def _worktrees():
    return WorktreeService(_container.store, _container.git, _container.fs, _container.config)


def require_store():
    if _container.fs.store_ready():
        return True
    sys.stderr.write("no lightcycle store here - run `lc init` first.\n")
    return False


COMMAND_GROUPS = [
    ("Setup", [
        ("init", "[<project>]", "no arg: create the lightcycle store + seed the HOME config (run once). "
         "<project>: scaffold that project's .lightcycle/ (workflows, config with a shortcode)"),
        ("config", "[--edit]", "show or edit the lightcycle config (projects + specs roots)"),
        ("migrate", "", "one-time: move a legacy ~/.grid or ~/.config layout into ~/.lightcycle"),
    ]),
    ("Start working", [
        ("start", "[--once]", "the agent pool: each tick, sweep stale claims, then fill up to LC_MAX_AGENTS (default 4) workers from the ready queue"),
        ("driver", "", "open the interactive driver - your seat to shape and file work"),
    ]),
    ("See what's happening", [
        ("status", "[--json]", "all lanes at once: inbox / active / queue / blocked"),
        ("inbox", "[N]", "what needs you now: gates to clear and agents waiting on you"),
        ("backlog", "[N]", "backlog items to develop later (todo)"),
        ("active", "", "steps a worker is running right now"),
        ("queue", "[N]", "the next N ready/blocked agent steps"),
        ("ps", "[--all] [--json]", "running workers (alive only; --all includes dead)"),
        ("logs", "<step|role|run> [-f]", "tail a worker's or the loop's log"),
        ("show", "<id>", "one step or item as JSON (artifacts, resume-state)"),
        ("trace", "<item> [--json]", "an item end to end: artifacts + child steps + logs"),
        ("flow", "[--json]", "print and check the assembled flow (steps, routes, contracts, composition)"),
        ("worklog", "[start] [end]", "items shipped in a period (today, yesterday, YYYY-MM-DD)"),
    ]),
    ("Drive work in", [
        ("theme", '"<objective>" [--workflow <w>] [--backlog <id>] [--project <p>]',
         "open a theme: the objective container an item files under (--workflow sets its pipeline)"),
        ("file", "<spec> --theme <id> [--step <s>] [--workflow <w>] [--repo/--project/--goal/--blocked-by]",
         "create an item from a spec + its first step (step/workflow default to the theme's)"),
        ("link", "<item> <type> <value> [--label]", "attach an artifact to an item"),
        ("add", '"<title>" [--description/--goal/--project/--inbox]', "create a standalone human step (no spec/flow); --inbox surfaces it in lc inbox immediately"),
        ("edit", "<id> [--title/--description/--goal/--project/--parent]", "update a step's fields"),
        ("close", "<item> <reason>",
         "close an item + its steps, remove the worktree, delete the merged branch"),
    ]),
    ("Agent verbs (workers call these)", [
        ("claim", "<role>", "atomically claim the next ready step for a role"),
        ("done", "<id> <outcome> [--note \"<text>\"]", "close a step with a flow outcome and advance the chain"),
        ("block", "<id> --needs ... [--branch/--pr/--reason/--tried]",
         "escalate to a human with resume-state"),
        ("unblock", "<id>", "flip a blocked step back to its agent role so it re-claims and retries"),
        ("reflect", '<step> [--feedback "text"]',
         "record freeform feedback on the item for the retro (call before lc done)"),
        ("label", "<id> <label>", "add a label to a step"),
    ]),
    ("Feedback loop", [
        ("retro", "<theme>", "gather child feedback + objective signals into a read digest"),
    ]),
    ("Maintenance", [
        ("sweep", "", "reclaim orphaned step claims and prune dead worker entries (kept: LC_WORKER_HISTORY, default 20)"),
    ]),
    ("Plumbing (the loop uses these)", [
        ("advance", "<id> <outcome>", "create the next step for an outcome without closing"),
        ("ready-roles", "", "list roles that have a ready step"),
        ("spawn", "<role>", "spawn one worker for a role"),
        ("specs-dir", "", "print the resolved specs directory (absolute path)"),
    ]),
]

VERBS = tuple(verb for _, cmds in COMMAND_GROUPS for verb, _, _ in cmds)


def print_help():
    print("lc - lightcycle domain CLI\n")
    print("Usage: lc <command> [args]\n")
    width = min(
        34,
        max(
            len(("%s %s" % (v, args)).rstrip()) for _, cmds in COMMAND_GROUPS for v, args, _ in cmds
        ),
    )
    for group, cmds in COMMAND_GROUPS:
        print("%s:" % group)
        for verb, args, desc in cmds:
            print("  %-*s  %s" % (width, ("%s %s" % (verb, args)).rstrip(), desc))
        print("")


def cmd_migrate(argv):
    argparse.ArgumentParser(prog="lc migrate").parse_args(argv)
    resp = migrate_legacy(Config())
    if resp.already:
        print("already on the ~/.lightcycle layout - nothing to migrate")
    elif resp.nothing:
        print("no legacy layout found - nothing to migrate")
    else:
        print("migrated into ~/.lightcycle: %s (store backed up to %s)"
              % (", ".join(resp.moved), resp.backup))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "migrate":
        return cmd_migrate(argv[1:])
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


def cmd_show(argv):
    ap = argparse.ArgumentParser(prog="lc show")
    ap.add_argument("id")
    a = ap.parse_args(argv)
    view = ShowNodeUseCase(_container.store).execute(ShowNodeInput(step=a.id)).view
    print(json.dumps(view.as_dict(), indent=2))
    return 0


def cmd_claim(argv):
    ap = argparse.ArgumentParser(prog="lc claim")
    ap.add_argument("role")
    a = ap.parse_args(argv)
    resp = ClaimStepUseCase(
        _container.store, _flow(), _worktrees(), _container.workers, _container.config
    ).execute(ClaimInput(role=a.role))
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
    ap = argparse.ArgumentParser(prog="lc spawn")
    ap.add_argument("role")
    a = ap.parse_args(argv)
    return 0 if _container.spawner.spawn_worker(a.role) else 1


def cmd_ps(argv):
    ap = argparse.ArgumentParser(prog="lc ps")
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
            print(
                "  %-11s step=%-18s pid=%s %s"
                % (w["role"], w.get("step") or "-", w["pid"], "alive" if w["alive"] else "dead")
            )
    return 0


def cmd_logs(argv):
    ap = argparse.ArgumentParser(prog="lc logs")
    ap.add_argument("target")
    ap.add_argument("-f", action="store_true")
    a = ap.parse_args(argv)
    path = (
        ResolveLogUseCase(_container.workers, _container.config)
        .execute(ResolveLogInput(target=a.target))
        .path
    )
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
    ap = argparse.ArgumentParser(prog="lc advance")
    ap.add_argument("id")
    ap.add_argument("outcome")
    a = ap.parse_args(argv)
    resp = AdvanceStepUseCase(_container.store, _flow()).execute(
        AdvanceInput(step=a.id, outcome=a.outcome)
    )
    if resp.next_step:
        print(resp.next_step)
    return 0


def cmd_ready_roles(argv):
    print(" ".join(ready_roles()))
    return 0


def cmd_specs_dir(argv):
    argparse.ArgumentParser(prog="lc specs-dir").parse_args(argv)
    print(_container.config.specs_root())
    return 0


def cmd_flow(argv):
    ap = argparse.ArgumentParser(prog="lc flow")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    resp = FlowCheckUseCase(_flow()).execute(FlowCheckInput())
    owner, routes, an = resp.owner, resp.routes, resp.analysis
    steps, req, opt, prod = an["steps"], an["req"], an["opt"], an["prod"]
    entries, terminals = an["entries"], an["terminals"]
    unreachable, missing, dups, ok = an["unreachable"], an["missing"], an["dups"], an["ok"]

    hooks = resp.hooks
    if a.json:
        print(
            json.dumps(
                {
                    "owner": owner,
                    "routes": routes,
                    "accepts": {
                        s: {"required": sorted(req[s]), "optional": sorted(opt[s])} for s in steps
                    },
                    "produces": {s: sorted(prod[s]) for s in steps},
                    "entries": entries,
                    "terminals": terminals,
                    "hooks": hooks,
                    "unreachable": unreachable,
                    "missing_inputs": missing,
                    "conflicts": dups,
                    "ok": ok,
                },
                indent=2,
            )
        )
        return 0 if ok else 1

    for s in steps:
        print("%s  (%s)" % (s, owner[s]))
        accepts = [t + " (required)" for t in sorted(req[s])] + [
            t + " (optional)" for t in sorted(opt[s])
        ]
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
        sys.stderr.write(
            "warning: no entry step (none requires only %s)\n" % ", ".join(sorted(FILE_PROVIDES))
        )
    if hooks:
        print("on_* hooks:")
        for hook, hook_steps in hooks.items():
            print("  %s -> %s" % (hook, ", ".join(hook_steps)))
    for s, miss in sorted(missing.items()):
        sys.stderr.write(
            "composition: step '%s' needs %s, not guaranteed upstream\n" % (s, ", ".join(miss))
        )
    for s in unreachable:
        sys.stderr.write("warning: step '%s' is unreachable from any entry\n" % s)
    for d in dups:
        sys.stderr.write("conflict: %s\n" % d)
    return 0 if ok else 1


def cmd_done(argv):
    ap = argparse.ArgumentParser(prog="lc done")
    ap.add_argument("id")
    ap.add_argument("outcome")
    ap.add_argument(
        "--note", nargs="+", help="a note to forward to the next step; unquoted multi-word is fine"
    )
    a = ap.parse_args(argv)
    note = " ".join(a.note) if a.note else None
    try:
        resp = CompleteStepUseCase(_container.store, _flow()).execute(
            CompleteInput(step=a.id, outcome=a.outcome, note=note)
        )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if resp.next_step:
        print(resp.next_step)
    return 0


def cmd_block(argv):
    ap = argparse.ArgumentParser(prog="lc block")
    ap.add_argument("id")
    for opt in ("branch", "pr", "reason", "tried", "needs"):
        ap.add_argument("--%s" % opt)
    a = ap.parse_args(argv)
    if not a.needs:
        sys.stderr.write("lc block requires --needs (what the human must decide/provide)\n")
        return 2
    BlockStepUseCase(_container.store).execute(
        BlockInput(
            step=a.id, needs=a.needs, branch=a.branch, pr=a.pr, reason=a.reason, tried=a.tried
        )
    )
    print("blocked -> human")
    return 0


def cmd_unblock(argv):
    ap = argparse.ArgumentParser(prog="lc unblock")
    ap.add_argument("id")
    a = ap.parse_args(argv)
    try:
        resp = UnblockStepUseCase(_container.store, _flow()).execute(UnblockInput(step=a.id))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print("unblocked -> %s" % resp.role)
    return 0


def cmd_close(argv):
    ap = argparse.ArgumentParser(prog="lc close")
    ap.add_argument("item")
    ap.add_argument("reason")
    a = ap.parse_args(argv)
    children = _container.store.children(a.item)
    is_epic = _container.store.get_node(a.item).type == "theme" or any(
        c.type == "item" for c in children
    )
    try:
        if is_epic:
            resp = CloseThemeUseCase(_container.store, _flow()).execute(
                CloseThemeInput(theme=a.item, reason=a.reason)
            )
        else:
            CloseItemUseCase(_container.store, _worktrees()).execute(
                CloseItemInput(item=a.item, reason=a.reason)
            )
            resp = None
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print("closed %s (%s)" % (a.item, a.reason))
    if resp is not None:
        _print_retro(resp.retro)
    return 0


def cmd_link(argv):
    ap = argparse.ArgumentParser(prog="lc link")
    ap.add_argument("item")
    ap.add_argument("type")
    ap.add_argument("value")
    ap.add_argument("--label")
    a = ap.parse_args(argv)
    LinkArtifactUseCase(_container.store).execute(
        LinkArtifactInput(item=a.item, atype=a.type, value=a.value, label=a.label)
    )
    return 0


def cmd_trace(argv):
    ap = argparse.ArgumentParser(prog="lc trace")
    ap.add_argument("item")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    resp = TraceUseCase(_container.store, _container.workers).execute(TraceInput(item=a.item))
    if a.json:
        print(json.dumps(resp.as_dict(), indent=2))
    else:
        print("item %s  %s  [%s]" % (resp.item.id, resp.item.title, resp.item.status))
        for art in resp.artifacts:
            print("  artifact %s: %s" % (art.type, art.value))
        for t in resp.steps:
            log = "  log:" + t.log if t.log else ""
            print("  step %s  %s  [%s]%s" % (t.id, t.step or "-", t.status, log))
    return 0


def cmd_sweep(argv):
    result = SweepUseCase(_container.store, _container.workers).execute(
        time.time(), _container.config.max_boot_seconds()
    )
    for bid in result.swept:
        print("swept %s" % bid)
    for spawnid in result.killed:
        print("killed %s" % spawnid)
    if result.pruned:
        print(
            "pruned %d dead worker entr%s" % (result.pruned, "y" if result.pruned == 1 else "ies")
        )
    return 0


def _print_human_row(kind, t, show_description=False):
    plan = next((art.value for art in t.artifacts if art.type == "plan-doc"), None)
    extra = "  plan:%s" % plan if plan else ""
    if show_description and t.description:
        snippet = t.description[:60] + ("..." if len(t.description) > 60 else "")
        extra += "  desc:%s" % snippet
    print("%-9s %s  %s%s" % ("[%s]" % kind, t.id, t.title or t.step, extra))


def cmd_inbox(argv):
    ap = argparse.ArgumentParser(prog="lc inbox")
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args(argv)
    resp = InboxUseCase(_container.store, _flow()).execute(InboxInput(now=time.time(), n=a.n))
    for row in resp.rows:
        _print_human_row(row.kind, row.step)
    if resp.candidate_epics:
        print("close-candidate themes:")
        for e in resp.candidate_epics:
            print(
                "  %s  %s (%d %s closed)  -- lc close %s <reason>"
                % (
                    e.id,
                    e.title,
                    e.closed_item_count,
                    "item" if e.closed_item_count == 1 else "items",
                    e.id,
                )
            )
    return 0


def cmd_backlog(argv):
    ap = argparse.ArgumentParser(prog="lc backlog")
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args(argv)
    for row in BacklogUseCase(_container.store, _flow()).execute(BacklogInput(n=a.n)).rows:
        _print_human_row(row.kind, row.step, show_description=True)
    return 0


def cmd_active(argv):
    for t in ActiveStepsUseCase(_container.store).execute().steps:
        print("  %s  %s" % (t.id, t.title))
    return 0


def cmd_queue(argv):
    ap = argparse.ArgumentParser(prog="lc queue")
    ap.add_argument("n", nargs="?", type=int, default=10)
    a = ap.parse_args(argv)
    for t in QueueUseCase(_container.store).execute(QueueInput(n=a.n)).steps:
        print("  %-8s %s  %s" % (t.status, t.id, t.title))
    return 0


def cmd_theme(argv):
    ap = argparse.ArgumentParser(prog="lc theme")
    ap.add_argument("objective")
    ap.add_argument("--backlog")
    ap.add_argument("--project")
    ap.add_argument("--workflow")
    a = ap.parse_args(argv)
    try:
        resp = OpenThemeUseCase(_container.store).execute(
            OpenThemeInput(
                objective=a.objective, backlog=a.backlog, project=a.project, workflow=a.workflow
            )
        )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print(resp.theme)
    return 0


def cmd_file(argv):
    ap = argparse.ArgumentParser(prog="lc file")
    ap.add_argument("spec")
    ap.add_argument("--theme", required=True)
    ap.add_argument("--step")
    ap.add_argument("--workflow")
    ap.add_argument("--project")
    ap.add_argument("--goal")
    ap.add_argument("--repo")
    ap.add_argument("--blocked-by", action="append", dest="blocked_by", metavar="ID")
    a = ap.parse_args(argv)
    try:
        resp = FileItemUseCase(
            _container.store, _flow(), _container.git, _container.fs, _container.config
        ).execute(
            FileItemInput(
                spec=a.spec,
                step=a.step,
                workflow=a.workflow,
                theme=a.theme,
                project=a.project,
                goal=a.goal,
                repo=a.repo,
                blocked_by=a.blocked_by,
            )
        )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print(resp.item)
    return 0


def cmd_add(argv):
    ap = argparse.ArgumentParser(prog="lc add")
    ap.add_argument("title")
    ap.add_argument("--goal")
    ap.add_argument("--project")
    ap.add_argument("--description")
    ap.add_argument("--inbox", action="store_true", dest="attention")
    a = ap.parse_args(argv)
    resp = AddItemUseCase(_container.store).execute(
        AddItemInput(title=a.title, goal=a.goal, project=a.project, description=a.description,
                     attention=a.attention))
    print(resp.step)
    return 0


def cmd_edit(argv):
    ap = argparse.ArgumentParser(prog="lc edit")
    ap.add_argument("id")
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--goal")
    ap.add_argument("--project")
    ap.add_argument("--parent")
    a = ap.parse_args(argv)
    EditNodeUseCase(_container.store).execute(
        EditNodeInput(
            step=a.id,
            title=a.title,
            description=a.description,
            goal=a.goal,
            project=a.project,
            parent=a.parent,
        )
    )
    return 0


def _format_tick(result, prev_snapshot, now):
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    lines = []
    for role in result.spawned:
        lines.append("%s  %-7s  %s" % (ts, "spawn", role))
    for sid in result.merged:
        lines.append("%s  %-7s  %s" % (ts, "merge", sid))
    for sid in result.abandoned:
        lines.append("%s  %-7s  %s" % (ts, "abandon", sid))
    for sid in result.reworked:
        lines.append("%s  %-7s  %s" % (ts, "rework", sid))
    for sid in result.conflicted:
        lines.append("%s  %-7s  %s" % (ts, "conflict", sid))
    for bid in result.swept:
        lines.append("%s  %-7s  %s" % (ts, "sweep", bid))
    for step, tid, detail in result.hook_completed:
        msg = "%s: %s" % (tid, detail) if detail else tid
        lines.append("%s  %-7s  %s" % (ts, step, msg))
    if result.breaker_opened:
        reset_ts = time.strftime("%H:%M:%S", time.localtime(result.breaker_reset_at))
        lines.append("%s  %-7s  %s" % (ts, "breaker", "opened until %s" % reset_ts))
    if result.breaker_closed:
        lines.append("%s  %-7s  %s" % (ts, "breaker", "closed"))
    cur = (result.alive, result.max_agents, result.ready, result.inflight_count)
    if cur != prev_snapshot or result.pruned:
        state = "active=%d/%d ready=%d inflight=%d" % (
            result.alive, result.max_agents, result.ready, result.inflight_count)
        if result.pruned:
            state += " pruned=%d" % result.pruned
        lines.append("%s  %-7s  %s" % (ts, "state", state))
    return lines, cur


def cmd_start(argv):
    ap = argparse.ArgumentParser(prog="lc start")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    if not require_store():
        return 1
    lock_result = AcquireRunLockUseCase(_container.lock).execute()
    if not lock_result.acquired:
        sys.stderr.write("lc start already running, pid %d\n" % lock_result.holder_pid)
        return 1

    def _stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    try:
        flow_service = _flow()
        flow = flow_service.load_flow()
        complete = CompleteStepUseCase(_container.store, flow_service)
        monitor = MonitorPrsUseCase(
            _container.store, _container.github, _worktrees(), flow, complete
        )
        cadence_gate = RetroCadenceUseCase(_container.store, flow_service, _container.config)
        breaker_gate = BreakerGateUseCase(_container.workers, _container.fs, _container.breaker)
        hook_completions = HookCompletionsUseCase(_container.store, flow_service)
        tick = TickUseCase(
            _container.store,
            _container.workers,
            _container.spawner,
            _container.config,
            monitor=monitor,
            cadence_gate=cadence_gate,
            breaker_gate=breaker_gate,
            hook_completions=hook_completions,
        )
        if a.once:
            now = time.time()
            result = tick.execute(TickInput(now=now))
            lines, _ = _format_tick(result, None, now)
            for line in lines:
                print(line)
            return 0
        interval = _container.config.poll_seconds()
        max_agents = _container.config.max_agents()
        show_banner()
        print("lc start  poll=%ds  max-agents=%d" % (interval, max_agents))
        prev_snapshot = None
        prev_now = time.time()
        while True:
            now = time.time()
            result = tick.execute(TickInput(now=now, since=prev_now))
            lines, prev_snapshot = _format_tick(result, prev_snapshot, now)
            for line in lines:
                print(line)
            prev_now = now
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\ntg run stopped")
        return 0
    finally:
        ReleaseRunLockUseCase(_container.lock).execute()


def _human_step_skills():
    skills = []
    for role in _container.fs.step_roles():
        a = _container.fs.parse_step(role)
        if a and a["meta"].get("step") and not a["meta"].get("model"):
            skills.append((a["meta"]["step"], a["body"]))
    return sorted(skills)


def _compose_driver(base_body, skills):
    if not skills:
        return base_body
    parts = [
        base_body,
        "\n\n# Skills for human-facing steps\n",
        "These steps surface in `lc inbox`. When the human picks one, run the skill "
        "for its step: assist them, and record the outcome (`lc done` / `lc close`).\n",
    ]
    for step, body in skills:
        parts.append("\n## %s\n\n%s" % (step, body.strip()))
    return "\n".join(parts)


def cmd_driver(argv):
    if not require_store():
        return 1
    root = _container.config.data_root()
    seat = _container.fs.read_md("driver.md")
    if seat is None or not seat["meta"].get("model"):
        sys.stderr.write("driver.md is missing or has no 'model' in frontmatter\n")
        return 1
    body = _compose_driver(seat["body"], _human_step_skills())
    show_banner()
    os.execvp(
        "claude",
        [
            "claude",
            "--model",
            seat["meta"]["model"],
            "--name",
            "driver",
            "--append-system-prompt",
            body,
            "--add-dir",
            root,
            "--dangerously-skip-permissions",
        ],
    )


def cmd_init(argv):
    ap = argparse.ArgumentParser(prog="lc init")
    ap.add_argument("project", nargs="?")
    a = ap.parse_args(argv)
    if a.project:
        try:
            r = InitProjectUseCase(_container.config, _container.fs).execute(
                InitProjectInput(project=a.project)
            )
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
        if r.created:
            print("scaffolded %s (%s)" % (r.project_dir, ", ".join(r.created)))
        else:
            print("%s already scaffolded" % r.project_dir)
        return 0
    r = InitGridUseCase(_container.store, _container.fs, _container.config).execute()
    print("lightcycle store already initialised" if r.existed else "lightcycle store initialised")
    print("config %s at %s" % ("created" if r.created else "already exists", r.config_path))
    return 0


def cmd_config(argv):
    ap = argparse.ArgumentParser(prog="lc config")
    ap.add_argument("--edit", action="store_true")
    a = ap.parse_args(argv)
    if a.edit:
        _container.config.ensure_config()
        editor = _container.config.editor()
        os.execvp(editor, [editor, _container.config.config_path()])
    p = _container.config.config_path()
    print("config: %s" % p)
    print("exists" if os.path.exists(p) else "not found - run `lc init` to seed it")
    for key, getter in (("projects", projects_root), ("specs", specs_root)):
        try:
            print("%s: %s" % (key, getter()))
        except ConfigError:
            print("%s: (not set - run `lc init`)" % key)
    return 0


def cmd_status(argv):
    ap = argparse.ArgumentParser(prog="lc status")
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


def cmd_label(argv):
    ap = argparse.ArgumentParser(prog="lc label")
    ap.add_argument("id")
    ap.add_argument("label")
    a = ap.parse_args(argv)
    _container.store.label_add(a.id, a.label)
    return 0


def cmd_reflect(argv):
    ap = argparse.ArgumentParser(prog="lc reflect")
    ap.add_argument("id")
    ap.add_argument(
        "--feedback",
        default="",
        help="freeform feedback for the retro: what went well, what got in the way, "
        "tooling friction, spec gaps - whatever is worth surfacing (your step "
        "file says what to look for)",
    )
    a = ap.parse_args(argv)
    ReflectUseCase(_container.store, _container.fs).execute(
        ReflectInput(step=a.id, feedback=a.feedback)
    )
    print("reflected")
    return 0


def cmd_worklog(argv):
    ap = argparse.ArgumentParser(prog="lc worklog")
    ap.add_argument("start", nargs="?")
    ap.add_argument("end", nargs="?")
    a = ap.parse_args(argv)
    import datetime as _dt

    now = _dt.datetime.now().astimezone()
    today, tz = now.date(), now.tzinfo
    args = [x for x in (a.start, a.end) if x is not None]
    resp = WorklogUseCase(_container.store).execute(
        WorklogInput(period_args=args, today=today, tz=tz)
    )
    if not resp.entries:
        print("no items shipped in that period")
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
            print("  [%s] %s" % (item.step, item.text))
    elif resp.reflection_count == 0:
        print("no reflections yet - agents call `lc reflect --feedback` before `lc done`")
    print("\nPer-item signals:")
    for row in resp.item_signals:
        sig_str = "  ".join(_fmt_signal(k, row.signals[k]) for k in sorted(row.signals))
        print(
            "  %-20s  %s  (N=%d)  duration=%s"
            % (row.item.id, sig_str, row.reflections, _fmt_duration(row.total_duration()))
        )


def _fmt_signal(name, by_model):
    total = sum(by_model.values())
    if not by_model:
        return "%s=%d" % (name, total)
    breakdown = ",".join("%s:%d" % (m, by_model[m]) for m in sorted(by_model))
    return "%s=%d(%s)" % (name, total, breakdown)


def _fmt_duration(seconds):
    if seconds is None:
        return "unknown"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, _ = divmod(rem, 60)
    if hours:
        return "%dh%02dm" % (hours, minutes)
    return "%dm" % minutes


def cmd_retro(argv):
    ap = argparse.ArgumentParser(prog="lc retro")
    ap.add_argument("id", nargs="?", default=None, help="item or theme id")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="aggregate steps closed on/after date")
    ap.add_argument("--last", type=int, metavar="N", help="aggregate last N closed themes")
    a = ap.parse_args(argv)

    flags = [a.id is not None, a.since is not None, a.last is not None]
    if sum(flags) != 1:
        ap.error("provide exactly one of: <id>, --since, --last")

    inp = RetroInput(subject=a.id, since=a.since, last=a.last)
    resp = RetroUseCase(_container.store, _flow()).execute(inp)
    _print_retro(resp)
    return 0
