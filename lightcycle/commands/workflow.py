import contextlib
import io
import json
import sys

from lightcycle.cli_commands import COMMANDS, build_parser
from lightcycle.render import (
    display_stage, render_workflow_mermaid,
)

from lightcycle.application.errors import UseCaseError
from lightcycle.application.workflows.add import AddWorkflowSourceUseCase
from lightcycle.application.workflows.bundle_check import undeclared_target_message
from lightcycle.application.workflows.script_tooling import WorkflowScripts
from lightcycle.application.workflows.set_writable import SetOriginWritableUseCase
from lightcycle.application.workflows.check_dir import (
    DIR_ORIGIN,
    DIR_SHA,
    CheckWorkflowDirUseCase,
    DirWorkflowSource,
)
from lightcycle.domain.workflows.identity import format_pin
from lightcycle.domain.workflows.identity import parse_pin
from lightcycle.application.workflows.init_origin import InitWorkflowOriginUseCase
from lightcycle.application.workflows.list import ListWorkflowSourcesUseCase
from lightcycle.application.workflows.lifecycle import directory_lifecycle_problems
from lightcycle.application.workflows.purge import PurgeWorkflowDataUseCase
from lightcycle.application.workflows.remove import RemoveWorkflowSourceUseCase
from lightcycle.application.workflows.simulate import SimulateInput
from lightcycle.application.workflows.pin_drift import PinDrift
from lightcycle.application.workflows.repin_in_flight import RepinInFlightItemsUseCase
from lightcycle.application.workflows.upgrade import UpgradeWorkflowSourcesUseCase
from lightcycle.application.flow import (
    FlowCheckInput,
    FlowCheckUseCase,
)
from lightcycle.container import (
    make_flow_service,
)
from lightcycle.ports.workflow_source import WorkflowSourceError


from lightcycle.commands.context import container, flow as _flow



def _prune_warning(origin, error):
    return "lc workflow: %s is registered but pruning old versions failed: %s\n" % (origin, error)


def cmd_workflow(argv):
    parser = build_parser(COMMANDS["workflow"])
    a = parser.parse_args(argv)
    if a.sub is None:
        parser.print_help()
        return 2
    if a.sub == "check":
        if a.dir:
            return _workflow_check_dir(a.dir, a.workflow, a.json)
        if a.workflow is None:
            sys.stderr.write("lc workflow check: pass a workflow or --dir <bundle-dir>\n")
            return 1
        return _workflow_check_pinned(a.workflow, a.json)
    if a.sub == "describe":
        return _workflow_describe(a.workflow, a.mermaid)
    if a.sub == "simulate":
        return _workflow_simulate(a.workflow, a.trace)
    c = container()
    try:
        if a.sub == "add":
            resp = AddWorkflowSourceUseCase(
                c.workflow_source, c.store, c.config, c.fs, c.workflow_lifecycle()
            ).execute(
                url=a.url, ref=a.ref, name=a.name, writable=a.writable)
            msg = "added %s @ %s" % (resp.origin, resp.sha)
            if resp.pruned:
                msg += " (pruned %d)" % len(resp.pruned)
            print(msg)
            if resp.prune_error:
                sys.stderr.write(_prune_warning(resp.origin, resp.prune_error))
            return 0
        if a.sub == "init":
            resp = InitWorkflowOriginUseCase(
                c.config, c.git, c.workflow_source, c.store, c.scaffold, c.fs,
                c.workflow_lifecycle()
            ).execute(a.name)
            print("created %s, registered as %s @ %s, personal-origin set" % (
                resp.project_dir, resp.origin, resp.sha))
            return 0
        if a.sub == "upgrade":
            resp = UpgradeWorkflowSourcesUseCase(
                c.workflow_source, c.store, c.config, c.fs, c.workflow_lifecycle(),
                RepinInFlightItemsUseCase(
                    c.store, c.workflow_source, _flow(),
                    PinDrift(c.workflow_source, c.workflow_bundle, c.config), c.config, c.worker_log)
            ).execute(a.origin, repin=not a.no_repin)
            if not resp.results and not resp.failures:
                print("no workflow sources registered")
                return 0
            for r in resp.results:
                if r.changed:
                    print("upgraded %s @ %s" % (r.origin, r.sha))
                    for line in _repin_lines(r.repin):
                        print(line)
                else:
                    print("%s already current (%s)" % (r.origin, r.sha))
                if r.prune_error:
                    sys.stderr.write(_prune_warning(r.origin, r.prune_error))
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
                line += ", writable" if v.writable else ", read-only"
                print(line + ")")
                for wf, summary in v.workflows:
                    print("  %s%s" % (wf, "  - %s" % summary if summary else ""))
            return 0
        if a.sub == "set":
            resp = SetOriginWritableUseCase(c.workflow_source).execute(a.origin, a.writable)
            print("%s is now %s" % (resp.origin, "writable" if resp.writable else "read-only"))
            return 0
        if a.sub == "rm":
            resp = RemoveWorkflowSourceUseCase(
                c.workflow_source, c.store, c.workflow_lifecycle()
            ).execute(a.origin)
            print("removed %s" % resp.origin)
            for path in resp.kept_data_dirs:
                print("data kept at %s; lc workflow purge %s removes it" % (path, resp.origin))
            return 0
        if a.sub == "purge":
            resp = PurgeWorkflowDataUseCase(c.workflow_lifecycle()).execute(a.origin, a.workflow)
            if not resp.removed:
                print("no data to purge for %s" % a.origin)
            for path in resp.removed:
                print("purged %s" % path)
            return 0
    except WorkflowSourceError as e:
        sys.stderr.write("lc workflow: %s\n" % e)
        return 1


