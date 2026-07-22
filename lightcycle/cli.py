import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error

from lightcycle import __version__
from lightcycle.adapters.simulate import NullWorkers, RecordingGit, SimulateConfig
from lightcycle.banner import show_banner
from lightcycle.domain.contracts import FILE_PROVIDES
from lightcycle.logrender import render_log_line
from lightcycle.render import (
    render_backlog, render_backlog_themed, render_inbox, render_queue, render_workflow_mermaid,
)

from lightcycle.application.feedback import (
    ReflectInput,
    ReflectUseCase,
    RetroInput,
    RetroUseCase,
    WorklogInput,
    WorklogUseCase,
)
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from lightcycle.application.work.project_of import project_of
from lightcycle.application.work.resolve_backlog import link_resolves
from lightcycle.application.work.title_guard import validate_title
from lightcycle.application.work import (
    ActiveStepsUseCase,
    BacklogInput,
    BacklogUseCase,
    CloseThemeInput,
    CloseThemeUseCase,
    CloseItemInput,
    CloseItemUseCase,
    InboxInput,
    InboxUseCase,
    LinkArtifactInput,
    LinkArtifactUseCase,
    OpenThemeInput,
    OpenThemeUseCase,
    QueueInput,
    QueueUseCase,
    RemoveNodeInput,
    RemoveNodeUseCase,
    ShowNodeInput,
    ShowNodeUseCase,
    StatusUseCase,
    TraceInput,
    TraceUseCase,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect import DoctorInput, DoctorUseCase
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.errors import WorkflowSourceError
from lightcycle.application.workflows.init_origin import InitWorkflowOriginUseCase
from lightcycle.application.workflows.list import ListWorkflowSourcesUseCase
from lightcycle.application.workflows.remove import RemoveWorkflowSourceUseCase
from lightcycle.application.workflows.simulate import SimulateInput, WorkflowSimulateUseCase
from lightcycle.application.workflows.upgrade import UpgradeWorkflowSourceUseCase
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
    BackupUseCase,
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
    VenvBusyError,
    upgrade,
)
from lightcycle.adapters.sqlite_store import LiveStoreRefused, SqliteStore
from lightcycle.config import Config, ConfigError
from lightcycle.container import Container, make_flow_service, make_worktrees


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
    return make_flow_service(
        _container.fs, _container.store, _container.config, _container.workflow_source)


def ready_roles():
    return _flow().ready_roles()


def _worktrees():
    return make_worktrees(
        _container.store, _container.git, _container.fs, _container.config, _flow())


def require_store():
    if _container.fs.store_ready():
        return True
    sys.stderr.write("no lightcycle store here - run `lc init` first.\n")
    return False


