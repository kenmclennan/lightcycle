import json
import os
import shutil
import signal
import sys
import tempfile
import time
import traceback

from lightcycle import __version__
from lightcycle.adapters.simulate import (
    ScriptedGitHub,
)
from lightcycle.cli_commands import COMMANDS, build_parser
from lightcycle.adapters.upgrade import UpgradeAdapter
from lightcycle.logrender import render_log_line
from lightcycle.render import (
    display_stage, format_elapsed, render_backlog, render_inbox, render_queue, render_search,
    render_workflow_mermaid,
)

from lightcycle.application.feedback import (
    ReflectInput,
    ReflectUseCase,
    RetroInput,
    RetroUseCase,
    WorklogInput,
    WorklogUseCase,
)
from lightcycle.domain.work import (
    FieldRefusal, State, refuse_fields, refuse_state, worker_permitted, worker_refusal_message,
)
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from lightcycle.application.work.resolve_backlog import link_resolves
from lightcycle.application.work.resolve_workflow_selection import (
    ResolveWorkflowSelectionInput,
    ResolveWorkflowSelectionUseCase,
)
from lightcycle.application.work.title_guard import validate_title
from lightcycle.application.work import (
    ActiveStepsUseCase,
    BacklogInput,
    BacklogUseCase,
    CloseItemInput,
    CloseItemUseCase,
    CreateItemInput,
    CreateItemUseCase,
    CreateStepInput,
    CreateStepUseCase,
    EditNodeInput,
    EditNodeUseCase,
    InboxInput,
    InboxUseCase,
    LinkArtifactInput,
    LinkArtifactUseCase,
    PeekStepInput,
    PeekStepUseCase,
    QueueInput,
    QueueUseCase,
    ReopenItemInput,
    ReopenItemUseCase,
    RemoveNodeInput,
    RemoveNodeUseCase,
    SearchInput,
    SearchUseCase,
    ShowNodeInput,
    ShowNodeUseCase,
    StatusUseCase,
    TraceInput,
    TraceUseCase,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect import DoctorInput, DoctorUseCase
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.init_origin import InitWorkflowOriginUseCase
from lightcycle.application.workflows.list import ListWorkflowSourcesUseCase
from lightcycle.application.workflows.remove import RemoveWorkflowSourceUseCase
from lightcycle.application.workflows.simulate import SimulateInput, WorkflowSimulateUseCase
from lightcycle.application.workflows.upgrade import UpgradeWorkflowSourcesUseCase
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
)
from lightcycle.domain.flow.flow import SPECS_WORKSPACE
from lightcycle.application.pool import (
    AcquireRunLockUseCase,
    BackfillUsageUseCase,
    ListWorkersUseCase,
    ReleaseRunLockUseCase,
    StartPoolUseCase,
    ResolveLogInput,
    ResolveLogUseCase,
    StopPoolUseCase,
    TickInput,
)
from lightcycle.application.setup import (
    AddProjectInput,
    AddProjectUseCase,
    InitGridUseCase,
    ListProjectsUseCase,
    ProcessListUnreadableError,
    RemoteVersionUnavailableError,
    RemoveProjectUseCase,
    RestoreInput,
    RestoreStoreUseCase,
    ScanProjectsUseCase,
    UpgradeNoticeUseCase,
    VenvBusyError,
    upgrade,
)
from lightcycle.application.setup.upgrade import scan_venv_holders
from lightcycle.adapters.sqlite_store import LiveStoreRefused
from lightcycle.config import Config, ConfigError
from lightcycle.container import (
    Container,
    SimulationContainer,
    make_flow_service,
    worktrees_for,
)
from lightcycle.ports.store import NodeNotFoundError
from lightcycle.ports.workers import RegistryUnreadable
from lightcycle.ports.workflow_source import WorkflowSourceError


_container = None


def set_container(impl):
    global _container
    _container = impl


def container():
    return _container


def _flow():
    return make_flow_service(
        _container.workflow_bundle, _container.store, _container.config, _container.workflow_source)


def ready_roles():
    return _flow().ready_roles()


def _worktrees():
    return worktrees_for(_container)


def require_store():
    if _container.fs.store_ready():
        return True
    sys.stderr.write("no lightcycle store here - run `lc init` first.\n")
    return False