def _workflow_check_dir(directory, name, as_json):
    c = container()
    try:
        resp = CheckWorkflowDirUseCase(
            c.workflow_bundle, c.fs, c.config.version(), c.config).execute(directory, name)
    except WorkflowSourceError as e:
        sys.stderr.write("lc workflow check: %s\n" % e)
        return 1
    flow = make_flow_service(
        c.workflow_bundle, c.store, c.config, DirWorkflowSource(directory))
    rc = 1 if resp.problems else 0
    for problem in resp.problems:
        sys.stderr.write("%s\n" % problem)
    multi = len(resp.names) > 1
    json_out = {}
    for n in resp.names:
        if multi and not as_json:
            print("== %s ==" % n)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf if as_json else sys.stdout):
            wf_rc = _workflow_check(format_pin(DIR_ORIGIN, n, DIR_SHA), as_json, flow)
        for message in resp.lifecycle_problems.get(n, []):
            sys.stderr.write("%s: %s\n" % (n, message))
            wf_rc = 1
        for message in resp.reference_problems.get(n, []):
            sys.stderr.write("%s: %s\n" % (n, message))
            wf_rc = 1
        if as_json and buf.getvalue():
            json_out[n] = json.loads(buf.getvalue())
        if multi and not as_json:
            print("%s: %s" % (n, "ok" if wf_rc == 0 else "FAILED"))
        rc = rc or wf_rc
    if as_json and json_out:
        print(json.dumps(next(iter(json_out.values())) if not multi else json_out, indent=2))
    return rc


def _workflow_check_pinned(selector, as_json):
    rc = _workflow_check(selector, as_json)
    c = container()
    try:
        pin = _flow().resolve_selection(selector)
    except ValueError:
        return rc
    parsed = parse_pin(pin)
    if parsed is None:
        return rc
    origin, name, sha = parsed
    directory = c.workflow_source.pinned_bundle(origin, sha)
    problems = directory_lifecycle_problems(c.workflow_bundle, c.fs, directory, name)
    problems = problems + WorkflowScripts(c.workflow_bundle, c.fs, c.config).problems(directory, name)
    for message in problems:
        sys.stderr.write("%s: %s\n" % (name, message))
    return 1 if problems else rc


def _workflow_check(selector, as_json, flow=None):
    flow = flow or _flow()
    try:
        selected = flow.resolve_selection(selector)
        resp = FlowCheckUseCase(flow).execute(FlowCheckInput(workflow=selected))
    except ValueError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    owner, routes, an = resp.owner, resp.routes, resp.analysis
    steps, req, opt, prod = an["steps"], an["req"], an["opt"], an["prod"]
    entries, terminals = an["entries"], an["terminals"]
    unreachable, missing, ok = an["unreachable"], an["missing"], an["ok"]
    phase_gaps = an["phase_gaps"]
    unknown_phases = an["unknown_phases"]
    phase_conflicts = an["phase_conflicts"]
    unknown_display = an["unknown_display"]
    undeclared_edge_targets = an["undeclared_edge_targets"]
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
                    "phase_gaps": phase_gaps,
                    "unknown_phases": unknown_phases,
                    "phase_conflicts": phase_conflicts,
                    "unknown_display": unknown_display,
                    "undeclared_edge_targets": undeclared_edge_targets,
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
    for frm, outcome, target in undeclared_edge_targets:
        sys.stderr.write(undeclared_target_message(frm, outcome, target) + "\n")
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


def _workflow_simulate(selector, trace=False):
    with container().simulation() as use_case:
        try:
            resp = use_case.execute(SimulateInput(workflow=selector))
        except (ValueError, UseCaseError) as e:
            sys.stderr.write("%s\n" % e)
            return 1
        if resp.ok:
            if trace:
                for line in resp.trace:
                    print(line)
            print("pass")
            return 0
        if trace:
            for line in resp.trace:
                sys.stderr.write("%s\n" % line)
        for v in resp.violations:
            sys.stderr.write("%s\n" % v)
        sys.stderr.write("simulate: %d violation(s)\n" % len(resp.violations))
        return 1


def _repin_lines(repin):
    if repin is None:
        return []
    lines = [
        'repinned %s "%s" -> %s: changed steps ahead: %s' % (
            r.id, r.title, r.pin, ", ".join(r.changed_steps))
        for r in repin.repinned
    ]
    lines += ["held %s: %s" % (h.id, h.reason) for h in repin.held]
    lines.append(
        "left %d in-flight item(s) on their pin (nothing changed ahead, or held)" % repin.left)
    return lines