COMMAND_GROUPS = [
    ("Setup", [
        ("init", "[<project>] [--shortcode X]", "no arg: create the lightcycle store + seed the "
         "HOME config (run once). <project>: register/record that project's shortcode in the "
         "central config"),
        ("config", "[--edit]", "show or edit the lightcycle config (projects + specs roots)"),
        ("version", "", "print the lightcycle version"),
        ("upgrade", "[--check]", "upgrade lc in place from main if it's ahead; --check only reports"),
        ("workflow", "<add|upgrade|list|rm|check|describe|simulate> ...", "manage workflow sources and "
         "inspect workflows: check <origin>/<name> validates composition, describe <origin>/<name> "
         "shows its summary/shape, simulate <origin>/<name> dry-runs the bundle through the real "
         "engine (no LLM/GitHub) to its terminals - separate from `lc upgrade`, which updates the engine"),
    ]),
    ("Start working", [
        ("start", "[--once]", "the agent pool: each tick, sweep stale claims, then fill up to LC_MAX_AGENTS (default 4) workers from the ready queue"),
        ("driver", "[claude-flags]", "open the interactive driver - your seat to shape and file "
         "work; extra flags pass through to claude (e.g. --resume, --dangerously-skip-permissions)"),
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
        ("worklog", "[start] [end]", "items shipped in a period (today, yesterday, YYYY-MM-DD)"),
    ]),
    ("Node primitives", [
        ("new", "<type> \"title\" [--parent/--workflow/--goal/--project]",
         "create a node; <type> is theme|item|step"),
        ("set", "<id> [--parent/--state/--workflow/--title/--goal/--desc/--label]",
         "update a node; --parent moves it; --state active activates an item (files the entry step)"),
        ("rm", "<id> [--force]", "delete a node; refuses on structural children, a live "
         "worker, or a dirty worktree - --force overrides the dirty worktree and stale claims"),
        ("attach", "<id> <type> <value> [--label]", "attach an artifact"),
        ("dep", "<id> --needs <id> | --remove <id>", "add or remove a blocker on a node"),
    ]),
    ("Agent verbs (workers call these)", [
        ("claim", "<role>", "atomically claim the next ready step for a role"),
        ("done", "<id> <outcome> [--note \"<text>\"]", "close a node; a step done-with-outcome advances the flow"),
    ]),
    ("Feedback loop", [
        ("retro", "<theme>", "gather child feedback + objective signals into a read digest"),
    ]),
    ("Maintenance", [
        ("sweep", "", "reclaim orphaned step claims and prune dead worker entries (kept: LC_WORKER_HISTORY, default 20)"),
        ("restore", "[<snapshot>] --force", "overwrite the live store from a backup snapshot "
         "(newest if omitted); refuses without --force or while lc start is running"),
        ("doctor", "[--json]", "read-only diagnostics: store fsck + pinned-bundle/config/origin drift"),
    ]),
    ("Plumbing (the loop uses these)", [
        ("advance", "<id> <outcome>", "create the next step for an outcome without closing"),
        ("ready-roles", "", "list roles that have a ready step"),
        ("spawn", "<role>", "spawn one worker for a role"),
        ("specs-dir", "[--check]", "print the resolved specs directory (absolute path); "
         "--check validates it against specs-remote"),
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


def cmd_version(argv):
    argparse.ArgumentParser(prog="lc version").parse_args(argv)
    print("lightcycle %s" % __version__)
    return 0


def cmd_upgrade(argv):
    ap = argparse.ArgumentParser(prog="lc upgrade")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    try:
        resp = upgrade(__version__, check_only=a.check)
    except VenvBusyError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    except (urllib.error.URLError, ValueError) as e:
        sys.stderr.write("could not check for updates: %s\n" % e)
        return 1
    if not resp.available:
        print("already at latest (%s)" % resp.current)
    elif a.check:
        print("upgrade available: %s -> %s" % (resp.current, resp.remote))
    else:
        print("upgraded: %s -> %s" % (resp.current, resp.remote))
    return 0


_WORKER_VERBS = ("claim", "done", "show", "attach", "retro")
_SET_FORBIDDEN_FLAGS = (
    "--parent", "--title", "--desc", "--description", "--goal", "--project",
    "--workflow", "--backlog", "--label", "--step",
)


def _sets_state_blocked(args):
    for i, a in enumerate(args):
        if a == "--state":
            return i + 1 < len(args) and args[i + 1] == "blocked"
        if a.startswith("--state="):
            return a.split("=", 1)[1] == "blocked"
    return False


def _worker_permitted(cmd, args):
    if cmd in _WORKER_VERBS:
        return True
    if cmd == "set":
        if any(a.split("=", 1)[0] in _SET_FORBIDDEN_FLAGS for a in args):
            return False
        return _sets_state_blocked(args)
    return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("version", "--version"):
        return cmd_version([])
    if argv and argv[0] == "upgrade":
        if Config().is_worker():
            sys.stderr.write("lc: workers may not run 'upgrade'\n")
            return 1
        return cmd_upgrade(argv[1:])
    try:
        set_container(Container())
    except LiveStoreRefused as e:
        sys.stderr.write("%s\n" % e)
        return 1
    _container.config.reconcile_config()
    if not argv or argv[0] in ("-h", "--help"):
        print_help()
        return 0
    cmd = argv[0]
    if cmd not in VERBS:
        sys.stderr.write("unknown subcommand: %s\n" % cmd)
        return 2
    if (
        _container.config.is_worker()
        and _container.config.is_live_home()
        and not _worker_permitted(cmd, argv[1:])
    ):
        sys.stderr.write(
            "lc: workers may not run '%s' - permitted: claim, done, show, attach, "
            "set --state blocked\n" % cmd
        )
        return 1
    fn = globals().get("cmd_" + cmd.replace("-", "_"))
    if fn is None:
        sys.stderr.write("not implemented: %s\n" % cmd)
        return 2
    return fn(argv[1:]) or 0


def cmd_workflow(argv):
    ap = argparse.ArgumentParser(prog="lc workflow")
    sub = ap.add_subparsers(dest="sub")
    p_add = sub.add_parser("add")
    p_add.add_argument("url")
    p_add.add_argument("--ref")
    p_add.add_argument("--name")
    p_init = sub.add_parser("init")
    p_init.add_argument("name")
    p_upgrade = sub.add_parser("upgrade")
    p_upgrade.add_argument("origin", nargs="?")
    sub.add_parser("list")
    p_check = sub.add_parser("check")
    p_check.add_argument("workflow")
    p_check.add_argument("--json", action="store_true")
    p_describe = sub.add_parser("describe")
    p_describe.add_argument("workflow")
    p_describe.add_argument("--mermaid", action="store_true")
    p_simulate = sub.add_parser("simulate")
    p_simulate.add_argument("workflow")
    p_rm = sub.add_parser("rm")
    p_rm.add_argument("origin")
    a = ap.parse_args(argv)
    if a.sub is None:
        ap.print_help()
        return 2
    if a.sub == "check":
        return _workflow_check(a.workflow, a.json)
    if a.sub == "describe":
        return _workflow_describe(a.workflow, a.mermaid)
    if a.sub == "simulate":
        return _workflow_simulate(a.workflow)
    c = _container
    try:
        if a.sub == "add":
            resp = AddWorkflowSourceUseCase(c.workflow_source, c.store, c.config, c.fs).execute(
                url=a.url, ref=a.ref, name=a.name)
            msg = "added %s @ %s" % (resp.origin, resp.sha)
            if resp.pruned:
                msg += " (pruned %d)" % len(resp.pruned)
            print(msg)
            return 0
        if a.sub == "init":
            resp = InitWorkflowOriginUseCase(c.config, c.git, c.workflow_source, c.store, c.fs).execute(a.name)
            print("created %s, registered as %s @ %s, personal-origin set" % (
                resp.project_dir, resp.origin, resp.sha))
            return 0
        if a.sub == "upgrade":
            origins = [a.origin] if a.origin else c.workflow_source.list_origins()
            if not origins:
                print("no workflow sources registered")
                return 0
            for origin in origins:
                resp = UpgradeWorkflowSourceUseCase(c.workflow_source, c.store, c.config, c.fs).execute(origin)
                if resp.changed:
                    print("upgraded %s @ %s" % (resp.origin, resp.sha))
                else:
                    print("%s already current (%s)" % (resp.origin, resp.sha))
            return 0
        if a.sub == "list":
            resp = ListWorkflowSourcesUseCase(c.workflow_source, c.store, c.fs).execute()
            if not resp.origins:
                print("no workflow sources registered")
                return 0
            for v in resp.origins:
                line = "%s  %s  %s  (%d versions" % (v.name, v.current, v.url, len(v.versions))
                if v.pinned:
                    line += ", %d pinned" % len(v.pinned)
                print(line + ")")
                for wf, summary in v.workflows:
                    print("  %s%s" % (wf, "  - %s" % summary if summary else ""))
            return 0
        if a.sub == "rm":
            resp = RemoveWorkflowSourceUseCase(c.workflow_source, c.store).execute(a.origin)
            print("removed %s" % resp.origin)
            return 0
    except (WorkflowSourceError, subprocess.CalledProcessError) as e:
        sys.stderr.write("lc workflow: %s\n" % e)
        return 1


def cmd_show(argv):
    ap = argparse.ArgumentParser(prog="lc show")
    ap.add_argument("id")
    a = ap.parse_args(argv)
    view = ShowNodeUseCase(_container.store).execute(ShowNodeInput(step=a.id)).view
    out = view.as_dict()
    skill = _flow().step_skill(view.step)
    if skill:
        out["skill"] = skill
    print(json.dumps(out, indent=2))
    return 0


def cmd_claim(argv):
    ap = argparse.ArgumentParser(prog="lc claim")
    ap.add_argument("role")
    a = ap.parse_args(argv)
    try:
        resp = ClaimStepUseCase(
            _container.store, _flow(), _worktrees(), _container.workers, _container.config
        ).execute(ClaimInput(role=a.role))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if resp is None:
        return 0
    out = resp.view.as_dict()
    if resp.workspace:
        out["workspace"] = resp.workspace
    if resp.branch:
        out["branch"] = resp.branch
    if resp.spec_path:
        out["spec_path"] = resp.spec_path
    if resp.brief:
        out["brief"] = resp.brief
    if resp.repo_path:
        out["repo_path"] = resp.repo_path
    if resp.config:
        out["config"] = resp.config
    if resp.phase:
        out["phase"] = resp.phase
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
    ap = argparse.ArgumentParser(prog="lc specs-dir")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    root = _container.config.specs_root()
    if not a.check:
        print(root)
        return 0
    try:
        expected = _container.config.specs_remote()
    except ConfigError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if not _container.git.is_git_repo(root):
        sys.stderr.write("specs dir %s is not a git repo\n" % root)
        return 1
    origin = _container.git.remote_url(root)
    if origin != expected:
        sys.stderr.write(
            "specs dir %s origin (%s) does not match specs-remote (%s)\n"
            % (root, origin or "none", expected)
        )
        return 1
    print("ok: %s matches specs-remote (%s)" % (root, expected))
    return 0


def _workflow_check(selector, as_json):
    flow = _flow()
    try:
        selected = flow.resolve_selection(selector)
        resp = FlowCheckUseCase(flow).execute(FlowCheckInput(workflow=selected))
    except ValueError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    owner, routes, an = resp.owner, resp.routes, resp.analysis
    steps, req, opt, prod = an["steps"], an["req"], an["opt"], an["prod"]
    entries, terminals = an["entries"], an["terminals"]
    unreachable, missing, dups, ok = an["unreachable"], an["missing"], an["dups"], an["ok"]
    phase_gaps = an["phase_gaps"]
    unknown_phases = an["unknown_phases"]
    phase_conflicts = an["phase_conflicts"]

    hooks = resp.hooks
    if as_json:
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
                    "phase_gaps": phase_gaps,
                    "unknown_phases": unknown_phases,
                    "phase_conflicts": phase_conflicts,
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
    if phase_gaps:
        sys.stderr.write("phase: stages missing a phase: %s\n" % ", ".join(phase_gaps))
    if unknown_phases:
        sys.stderr.write(
            "phase: phase declared for a non-owned stage (only owned stages carry a phase; "
            "fileless terminals do not): %s\n" % ", ".join(unknown_phases)
        )
    for phase, workspaces in sorted(phase_conflicts.items()):
        sys.stderr.write("phase: phase '%s' spans workspaces: %s\n" % (phase, ", ".join(workspaces)))
    return 0 if ok else 1


def _workflow_describe(selector, as_mermaid=False):
    flow = _flow()
    try:
        pin = flow.resolve_selection(selector)
        meta = flow.workflow_meta(pin)
        graph = flow.load_graph(pin)
        assembled = flow.load_flow(pin)
    except ValueError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if as_mermaid:
        for line in render_workflow_mermaid(graph, assembled):
            print(line)
        return 0
    print(selector)
    if meta.get("summary"):
        print("  summary      %s" % meta["summary"])
    if meta.get("when-to-use"):
        print("  when to use  %s" % meta["when-to-use"])
    print("  entry        %s" % graph.entry)
    phases = sorted({p for p in graph.phases.values()})
    if phases:
        print("  phases       %s" % ", ".join(phases))
    print("  steps        %s" % ", ".join(assembled.steps()))
    return 0


def _workflow_simulate(selector):
    c = _container
    scratch = tempfile.mkdtemp(prefix="lc-simulate-")
    try:
        store_home = os.path.join(scratch, "home")
        specs_root = os.path.join(scratch, "specs")
        projects_root = os.path.join(scratch, "projects")
        os.makedirs(store_home, exist_ok=True)
        os.makedirs(specs_root, exist_ok=True)
        os.makedirs(projects_root, exist_ok=True)
        cfg_path = os.path.join(store_home, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: SIM\n")
        store_config = Config(environ={"LC_HOME": store_home, "LC_CONFIG": cfg_path})
        store = SqliteStore(store_config)
        sim_config = SimulateConfig(c.config, specs_root, projects_root)
        git = RecordingGit()
        flow = make_flow_service(c.fs, store, c.config, c.workflow_source)
        worktrees = make_worktrees(store, git, c.fs, sim_config, flow)
        claim = ClaimStepUseCase(store, flow, worktrees, NullWorkers(), sim_config)
        complete = CompleteStepUseCase(store, flow, worktrees, sim_config)
        use_case = WorkflowSimulateUseCase(
            store, flow, worktrees, claim, complete, projects_root, git
        )
        try:
            resp = use_case.execute(SimulateInput(workflow=selector))
        except (ValueError, UseCaseError) as e:
            sys.stderr.write("%s\n" % e)
            return 1
        if resp.ok:
            print("pass")
            return 0
        for v in resp.violations:
            sys.stderr.write("%s\n" % v)
        return 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def cmd_done(argv):
    ap = argparse.ArgumentParser(prog="lc done")
    ap.add_argument("id")
    ap.add_argument("outcome")
    ap.add_argument(
        "--note", nargs="+", help="a note to forward to the next step; unquoted multi-word is fine"
    )
    a = ap.parse_args(argv)
    note = " ".join(a.note) if a.note else None
    node = _container.store.get_node(a.id)
    try:
        if node.type == "step":
            resp = CompleteStepUseCase(
                _container.store, _flow(), _worktrees(), _container.config).execute(
                CompleteInput(step=a.id, outcome=a.outcome, note=note)
            )
            if resp.next_step:
                print(resp.next_step)
        elif node.type == "theme":
            CloseThemeUseCase(_container.store).execute(
                CloseThemeInput(theme=a.id, reason=a.outcome)
            )
        else:
            CloseItemUseCase(_container.store, _worktrees()).execute(
                CloseItemInput(item=a.id, reason=a.outcome)
            )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
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
        print("item %s  %s  [%s]" % (resp.item.id, resp.item.title, resp.item.state))
        for art in resp.artifacts:
            if art.label:
                print("  artifact %s [%s]: %s" % (art.type, art.label, art.value))
            else:
                print("  artifact %s: %s" % (art.type, art.value))
        for t in resp.steps:
            log = "  log:" + t.log if t.log else ""
            print("  step %s  %s  [%s]%s" % (t.id, t.step or "-", t.state, log))
    return 0


def cmd_sweep(argv):
    result = SweepUseCase(
        _container.store, _container.workers, _worktrees(), _container.git
    ).execute(time.time(), _container.config.max_boot_seconds())
    for bid in result.swept:
        print("swept %s" % bid)
    for bid in result.preserved:
        print("preserved %s" % bid)
    for bid in result.capture_failed:
        sys.stderr.write("failed to preserve uncommitted work for %s\n" % bid)
    for spawnid in result.killed:
        print("killed %s" % spawnid)
    if result.pruned:
        print(
            "pruned %d dead worker entr%s" % (result.pruned, "y" if result.pruned == 1 else "ies")
        )
    return 0


def cmd_restore(argv):
    ap = argparse.ArgumentParser(prog="lc restore")
    ap.add_argument("snapshot", nargs="?")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    snapshots = _container.backup.list_snapshots()
    if a.list:
        now = time.time()
        for name, mtime in snapshots:
            print("%s  age=%ds" % (name, int(now - mtime)))
        return 0
    if not snapshots:
        sys.stderr.write("lc restore: no snapshots in %s\n" % _container.config.backups_dir())
        return 1
    if a.snapshot is None:
        target, target_mtime = snapshots[0]
    else:
        match = next(((n, m) for n, m in snapshots if n == a.snapshot), None)
        if match is None:
            sys.stderr.write("lc restore: no such snapshot %s\n" % a.snapshot)
            return 1
        target, target_mtime = match
    if not a.force:
        sys.stderr.write(
            "lc restore: this would overwrite the live store from %s; re-run with --force\n"
            % target
        )
        return 1
    lock_result = AcquireRunLockUseCase(_container.lock).execute()
    if not lock_result.acquired:
        sys.stderr.write("lc restore: lc start is running (pid %d); stop it first\n"
                          % lock_result.holder_pid)
        return 1
    try:
        _container.store.disconnect()
        _container.backup.restore(target)
    finally:
        ReleaseRunLockUseCase(_container.lock).execute()
    print("restored %s (age %ds)" % (target, int(time.time() - target_mtime)))
    return 0


def cmd_doctor(argv):
    ap = argparse.ArgumentParser(prog="lc doctor")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    report = DoctorUseCase(
        _container.store, _container.workflow_source, _container.config
    ).execute(DoctorInput())
    if a.json:
        print(json.dumps(
            {cat: [p.as_dict() for p in probs] for cat, probs in report.problems.items()},
            indent=2,
        ))
        return 0 if report.healthy() else 1
    for cat, probs in report.problems.items():
        if not probs:
            print("%s: ok" % cat)
            continue
        print("%s:" % cat)
        for p in probs:
            suffix = " (%s)" % p.node_id if p.node_id else ""
            print("  %s%s" % (p.message, suffix))
    print("healthy" if report.healthy() else "unhealthy")
    return 0 if report.healthy() else 1


def cmd_inbox(argv):
    ap = argparse.ArgumentParser(prog="lc inbox")
    ap.add_argument("n", nargs="?", type=int)
    a = ap.parse_args(argv)
    resp = InboxUseCase(_container.store, _flow()).execute(InboxInput(n=a.n))
    for line in render_inbox(resp.rows, _container.config.max_title_length()):
        print(line)
    return 0


def cmd_backlog(argv):
    ap = argparse.ArgumentParser(prog="lc backlog")
    ap.add_argument("n", nargs="?", type=int)
    ap.add_argument("--project")
    ap.add_argument("--themes", action="store_true")
    a = ap.parse_args(argv)
    resp = BacklogUseCase(_container.store, _flow()).execute(
        BacklogInput(n=a.n, project=a.project, themes=a.themes))
    title_cap = _container.config.max_title_length()
    lines = (
        render_backlog_themed(resp.groups, title_cap)
        if a.themes else render_backlog(resp.rows, title_cap)
    )
    for line in lines:
        print(line)
    return 0


def cmd_active(argv):
    for t in ActiveStepsUseCase(_container.store).execute().steps:
        print("  %s  %s" % (t.id, t.title))
    return 0


def cmd_queue(argv):
    ap = argparse.ArgumentParser(prog="lc queue")
    ap.add_argument("n", nargs="?", type=int, default=10)
    a = ap.parse_args(argv)
    steps = QueueUseCase(_container.store).execute(QueueInput(n=a.n)).steps
    for line in render_queue(steps, _container.config.max_title_length()):
        print(line)
    return 0






_NODE_TYPES = ("theme", "item", "step")


def cmd_new(argv):
    ap = argparse.ArgumentParser(prog="lc new")
    ap.add_argument("type")
    ap.add_argument("title")
    ap.add_argument("--parent")
    ap.add_argument("--workflow")
    ap.add_argument("--project")
    ap.add_argument("--repo")
    ap.add_argument("--goal")
    ap.add_argument("--description")
    ap.add_argument("--backlog", action="append")
    ap.add_argument("--inbox", action="store_true", dest="attention")
    a = ap.parse_args(argv)
    if a.type not in _NODE_TYPES:
        sys.stderr.write(
            "unknown type '%s'; expected theme | item | step (theme > item > step)\n" % a.type
        )
        return 2
    try:
        validate_title(_container.config, a.title)
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if a.type == "theme":
        try:
            resp = OpenThemeUseCase(_container.store).execute(
                OpenThemeInput(objective=a.title, backlog=a.backlog,
                               project=a.project, workflow=a.workflow, repo=a.repo)
            )
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
        print(resp.theme)
    elif a.type == "item":
        if a.parent:
            try:
                parent = _container.store.get_node(a.parent)
            except KeyError:
                sys.stderr.write("unknown theme '%s'\n" % a.parent)
                return 1
            if parent.type != "theme":
                sys.stderr.write("'%s' is not a theme (type=%s)\n" % (a.parent, parent.type))
                return 1
        tid = _container.store.create_item(
            a.title, theme=a.parent, project=a.project, goal=a.goal, workflow=a.workflow)
        repo = a.repo or (project_of(_container.store, parent) if a.parent else None)
        if repo:
            _container.store.add_artifact(tid, "repo", repo)
        if a.description or a.attention:
            _container.store.edit_node(tid, description=a.description)
            if a.attention:
                _container.store.label_add(tid, "attention")
        if a.backlog:
            try:
                link_resolves(_container.store, tid, a.backlog)
            except UseCaseError as e:
                sys.stderr.write("%s\n" % e)
                return 1
        print(tid)
    else:
        print(_container.store.create_step(
            a.title, parent=a.parent, project=a.project, goal=a.goal, description=a.description,
            attention=a.attention))
    return 0


def cmd_set(argv):
    ap = argparse.ArgumentParser(prog="lc set")
    for opt in ("title", "description", "goal", "project", "parent", "workflow", "state", "label",
                "needs", "branch", "pr", "reason", "tried", "step"):
        ap.add_argument("--%s" % opt)
    ap.add_argument("--backlog", action="append")
    ap.add_argument("id")
    a = ap.parse_args(argv)
    try:
        if a.title:
            validate_title(_container.config, a.title)
        if a.state == "active":
            resp = ActivateItemUseCase(_container.store, _flow()).execute(
                ActivateItemInput(item=a.id, workflow=a.workflow, theme=a.parent, step=a.step)
            )
            print(resp.step)
            return 0
        if a.state == "blocked":
            if not a.needs:
                sys.stderr.write("--state blocked requires --needs (what the human must decide)\n")
                return 2
            BlockStepUseCase(_container.store).execute(
                BlockInput(step=a.id, needs=a.needs, branch=a.branch, pr=a.pr,
                           reason=a.reason, tried=a.tried)
            )
            return 0
        if a.state == "ready":
            UnblockStepUseCase(_container.store, _flow()).execute(UnblockInput(step=a.id))
            return 0
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if a.label:
        _container.store.label_add(a.id, a.label)
    tid = _container.store.edit_node(
        a.id, title=a.title, description=a.description, goal=a.goal,
        project=a.project, parent=a.parent, workflow=a.workflow)
    if a.parent:
        print(tid)
    if a.backlog:
        try:
            link_resolves(_container.store, tid, a.backlog)
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
    return 0


def cmd_attach(argv):
    ap = argparse.ArgumentParser(prog="lc attach")
    ap.add_argument("id")
    ap.add_argument("type")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("value", nargs="?")
    group.add_argument("--file")
    ap.add_argument("--label")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    value = a.value
    if a.file:
        data = _container.fs.read_bytes(a.file)
        if data is None:
            sys.stderr.write("no such file: %s\n" % a.file)
            return 1
        value = data.decode()
    if a.type == "feedback":
        ReflectUseCase(_container.store, _container.fs).execute(
            ReflectInput(step=a.id, feedback=value)
        )
        return 0
    LinkArtifactUseCase(_container.store).execute(
        LinkArtifactInput(item=a.id, atype=a.type, value=value, label=a.label, replace=a.replace)
    )
    return 0


def cmd_dep(argv):
    ap = argparse.ArgumentParser(prog="lc dep")
    ap.add_argument("id")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--needs")
    group.add_argument("--remove")
    a = ap.parse_args(argv)
    if a.remove:
        removed = _container.store.dep_remove(a.id, a.remove)
        if removed:
            print("removed: %s no longer blocked by %s" % (a.id, a.remove))
        else:
            print("no-op: %s was not blocked by %s" % (a.id, a.remove))
        return 0
    _container.store.dep_add(a.id, a.needs)
    return 0


def cmd_rm(argv):
    ap = argparse.ArgumentParser(prog="lc rm")
    ap.add_argument("id")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    try:
        resp = RemoveNodeUseCase(
            _container.store, _container.workers, _worktrees(), _container.git
        ).execute(RemoveNodeInput(id=a.id, force=a.force))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print(
        "removed %s (%d step row(s)%s)"
        % (
            resp.id,
            resp.steps_removed,
            ", worktree torn down" if resp.worktree_removed else "",
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
    for sid in result.cadence_fired:
        lines.append("%s  %-7s  %s" % (ts, "audit", sid))
    for step, tid, detail in result.hook_completed:
        msg = "%s: %s" % (tid, detail) if detail else tid
        lines.append("%s  %-7s  %s" % (ts, step, msg))
    if result.backed_up:
        msg = result.backed_up
        if result.backup_pruned:
            msg += " pruned=%d" % len(result.backup_pruned)
        lines.append("%s  %-7s  %s" % (ts, "backup", msg))
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


def _upgrade_notice(check=lambda: upgrade(__version__, check_only=True)):
    try:
        resp = check()
    except Exception:
        return None
    if not resp.available:
        return None
    return "a newer lightcycle is available (%s -> %s); run lc upgrade" % (resp.current, resp.remote)


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
        complete = CompleteStepUseCase(
            _container.store, flow_service, _worktrees(), _container.config)
        monitor = MonitorPrsUseCase(
            _container.store, _container.github, _worktrees(), flow_service, complete
        )
        cadence_gate = RetroCadenceUseCase(_container.store, _container.config)
        breaker_gate = BreakerGateUseCase(_container.workers, _container.fs, _container.breaker)
        hook_completions = HookCompletionsUseCase(_container.store, flow_service)
        backup_gate = BackupUseCase(_container.backup, _container.config)
        tick = TickUseCase(
            _container.store,
            _container.workers,
            _container.spawner,
            _container.config,
            monitor=monitor,
            cadence_gate=cadence_gate,
            breaker_gate=breaker_gate,
            hook_completions=hook_completions,
            worktrees=_worktrees(),
            git=_container.git,
            backup_gate=backup_gate,
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
        notice = _upgrade_notice()
        if notice:
            print(notice)
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


def cmd_driver(argv):
    if not require_store():
        return 1
    root = _container.config.data_root()
    seat = _container.fs.read_md("driver.md", _container.config.prompts_root())
    if seat is None or not seat["meta"].get("model"):
        sys.stderr.write("driver.md is missing or has no 'model' in frontmatter\n")
        return 1
    body = seat["body"]
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
            *argv,
        ],
    )


def cmd_init(argv):
    ap = argparse.ArgumentParser(prog="lc init")
    ap.add_argument("project", nargs="?")
    ap.add_argument("--shortcode")
    a = ap.parse_args(argv)
    if a.project:
        try:
            r = InitProjectUseCase(_container.config, _container.fs).execute(
                InitProjectInput(project=a.project, shortcode=a.shortcode)
            )
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
        if r.changed:
            print("%s -> shortcode %s" % (r.project, r.shortcode))
        else:
            print("%s already mapped to %s" % (r.project, r.shortcode))
        return 0
    r = InitGridUseCase(_container.store, _container.fs, _container.config).execute()
    print("lightcycle store already initialised" if r.existed else "lightcycle store initialised")
    print("config %s at %s" % ("created" if r.created else "already exists", r.config_path))
    _init_pull_default_origin()
    return 0


def _init_pull_default_origin():
    origin = _container.config.default_origin()
    if _container.workflow_source.read_registry(origin) is not None:
        return
    url = _container.config.workflows_remote()
    try:
        resp = AddWorkflowSourceUseCase(
            _container.workflow_source, _container.store, _container.config, _container.fs
        ).execute(url=url, ref="main", name=origin)
        print("pulled %s workflows @ %s" % (resp.origin, resp.sha))
    except (WorkflowSourceError, subprocess.CalledProcessError) as e:
        sys.stderr.write(
            "could not pull workflows: %s\nrun `lc workflow add %s --name %s` once reachable\n"
            % (e, url, origin))


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


def _print_retro(resp, interval=None):
    if resp.subject == "pending" and interval is not None:
        arrow = " -> fires" if resp.reflection_count >= interval else ""
        print(
            "== retro: pending  (%d / %d reflections%s) =="
            % (resp.reflection_count, interval, arrow)
        )
    else:
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
    ap.add_argument("--project", metavar="REPO", help="aggregate a project's closed unretroed items")
    ap.add_argument("--pending", action="store_true",
                     help="aggregate all closed unretroed items that carry feedback")
    a = ap.parse_args(argv)

    flags = [a.id is not None, a.since is not None, a.last is not None, a.project is not None,
             a.pending]
    if sum(flags) != 1:
        ap.error("provide exactly one of: <id>, --since, --last, --project, --pending")

    inp = RetroInput(subject=a.id, since=a.since, last=a.last, project=a.project,
                      pending=a.pending)
    resp = RetroUseCase(_container.store, _flow()).execute(inp)
    interval = _container.config.retro_interval_reflections() if a.pending else None
    _print_retro(resp, interval)
    return 0