COMMAND_GROUPS = [
    ("Setup", [
        ("init", "", "create the lightcycle store + seed the HOME config (run once)."),
        ("project", "<add|list|rm|scan> ...", "manage the project registry: add <owner/name> "
         "[--shortcode X] [--path P], list, rm <owner/name>, scan [dir] [--json] lists git repos "
         "under dir (default cwd) as registration candidates - read-only, registers nothing"),
        ("config", "[--edit]", "show every resolved config setting, or edit the config file"),
        ("version", "", "print the lightcycle version"),
        ("upgrade", "[--check]", "upgrade lc in place from main if it's ahead; --check only reports"),
        ("workflow", "<add|upgrade|list|rm|check|describe|simulate> ...", "manage workflow sources and "
         "inspect workflows: check <origin>/<name> validates composition, describe <origin>/<name> "
         "shows its summary/shape, simulate <origin>/<name> dry-runs the bundle through the real "
         "engine (no LLM/GitHub) to its terminals - separate from `lc upgrade`, which updates the engine"),
    ]),
    ("Start working", [
        ("start", "[--once]", "the agent pool: each tick, sweep stale claims, then fill up to LC_MAX_AGENTS (default 4) workers from the ready queue"),
    ]),
    ("See what's happening", [
        ("status", "[--json]", "all lanes at once: inbox / active / queue / blocked"),
        ("inbox", "[N]", "what needs you now: gates to clear and agents waiting on you"),
        ("backlog", "[N]", "backlog items to develop later (todo)"),
        ("search", "<text>", "find items by title/description/notes text, across every state "
         "including done - the duplicate-check surface before filing new work"),
        ("active", "", "steps a worker is running right now"),
        ("queue", "[N]", "the next N ready/blocked agent steps"),
        ("ps", "[--all] [--json]", "running workers (alive only; --all includes dead)"),
        ("logs", "<step|stage|run> [-f]", "tail a worker's or the loop's log"),
        ("show", "<id>", "one step or item as JSON (artifacts, resume-state)"),
        ("peek", "<id> <stage>", "print a stage's step guidance as currently pinned for the given "
         "item/step's workflow origin - lets a worker read another stage's instructions without "
         "claiming them"),
        ("trace", "<item> [--json]", "an item end to end: artifacts + child steps + logs"),
        ("worklog", "[start] [end]", "items shipped in a period (today, yesterday, YYYY-MM-DD)"),
        ("tui", "", "launch the interactive dashboard (priority list + pool/breaker status)"),
    ]),
    ("Work primitives", [
        ("new", "<type> \"title\" [item: --description/--workflow/--repo | step: --parent/--step/--note]",
         "create an item or a step; each takes only its own fields"),
        ("set", "<id> [item: --title/--desc/--workflow/--state | step: --notes/--needs/--state]",
         "update an item or a step; refuses a field the other one owns"),
        ("rm", "<id> [--force]", "delete a node; refuses on a live worker or a dirty worktree "
         "- --force overrides the dirty worktree and stale claims"),
        ("attach", "<id> <type> <value> [--label] [--internal] [--kind K]", "attach an artifact"),
        ("dep", "<id> --needs <id> | --remove <id>", "add or remove a blocker on a node"),
    ]),
    ("Agent verbs (workers call these)", [
        ("claim", "<role>", "atomically claim the next ready step for a role"),
        ("done", "<id> <outcome> [--note \"<text>\"] [--disposition completed|aborted]",
         "close a node; a step done-with-outcome advances the flow"),
    ]),
    ("Feedback loop", [
        ("retro", "<item>", "gather child feedback + objective signals into a read digest"),
    ]),
    ("Maintenance", [
        ("sweep", "", "reclaim orphaned step claims and prune dead worker entries (kept: LC_WORKER_HISTORY, default 20)"),
        ("restore", "[<snapshot>] --force", "overwrite the live store from a backup snapshot "
         "(newest if omitted); refuses without --force or while lc start is running"),
        ("doctor", "[--json]", "read-only diagnostics: store fsck + pinned-bundle/config/origin drift"),
        ("backfill-usage", "", "capture usage/attribution from historical worker logs in "
         "$LC_HOME/logs that predate live capture"),
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
    build_parser(COMMANDS["version"]).parse_args(argv)
    print("lightcycle %s" % __version__)
    return 0


def cmd_upgrade(argv):
    a = build_parser(COMMANDS["upgrade"]).parse_args(argv)
    port = _container.upgrade if _container is not None else UpgradeAdapter(Config())
    try:
        resp = upgrade(
            __version__, check_only=a.check, fetch=port.fetch_remote_version,
            install=port.install_upgrade, installed=port.installed_version,
            holders=lambda: scan_venv_holders(port.list_processes),
        )
    except VenvBusyError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    except ProcessListUnreadableError as e:
        sys.stderr.write(
            "lc upgrade refused: could not check whether the venv is in use (%s)\n" % e
        )
        return 1
    except (RemoteVersionUnavailableError, ValueError) as e:
        sys.stderr.write("could not check for updates: %s\n" % e)
        return 1
    if not resp.available:
        print("already at latest (%s)" % resp.current)
    elif a.check:
        print("upgrade available: %s -> %s" % (resp.current, resp.remote))
    else:
        print("upgraded: %s -> %s" % (resp.current, resp.remote))
    return 0


_SET_FIELDS = (
    "title", "description", "project", "workflow", "label", "backlog",
    "notes", "needs", "reason", "tried", "step", "depends",
)


def _set_flags(args):
    ns, _extras = build_parser(COMMANDS["set"]).parse_known_args(args)
    return vars(ns)


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
    if _container.config.is_worker() and _container.config.is_live_home():
        parsed_flags = _set_flags(argv[1:]) if cmd == "set" else {}
        if not worker_permitted(cmd, parsed_flags):
            sys.stderr.write(worker_refusal_message(cmd))
            return 1
    fn = globals().get("cmd_" + cmd.replace("-", "_"))
    if fn is None:
        sys.stderr.write("not implemented: %s\n" % cmd)
        return 2
    try:
        return fn(argv[1:]) or 0
    except NodeNotFoundError as e:
        sys.stderr.write("%s\n" % e)
        return 1


def cmd_workflow(argv):
    parser = build_parser(COMMANDS["workflow"])
    a = parser.parse_args(argv)
    if a.sub is None:
        parser.print_help()
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
            resp = InitWorkflowOriginUseCase(
                c.config, c.git, c.workflow_source, c.store, c.scaffold, c.fs
            ).execute(a.name)
            print("created %s, registered as %s @ %s, personal-origin set" % (
                resp.project_dir, resp.origin, resp.sha))
            return 0
        if a.sub == "upgrade":
            resp = UpgradeWorkflowSourcesUseCase(
                c.workflow_source, c.store, c.config, c.fs
            ).execute(a.origin)
            if not resp.results and not resp.failures:
                print("no workflow sources registered")
                return 0
            for r in resp.results:
                if r.changed:
                    print("upgraded %s @ %s" % (r.origin, r.sha))
                else:
                    print("%s already current (%s)" % (r.origin, r.sha))
            for f in resp.failures:
                sys.stderr.write("lc workflow: %s: %s\n" % (f.origin, f.error))
            return 1 if resp.failures else 0
        if a.sub == "list":
            resp = ListWorkflowSourcesUseCase(c.workflow_source, c.store, c.workflow_bundle).execute()
            if not resp.origins:
                print("no workflow sources registered")
                return 0
            for v in resp.origins:
                line = "%s  %s  %s  (%d versions" % (v.name, v.current, v.url, len(v.versions))
                if v.ref:
                    line += ", ref=%s" % v.ref
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
    except WorkflowSourceError as e:
        sys.stderr.write("lc workflow: %s\n" % e)
        return 1


def cmd_show(argv):
    a = build_parser(COMMANDS["show"]).parse_args(argv)
    resp = ShowNodeUseCase(_container.store, _flow()).execute(ShowNodeInput(step=a.id))
    print(json.dumps(resp.as_dict(), indent=2))
    return 0


def cmd_peek(argv):
    a = build_parser(COMMANDS["peek"]).parse_args(argv)
    try:
        resp = PeekStepUseCase(
            _container.store, _flow(), _container.workflow_source
        ).execute(PeekStepInput(node_id=a.id, stage=a.stage))
    except KeyError:
        sys.stderr.write("unknown node '%s'\n" % a.id)
        return 1
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print("# %s @ %s\n\n%s" % (a.stage, resp.pin, resp.body))
    return 0


def cmd_claim(argv):
    a = build_parser(COMMANDS["claim"]).parse_args(argv)
    try:
        resp = ClaimStepUseCase(
            _container.store, _flow(), _worktrees(), _container.workers, _container.config
        ).execute(ClaimInput(role=a.role))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    except RegistryUnreadable as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if resp is None:
        return 0
    print(json.dumps(resp.as_dict(), indent=2))
    return 0


def cmd_spawn(argv):
    a = build_parser(COMMANDS["spawn"]).parse_args(argv)
    return 0 if _container.spawner.spawn_worker(a.role) else 1


def cmd_ps(argv):
    a = build_parser(COMMANDS["ps"]).parse_args(argv)
    try:
        rows = ListWorkersUseCase(_container.workers, _container.store).execute().workers
    except RegistryUnreadable as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if not a.all:
        rows = [w for w in rows if w["alive"]]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for w in rows:
            print(
                "  %-11s step=%-18s pid=%s %s"
                % (w.get("stage") or w["role"], w.get("step") or "-", w["pid"],
                   "alive" if w["alive"] else "dead")
            )
    return 0


def cmd_logs(argv):
    a = build_parser(COMMANDS["logs"]).parse_args(argv)
    try:
        path = (
            ResolveLogUseCase(_container.store, _container.workers, _container.config)
            .execute(ResolveLogInput(target=a.target))
            .path
        )
    except RegistryUnreadable as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if not path or not os.path.exists(path):
        sys.stderr.write("no log for %s\n" % a.target)
        return 1

    def emit(line):
        r = render_log_line(line)
        if r is not None:
            print(r, flush=True)

    if a.f:
        offset = 0
        buf = b""
        try:
            while True:
                data, offset = _container.worker_log.read_from(path, offset)
                if not data:
                    time.sleep(0.3)
                    continue
                buf += data
                *complete, buf = buf.split(b"\n")
                for raw in complete:
                    emit(raw.decode("utf-8", errors="replace"))
        except KeyboardInterrupt:
            pass
    else:
        for line in _container.worker_log.iter_lines(path):
            emit(line)
    return 0


def cmd_advance(argv):
    a = build_parser(COMMANDS["advance"]).parse_args(argv)
    resp = AdvanceStepUseCase(_container.store, _flow()).execute(
        AdvanceInput(step=a.id, outcome=a.outcome)
    )
    if resp.next_step:
        print(resp.next_step)
    return 0


def cmd_ready_roles(argv):
    build_parser(COMMANDS["ready-roles"]).parse_args(argv)
    print(" ".join(ready_roles()))
    return 0


def cmd_specs_dir(argv):
    a = build_parser(COMMANDS["specs-dir"]).parse_args(argv)
    project = _container.store.get_project(SPECS_WORKSPACE)
    if project is None or not project.local_path:
        sys.stderr.write("no '%s' project registered - run `lc init`\n" % SPECS_WORKSPACE)
        return 1
    root = project.local_path
    if not a.check:
        print(root)
        return 0
    expected = project.remote
    if not expected:
        sys.stderr.write("'%s' project has no remote registered\n" % SPECS_WORKSPACE)
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
    unknown_display = an["unknown_display"]
    unknown_pass_ends = an["unknown_pass_ends"]
    unreachable_pass_ends = an["unreachable_pass_ends"]
    hook_phase_mismatches = an["hook_phase_mismatches"]
    unresolved_hook_targets = an["unresolved_hook_targets"]

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
                    "provided": an["provided"],
                    "hooks": hooks,
                    "unreachable": unreachable,
                    "missing_inputs": missing,
                    "conflicts": dups,
                    "phase_gaps": phase_gaps,
                    "unknown_phases": unknown_phases,
                    "phase_conflicts": phase_conflicts,
                    "unknown_display": unknown_display,
                    "unknown_pass_ends": unknown_pass_ends,
                    "unreachable_pass_ends": unreachable_pass_ends,
                    "hook_phase_mismatches": hook_phase_mismatches,
                    "unresolved_hook_targets": unresolved_hook_targets,
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
            "warning: no entry step (none requires only %s)\n" % ", ".join(an["provided"])
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
    for hook, gate, gate_phase, target, target_phase in hook_phase_mismatches:
        sys.stderr.write(
            "phase: %s on '%s' (phase '%s') targets '%s' in a different phase ('%s')\n"
            % (hook, gate, gate_phase, target, target_phase)
        )
    for hook, gate, target in unresolved_hook_targets:
        sys.stderr.write(
            "%s on '%s' targets '%s', which resolves to nothing\n" % (hook, gate, target)
        )
    if unknown_display:
        sys.stderr.write(
            "display phrase declared for a stage this bundle does not reference: %s\n"
            % ", ".join(unknown_display)
        )
    if unknown_pass_ends:
        sys.stderr.write(
            "pass-end: declared for a stage this bundle does not reference: %s\n"
            % ", ".join(unknown_pass_ends)
        )
    if unreachable_pass_ends:
        sys.stderr.write(
            "pass-end: names an outcome the stage cannot emit (no such edge): %s\n"
            % ", ".join(unreachable_pass_ends)
        )
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
    if graph.pass_ends:
        print("  pass ends    %s" % ", ".join(
            "%s %s" % pair for pair in sorted(graph.pass_ends)))
    print(
        "  steps        %s"
        % ", ".join(
            display_stage(assembled.step_def(s).display, s) for s in assembled.steps()
        )
    )
    return 0


def _workflow_simulate(selector):
    scratch = tempfile.mkdtemp(prefix="lc-simulate-")
    try:
        sim = SimulationContainer(_container, scratch)
        use_case = WorkflowSimulateUseCase(
            sim.store, sim.flow, sim.worktrees, sim.claim, sim.complete, sim.projects_root,
            sim.git, sim.spin, scaffold=sim.scaffold, github_factory=ScriptedGitHub,
            config=sim.config,
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
    a = build_parser(COMMANDS["done"]).parse_args(argv)
    note = " ".join(a.note) if a.note else None
    node_type = _container.store.type_of(a.id)
    if node_type is None:
        sys.stderr.write("unknown node '%s'\n" % a.id)
        return 1
    if node_type == "item" and note:
        sys.stderr.write("--note belongs to a step, not an item\n")
        return 2
    if node_type == "step" and a.disposition:
        sys.stderr.write("--disposition belongs to an item, not a step\n")
        return 2
    try:
        if node_type == "step":
            resp = CompleteStepUseCase(
                _container.store, _flow(), _worktrees(), _container.config).execute(
                CompleteInput(step=a.id, outcome=a.outcome, note=note)
            )
            if resp.next_step:
                print(resp.next_step)
        else:
            disposition = a.disposition
            if disposition is None:
                item = _container.store.get_node(a.id)
                disposition = _flow().flow_for(item).disposition_for(a.outcome)
            if disposition is None:
                sys.stderr.write(
                    "outcome '%s' is not bundle-declared; pass --disposition "
                    "{completed,aborted} explicitly\n" % a.outcome
                )
                return 2
            CloseItemUseCase(_container.store, _worktrees()).execute(
                CloseItemInput(item=a.id, reason=a.outcome, disposition=disposition)
            )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    return 0


def cmd_trace(argv):
    a = build_parser(COMMANDS["trace"]).parse_args(argv)
    try:
        resp = TraceUseCase(_container.store, _container.workers, _container.config).execute(
            TraceInput(item=a.item)
        )
    except RegistryUnreadable as e:
        sys.stderr.write("%s\n" % e)
        return 1
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
    build_parser(COMMANDS["sweep"]).parse_args(argv)
    result = _container.sweep().execute(
        time.time(), _container.config.max_boot_seconds(), _container.config.stall_seconds()
    )
    for bid in result.swept:
        print("swept %s" % bid)
    for bid in result.preserved:
        print("preserved %s" % bid)
    for bid in result.capture_failed:
        sys.stderr.write("failed to preserve uncommitted work for %s\n" % bid)
    for bid in result.parked:
        print("parked %s" % bid)
    for spawnid in result.killed:
        print("killed %s" % spawnid)
    if result.pruned:
        print(
            "pruned %d dead worker entr%s" % (result.pruned, "y" if result.pruned == 1 else "ies")
        )
    return 0


def cmd_restore(argv):
    a = build_parser(COMMANDS["restore"]).parse_args(argv)
    if a.list:
        now = time.time()
        for snap in _container.backup.list_snapshots():
            print("%s  age=%ds" % (snap.name, int(now - snap.taken_at)))
        return 0
    try:
        resp = RestoreStoreUseCase(
            _container.lock, _container.store, _container.backup, _container.config
        ).execute(RestoreInput(snapshot=a.snapshot, force=a.force))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print("restored %s (age %ds)" % (resp.snapshot, int(time.time() - resp.taken_at)))
    return 0


def cmd_doctor(argv):
    a = build_parser(COMMANDS["doctor"]).parse_args(argv)
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


def cmd_backfill_usage(argv):
    a = build_parser(COMMANDS["backfill-usage"]).parse_args(argv)
    try:
        resp = BackfillUsageUseCase(
            _container.store, _container.fs, _container.workers, _container.config,
            _container.worker_log, _container.claude_stream,
        ).execute(repair=a.repair)
    except RegistryUnreadable as e:
        sys.stderr.write("%s\n" % e)
        return 1
    ledger_total = len(_container.store.usage_backfilled_logs())
    print(
        "backfilled %d/%d logs (%d matched, %d orphaned (step no longer exists), "
        "%d unmatched, %d left for live capture); %d/%d ledger rows reclassified, "
        "%d recovered usage"
        % (resp.stored, resp.total, resp.matched, resp.orphaned, resp.unmatched,
           resp.skipped_pending, resp.reclassified, ledger_total, resp.recovered)
    )
    if a.repair:
        print(
            "repair: %d/%d steps corrected, %d ledgered logs missing on disk"
            % (resp.repair_corrected, resp.repair_examined, resp.repair_missing_logs)
        )
    return 0


def cmd_inbox(argv):
    a = build_parser(COMMANDS["inbox"]).parse_args(argv)
    flow_service = _flow()
    resp = InboxUseCase(_container.store, flow_service).execute(InboxInput(n=a.n))
    for line in render_inbox(resp.rows, _container.config.max_title_length(), flow_service):
        print(line)
    return 0


def cmd_backlog(argv):
    a = build_parser(COMMANDS["backlog"]).parse_args(argv)
    resp = BacklogUseCase(_container.store, _flow()).execute(
        BacklogInput(n=a.n, project=a.project))
    for line in render_backlog(resp.rows, _container.config.max_title_length()):
        print(line)
    return 0


def cmd_search(argv):
    a = build_parser(COMMANDS["search"]).parse_args(argv)
    resp = SearchUseCase(_container.store).execute(SearchInput(text=a.text))
    for line in render_search(resp.matches, _container.config.max_title_length()):
        print(line)
    return 0


def cmd_active(argv):
    build_parser(COMMANDS["active"]).parse_args(argv)
    for t in ActiveStepsUseCase(_container.store).execute().steps:
        print("  %s  %s" % (t.id, t.title))
    return 0


def cmd_queue(argv):
    a = build_parser(COMMANDS["queue"]).parse_args(argv)
    steps = QueueUseCase(_container.store).execute(QueueInput(n=a.n)).steps
    for line in render_queue(steps, _container.config.max_title_length()):
        print(line)
    return 0


def cmd_tui(argv):
    build_parser(COMMANDS["tui"]).parse_args(argv)
    from lightcycle.adapters.tui.app import run
    run(_container)
    return 0


_NODE_TYPES = ("item", "step")


def cmd_new(argv):
    a = build_parser(COMMANDS["new"]).parse_args(argv)
    if a.type not in _NODE_TYPES:
        sys.stderr.write(
            "unknown type '%s'; expected item | step (item > step)\n" % a.type
        )
        return 2
    try:
        validate_title(_container.config, a.title)
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if a.type == "step" and a.description:
        sys.stderr.write("--description belongs to an item, not a step; use --note\n")
        return 2
    if a.type == "item" and a.note:
        sys.stderr.write("--note belongs to a step, not an item; use --description\n")
        return 2
    if a.type == "item":
        if a.parent:
            sys.stderr.write("items are top-level; --parent applies to 'lc new step'\n")
            return 2
        if not (a.description or "").strip():
            sys.stderr.write(
                "--description is required for 'lc new item'; a paragraph or two describing "
                "the work, which the entry step reads\n"
            )
            return 2
        if not a.project:
            sys.stderr.write(
                "no --project given; minted with the global shortcode '%s'\n"
                % _container.config.shortcode()
            )
        try:
            resp = CreateItemUseCase(_container.store, _container.config).execute(
                CreateItemInput(
                    title=a.title, description=a.description, project=a.project,
                    workflow=a.workflow, repo=a.repo, backlog=a.backlog,
                )
            )
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
        print(resp.id)
    else:
        if not a.step:
            sys.stderr.write(
                "--step <name> is required for 'lc new step'; it determines the owning role\n"
            )
            return 2
        if not a.parent:
            sys.stderr.write(
                "--parent <item> is required for 'lc new step'; it names the owning item\n"
            )
            return 2
        try:
            resp = CreateStepUseCase(_container.store, _flow()).execute(
                CreateStepInput(
                    title=a.title, step=a.step, parent=a.parent, workflow=a.workflow,
                    note=a.note,
                )
            )
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
        print(resp.id)
    return 0


_SET_FLAG_OWNERS = {
    "title": (None,), "description": (None,), "project": (None,),
    "label": (None,), "backlog": (None,), "notes": (None,),
    "workflow": (None, "active"),
    "step": ("active",),
    "depends": ("active",),
    "needs": ("waiting",), "reason": ("waiting",), "tried": ("waiting",),
    "unset": (None,),
}
_SET_KNOWN_STATES = (None, "active", "waiting", "ready", "in_progress")

_SET_UNSETTABLE_FIELDS = ("description", "project", "workflow", "notes")

_SET_UNSET_REFUSAL_REASONS = {
    "title": "a title must not be blank; there is nothing to clear, only to replace",
    "label": "there is no way to clear a label this way",
    "needs": "a park's fields are cleared as a whole, via --state ready",
    "reason": "a park's fields are cleared as a whole, via --state ready",
    "tried": "a park's fields are cleared as a whole, via --state ready",
    "backlog": "backlog is a list of ids to resolve, not a value to clear",
    "step": "step is a one-shot input to activation, not a persisted field",
}


def _set_state_label(state):
    return "--state %s" % state if state is not None else "no --state"


def _reject_flags_ineffective_for_state(a):
    if a.state not in _SET_KNOWN_STATES:
        return None
    offending = [
        f for f in _SET_FLAG_OWNERS
        if getattr(a, f) is not None and a.state not in _SET_FLAG_OWNERS[f]
    ]
    if not offending:
        return None
    parts = [
        "--%s (needs %s)" % (f, " or ".join(_set_state_label(s) for s in _SET_FLAG_OWNERS[f]))
        for f in offending
    ]
    return "%s does not accept %s\n" % (_set_state_label(a.state), "; ".join(parts))


def _reject_blank_values(a):
    for f in ("title", "description", "project", "workflow", "label", "notes", "tried"):
        if getattr(a, f, None) != "":
            continue
        if f in _SET_UNSETTABLE_FIELDS:
            return "--%s \"\" is refused; use --unset %s to clear it\n" % (f, f)
        return "--%s \"\" is refused; %s\n" % (
            f, _SET_UNSET_REFUSAL_REASONS.get(f, "it may not be blank")
        )
    return None


def _reject_unset_contradiction(given_values, unset_fields):
    overlap = given_values & unset_fields
    if not overlap:
        return None
    named = ", ".join("--%s" % f for f in sorted(overlap))
    return "given a value and --unset in the same call: %s\n" % named


def _reject_unset_targets(unset_fields):
    bad = sorted(f for f in unset_fields if f not in _SET_UNSETTABLE_FIELDS)
    if not bad:
        return None
    parts = [
        "--unset %s: %s" % (f, _SET_UNSET_REFUSAL_REASONS.get(f, "not a field lc set can clear"))
        for f in bad
    ]
    return "; ".join(parts) + "\n"


def _named(node_type):
    return "an item" if node_type == "item" else "a step"


def _render_refusal(refusal):
    if isinstance(refusal, FieldRefusal):
        return _render_field_refusal(refusal)
    return _render_state_refusal(refusal)


def _render_field_refusal(r):
    named = ", ".join("--%s" % f for f in r.fields)
    verb = "belong" if len(r.fields) > 1 else "belongs"
    if r.owner is None:
        return "%s %s to no structure" % (named, verb)
    return "%s %s to %s, not %s" % (named, verb, _named(r.owner), _named(r.requested_type))


def _render_state_refusal(r):
    if r.owner is None:
        return "unknown --state %r; use %s" % (r.state, ", ".join(r.allowed))
    takes = ", ".join("--state %s" % s for s in r.allowed)
    return "--state %s applies to %s, not %s; %s takes %s" % (
        r.state, _named(r.owner), _named(r.requested_type), _named(r.requested_type), takes,
    )


def cmd_set(argv):
    a = build_parser(COMMANDS["set"]).parse_args(argv)
    node_type = _container.store.type_of(a.id)
    if node_type is None:
        sys.stderr.write("unknown node '%s'\n" % a.id)
        return 1
    given_values = {f for f in _SET_FIELDS if getattr(a, f, None) is not None}
    unset_fields = set(a.unset or [])
    msg = (
        _reject_blank_values(a)
        or _reject_unset_contradiction(given_values, unset_fields)
        or _reject_unset_targets(unset_fields)
    )
    if msg:
        sys.stderr.write(msg)
        return 2
    given = given_values | unset_fields
    refusal = refuse_fields(node_type, given) or refuse_state(node_type, a.state)
    if refusal is not None:
        sys.stderr.write("%s\n" % _render_refusal(refusal))
        return 2
    if not given and a.state is None:
        sys.stderr.write("nothing to set on '%s'\n" % a.id)
        return 2
    msg = _reject_flags_ineffective_for_state(a)
    if msg:
        sys.stderr.write(msg)
        return 2
    try:
        if a.title:
            validate_title(_container.config, a.title)
        if a.state == "active":
            depends_ids = a.depends or []
            for node_id in depends_ids:
                try:
                    _container.store.get_node(node_id)
                except KeyError:
                    sys.stderr.write("unknown node '%s'\n" % node_id)
                    return 1
            resp = ActivateItemUseCase(
                _container.store, _flow(), _container.git, _container.config, _container.scaffold
            ).execute(
                ActivateItemInput(
                    item=a.id, workflow=a.workflow, step=a.step, deps=depends_ids
                )
            )
            print(resp.step)
            return 0
        if a.state == "waiting":
            if not a.needs:
                sys.stderr.write("--state waiting requires --needs (what the human must decide)\n")
                return 2
            if not a.reason:
                sys.stderr.write(
                    "--state waiting requires --reason (what happened that led to this)\n"
                )
                return 2
            BlockStepUseCase(_container.store).execute(
                BlockInput(step=a.id, needs=a.needs, reason=a.reason, tried=a.tried)
            )
            return 0
        if a.state == "ready":
            _container.unblock_step_use_case().execute(UnblockInput(step=a.id))
            return 0
        if a.state == "in_progress":
            ReopenItemUseCase(_container.store).execute(ReopenItemInput(item=a.id))
            return 0

    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    workflow_pin = "" if "workflow" in unset_fields else a.workflow
    resolved_pin = None
    if a.workflow:
        try:
            node = _container.store.get_node(a.id)
        except KeyError:
            sys.stderr.write("unknown node '%s'\n" % a.id)
            return 1
        try:
            resp = ResolveWorkflowSelectionUseCase(_flow(), _container.store).execute(
                ResolveWorkflowSelectionInput(
                    node_id=node.id, node_type=node.type, selector=a.workflow))
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
        workflow_pin = resp.value
        if resp.resolved:
            resolved_pin = resp.value
    effective_description = "" if "description" in unset_fields else a.description
    effective_project = "" if "project" in unset_fields else a.project
    effective_notes = "" if "notes" in unset_fields else a.notes
    try:
        tid = EditNodeUseCase(_container.store).execute(
            EditNodeInput(step=a.id, title=a.title, description=effective_description,
                          project=effective_project, workflow=workflow_pin,
                          label=a.label, notes=effective_notes)
        ).id
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if resolved_pin:
        print(resolved_pin)
    if a.backlog:
        try:
            link_resolves(_container.store, tid, a.backlog)
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
    return 0


_REFLECTION_TYPES = ("reflection", "feedback")


def cmd_attach(argv):
    a = build_parser(COMMANDS["attach"]).parse_args(argv)
    value = a.value
    if a.file:
        data = _container.fs.read_bytes(a.file)
        if data is None:
            sys.stderr.write("no such file: %s\n" % a.file)
            return 1
        value = data.decode()
        if value == "":
            sys.stderr.write("file '%s' is empty; pass a file with content\n" % a.file)
            return 1
    if a.type in _REFLECTION_TYPES:
        ReflectUseCase(_container.store, _container.fs).execute(
            ReflectInput(step=a.id, feedback=value)
        )
        return 0
    try:
        LinkArtifactUseCase(_container.store, _flow()).execute(
            LinkArtifactInput(
                item=a.id, atype=a.type, value=value, label=a.label, replace=a.replace,
                internal=a.internal, kind=a.kind,
            )
        )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    return 0


def cmd_dep(argv):
    a = build_parser(COMMANDS["dep"]).parse_args(argv)
    if a.remove:
        removed = _container.store.dep_remove(a.id, a.remove)
        if removed:
            print("removed: %s no longer blocked by %s" % (a.id, a.remove))
        else:
            print("no-op: %s was not blocked by %s" % (a.id, a.remove))
        return 0
    target = None
    for node_id in (a.id, a.needs):
        try:
            node = _container.store.get_node(node_id)
        except KeyError:
            sys.stderr.write("unknown node '%s'\n" % node_id)
            return 1
        if node_id == a.id:
            target = node
    if target.type == "step" and target.claimed_by is not None and target.state != State.DONE:
        sys.stderr.write(
            "'%s' is claimed by '%s' and already running; adding a dependency now will not "
            "stop it - ask whoever runs the pool to stop the worker if it must not proceed\n"
            % (a.id, target.claimed_by)
        )
        return 1
    _container.store.dep_add(a.id, a.needs)
    return 0


def cmd_rm(argv):
    a = build_parser(COMMANDS["rm"]).parse_args(argv)
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


def _tick_event_lines(result, ts):
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
    for sid in result.ci_released:
        lines.append("%s  %-7s  %s" % (ts, "ci-release", sid))
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
    if result.breaker_rearmed:
        reset_ts = time.strftime("%H:%M:%S", time.localtime(result.breaker_reset_at))
        lines.append("%s  %-7s  %s" % (ts, "breaker", "probe stalled, retrying after %s" % reset_ts))
    if result.spin_opened:
        lines.append(
            "%s  %-7s  %s" % (ts, "spin", "opened - workers died with no observed work")
        )
    return lines


def _state_line(result, ts, reason=None):
    state = "active=%d/%d ready=%d inflight=%d" % (
        result.alive, result.max_agents, result.ready, result.inflight_count)
    if result.pruned:
        state += " pruned=%d" % result.pruned
    if reason:
        state += " reason=%s" % reason
    return "%s  %-7s  %s" % (ts, "state", state)


def _idle_reason(result):
    if not result.ready:
        return None
    if result.breaker_open:
        return "breaker-open"
    if result.spin_open:
        return "spin-open"
    if result.spawned:
        return None
    if result.free_slots <= 0:
        return "no-free-slots"
    return "ready-role-already-inflight"


def _format_tick(result, prev_snapshot, now):
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    lines = _tick_event_lines(result, ts)
    cur = (result.alive, result.max_agents, result.ready, result.inflight_count)
    if cur != prev_snapshot or result.pruned:
        lines.append(_state_line(result, ts))
    return lines, cur


def _run_log_lines(result, now):
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    lines = _tick_event_lines(result, ts) + [_state_line(result, ts, reason=_idle_reason(result))]
    return "\n".join(lines) + "\n"


def _run_log_error(now):
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    return "%s  %-7s  tick raised, process exiting:\n%s" % (ts, "error", traceback.format_exc())


def _run_tick(tick, fs, tick_input, now):
    try:
        result = tick.execute(tick_input)
    except Exception:
        fs.append_run_log(_run_log_error(now))
        raise
    fs.append_run_log(_run_log_lines(result, now))
    return result


def _tick_failure_action(consecutive_failures, cap):
    return "raise" if consecutive_failures >= cap else "continue"


def _upgrade_notice_lines(resp):
    if resp.notice:
        return [resp.notice]
    if resp.error:
        return ["could not check for updates: %s" % resp.error]
    return []


def _stop_pool():
    resp = StopPoolUseCase(_container.workers, _container.sweep(flow=_flow())).execute(
        time.time(), _container.config.max_boot_seconds(),
        _container.config.stall_seconds(),
        shutdown_grace_seconds=_container.config.shutdown_grace_seconds(),
    )
    lines = ["lc start stopped: %d worker(s) stopped, %d step(s) reclaimed"
             % (len(resp.stopped), len(resp.reclaimed))]
    if resp.preserved:
        lines.append("  preserved uncommitted work on: %s" % ", ".join(resp.preserved))
    if resp.capture_failed:
        lines.append(
            "  COULD NOT read the worktree to preserve work on: %s - check it by hand"
            % ", ".join(resp.capture_failed)
        )
    return lines


def cmd_start(argv):
    a = build_parser(COMMANDS["start"]).parse_args(argv)
    if not require_store():
        return 1
    if a.detach:
        if a.once:
            sys.stderr.write("--detach cannot be combined with --once\n")
            return 1
        resp = StartPoolUseCase(_container.lock, _container.spawner).execute()
        if not resp.started:
            sys.stderr.write("lc start already running, pid %d\n" % resp.pid)
            return 1
        print("lc start detached, pid %d - output goes to %s"
              % (resp.pid, os.path.join(_container.config.data_root(), "logs", "run.log")))
        return 0
    lock_result = AcquireRunLockUseCase(_container.lock).execute()
    if not lock_result.acquired:
        sys.stderr.write("lc start already running, pid %d\n" % lock_result.holder_pid)
        return 1

    def _stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    try:
        tick = _container.tick(flow=_flow())
        if a.once:
            now = time.time()
            result = _run_tick(tick, _container.worker_log, TickInput(now=now), now)
            lines, _ = _format_tick(result, None, now)
            for line in lines:
                print(line)
            return 0
        interval = _container.config.poll_seconds()
        max_agents = _container.config.max_agents()
        for line in _upgrade_notice_lines(
            UpgradeNoticeUseCase(__version__, port=_container.upgrade).execute()
        ):
            print(line)
        print("lc start  poll=%ds  max-agents=%d" % (interval, max_agents))
        prev_snapshot = None
        prev_now = time.time()
        consecutive_failures = 0
        tick_failure_cap = _container.config.tick_failure_cap()
        while True:
            now = time.time()
            try:
                result = _run_tick(tick, _container.worker_log, TickInput(now=now, since=prev_now), now)
            except Exception:
                consecutive_failures += 1
                if _tick_failure_action(consecutive_failures, tick_failure_cap) == "raise":
                    raise
                time.sleep(interval)
                continue
            consecutive_failures = 0
            lines, prev_snapshot = _format_tick(result, prev_snapshot, now)
            for line in lines:
                print(line)
            prev_now = now
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nlc start stopping - press Ctrl-C again only if it hangs")
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            for line in _stop_pool():
                print(line)
        except Exception as e:
            sys.stderr.write("shutdown could not finish cleanly: %s\n" % e)
        return 0
    finally:
        ReleaseRunLockUseCase(_container.lock).execute()


def cmd_init(argv):
    build_parser(COMMANDS["init"]).parse_args(argv)
    r = InitGridUseCase(_container.store, _container.fs, _container.config).execute()
    print("lightcycle store already initialised" if r.existed else "lightcycle store initialised")
    print("config %s at %s" % ("created" if r.created else "already exists", r.config_path))
    _init_pull_default_origin()
    return 0


def cmd_project(argv):
    parser = build_parser(COMMANDS["project"])
    a = parser.parse_args(argv)
    if a.sub is None:
        parser.print_help()
        return 2
    c = _container
    try:
        if a.sub == "add":
            r = AddProjectUseCase(c.store, c.git, c.config, c.fs).execute(
                AddProjectInput(identity=a.identity, shortcode=a.shortcode, path=a.path)
            )
            if r.changed:
                print("%s -> shortcode %s%s" % (
                    r.identity, r.shortcode,
                    " at %s" % r.local_path if r.local_path else " (no local checkout)"
                ))
            else:
                print("%s already registered (shortcode %s)" % (r.identity, r.shortcode))
            return 0
        if a.sub == "list":
            for p in ListProjectsUseCase(c.store).execute():
                print("%s\t%s\t%s" % (
                    p.identity, p.shortcode or "-", p.local_path or "(not checked out)"
                ))
            return 0
        if a.sub == "rm":
            RemoveProjectUseCase(c.store).execute(a.identity)
            print("removed %s" % a.identity)
            return 0
        if a.sub == "scan":
            candidates = ScanProjectsUseCase(c.store, c.git, c.config, c.fs).execute(a.dir)
            if a.json:
                print(json.dumps([dict(cand._asdict()) for cand in candidates], indent=2))
                return 0
            for cand in candidates:
                if cand.status == "unreadable":
                    print("unreadable\t%s\t(git could not read this repo)" % cand.path)
                elif cand.status == "no-remote":
                    print("no-remote\t%s\t(%s)" % (cand.path, cand.remote or "no origin"))
                elif cand.status == "already-registered":
                    print("already-registered\t%s\t%s\tproposed %s\tregistered at %s (shortcode %s)" % (
                        cand.identity, cand.path, cand.shortcode,
                        cand.registered_path or "(no local checkout)", cand.registered_shortcode or "-",
                    ))
                else:
                    print("new\t%s\t%s\tshortcode %s" % (cand.identity, cand.path, cand.shortcode))
            return 0
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1


def _init_pull_default_origin():
    origin = _container.config.default_origin()
    if _container.workflow_source.read_registry(origin) is not None:
        return
    try:
        url = _container.config.workflows_remote()
    except ConfigError:
        sys.stderr.write(
            "workflows-remote is not set; run `lc config --edit` to set it, then "
            "`lc workflow add <url> --name %s`\n" % origin
        )
        return
    try:
        resp = AddWorkflowSourceUseCase(
            _container.workflow_source, _container.store, _container.config, _container.fs
        ).execute(url=url, ref="main", name=origin)
        print("pulled %s workflows @ %s" % (resp.origin, resp.sha))
    except WorkflowSourceError as e:
        sys.stderr.write(
            "could not pull workflows: %s\nrun `lc workflow add %s --name %s` once reachable\n"
            % (e, url, origin))


def cmd_config(argv):
    a = build_parser(COMMANDS["config"]).parse_args(argv)
    if a.edit:
        _container.config.ensure_config()
        editor = _container.config.editor()
        return _container.launcher.edit(editor, _container.config.config_path())
    p = _container.config.config_path()
    print("config: %s" % p)
    print("exists" if os.path.exists(p) else "not found - run `lc init` to seed it")
    for s in _container.config.resolved_settings():
        if s.key == "personal-origin" and not s.value:
            print("%s: (not set)" % s.key)
        elif s.state == "unset":
            print("%s: (not set - run `lc init`)" % s.key)
        elif s.state == "env":
            print("%s: %s (env: %s)" % (s.key, s.value, s.env_var))
        elif s.state == "default":
            print("%s: %s (default)" % (s.key, s.value))
        else:
            print("%s: %s" % (s.key, s.value))
    return 0


def cmd_status(argv):
    a = build_parser(COMMANDS["status"]).parse_args(argv)
    lanes = StatusUseCase(_container.store).execute().lanes
    if a.json:
        print(json.dumps({k: [t.as_dict() for t in v] for k, v in lanes.items()}, indent=2))
    else:
        flow_service = _flow()
        for key in ("inbox", "active", "queue"):
            print("== %s (%d) ==" % (key, len(lanes[key])))
            for t in lanes[key]:
                suffix = "  [blocked by %s]" % ", ".join(sorted(t.blocked_by)) if t.blocked_by else ""
                step_suffix = (
                    "  %s" % display_stage(flow_service.display_for(t), t.step) if t.step else ""
                )
                print("  %s  %s%s%s" % (t.id, t.title, suffix, step_suffix))
    return 0


def cmd_worklog(argv):
    a = build_parser(COMMANDS["worklog"]).parse_args(argv)
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
    if resp.unreadable:
        print("\n%d reflection(s) could not be parsed and were excluded:" % len(resp.unreadable))
        for value in resp.unreadable:
            print("  %s" % (value[:200] + "…" if len(value) > 200 else value))
    if resp.feedback:
        print("\nFeedback (read it; an analyser agent can later):")
        for item in resp.feedback:
            print("  [%s] %s" % (item.step, item.text))
    elif resp.reflection_count == 0:
        print("no reflections yet - agents call `lc attach <step> reflection` before `lc done`")
    print("\nPer-item signals:")
    for row in resp.item_signals:
        sig_str = "  ".join(_fmt_signal(k, row.signals[k]) for k in sorted(row.signals))
        duration = row.total_duration()
        duration_str = "unknown" if duration is None else format_elapsed(duration)
        print(
            "  %-20s  %s  (N=%d)  duration=%s"
            % (row.item.id, sig_str, row.reflections, duration_str)
        )


def _fmt_signal(name, by_model):
    total = sum(by_model.values())
    if not by_model:
        return "%s=%d" % (name, total)
    breakdown = ",".join("%s:%d" % (m, by_model[m]) for m in sorted(by_model))
    return "%s=%d(%s)" % (name, total, breakdown)


def cmd_retro(argv):
    parser = build_parser(COMMANDS["retro"])
    a = parser.parse_args(argv)

    flags = [a.id is not None, a.since is not None, a.last is not None, a.project is not None,
             a.pending]
    if sum(flags) != 1:
        parser.error("provide exactly one of: <id>, --since, --last, --project, --pending")

    inp = RetroInput(subject=a.id, since=a.since, last=a.last, project=a.project,
                      pending=a.pending)
    resp = RetroUseCase(_container.store, _flow()).execute(inp)
    interval = _container.config.retro_interval_reflections() if a.pending else None
    _print_retro(resp, interval)
    return 0
