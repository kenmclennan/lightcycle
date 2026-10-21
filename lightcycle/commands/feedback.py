import json
import sys
import time

from lightcycle.cli_commands import COMMANDS, build_parser
from lightcycle.render import (
    format_elapsed,
)

from lightcycle.application.feedback import (
    RetroInput,
    RetroUseCase,
    WorklogInput,
    WorklogUseCase,
)
from lightcycle.application.work.resolve_project_ref import resolve_project_ref
from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect.check_guidance import CheckGuidanceUseCase
from lightcycle.application.inspect.show_audit_criteria import ShowAuditCriteriaUseCase
from lightcycle.domain.work.audit_criteria import UnknownMaterial
from lightcycle.application.inspect.report_guidance import ReportGuidanceUseCase, parse_since
from lightcycle.domain.guidance.conventions import CONVENTIONS_TEXT
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE


from lightcycle.commands.context import container, flow as _flow



def _project_dir(identity, remote_label, check, subject):
    project = container().store.get_project(identity)
    if project is None or not project.local_path:
        sys.stderr.write("no '%s' project registered - run `lc init`\n" % identity)
        return 1
    root = project.local_path
    if not check:
        print(root)
        return 0
    expected = project.remote
    if not expected:
        sys.stderr.write("'%s' project has no remote registered\n" % identity)
        return 1
    if not container().git.is_git_repo(root):
        sys.stderr.write("%s dir %s is not a git repo\n" % (subject, root))
        return 1
    origin = container().git.remote_url(root)
    if origin != expected:
        sys.stderr.write(
            "%s dir %s origin (%s) does not match %s (%s)\n"
            % (subject, root, origin or "none", remote_label, expected)
        )
        return 1
    print("ok: %s matches %s (%s)" % (root, remote_label, expected))
    return 0


def cmd_specs_dir(argv):
    a = build_parser(COMMANDS["specs-dir"]).parse_args(argv)
    return _project_dir(
        container().config.context_artifact_project(), "specs-remote", a.check, "specs"
    )


def _guidance_flags_text(row):
    return "; ".join("%s (%s)" % (f.name, f.evidence) for f in row.flags) or "-"


def _guidance_approval_text(row):
    approval = row.approval
    if approval.state == "unknown":
        return "unknown"
    text = "-"
    if approval.state == "known":
        text = "%s %s" % (approval.date[:10], approval.sha[:7])
        if approval.pr:
            text += " #%s" % approval.pr
    if row.verified:
        text = "%s verified: %s" % (text, row.verified) if text != "-" else "verified: %s" % row.verified
    return text


def cmd_guidance(argv):
    a = build_parser(COMMANDS["guidance"]).parse_args(argv)
    c = container()
    try:
        since = parse_since(a.since)
        report = ReportGuidanceUseCase(
            c.store, c.fs, c.git, c.github, c.config).execute(time.time(), since)
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if a.json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    print("window: since %s" % report.since if report.since else "window: all steps in the store")
    lines = [("ID", "STATUS", "DELIVERED", "CITED", "OPPORTUNITY", "LAST DELIVERED", "APPROVED", "FLAGS")]
    for r in report.rows:
        lines.append((
            r.id, r.status or "-", str(r.deliveries), str(r.citations), str(r.opportunity),
            r.last_delivered[:10] if r.last_delivered else "never", _guidance_approval_text(r),
            _guidance_flags_text(r),
        ))
    widths = [max(len(line[i]) for line in lines) for i in range(7)]
    for line in lines:
        print("  ".join(line[i].ljust(widths[i]) for i in range(7)) + "  " + line[7])
    notes = list(report.notes)
    for r in report.rows:
        notes.extend("%s: %s" % (r.id, n) for n in r.notes)
    if notes:
        print("notes:")
        for n in notes:
            print(n)
    _print_guidance_work(report)
    return 0


def _print_guidance_work(report):
    if not report.projects:
        print("work: no spawns in the window")
        return
    print("work (facets as registered now): %d spawns" % report.spawns)
    for p in report.projects:
        steps = ", ".join(
            "%s %d" % ("%s/%s" % (s["origin"], s["stage"]) if s["origin"] else s["stage"],
                       s["count"]) for s in p["steps"])
        print("%s  facets: %s  %d spawns: %s" % (
            p["project"] or "(no repo)", ",".join(p["facets"]) or "-", p["spawns"], steps))


def cmd_guidance_dir(argv):
    a = build_parser(COMMANDS["guidance-dir"]).parse_args(argv)
    return _project_dir(GUIDANCE_WORKSPACE, "guidance remote", a.check, "guidance")


def cmd_guidance_check(argv):
    a = build_parser(COMMANDS["guidance-check"]).parse_args(argv)
    c = container()
    try:
        failures, checked = CheckGuidanceUseCase(c.git, c.fs).execute(a.dir, a.mode, a.base)
    except UseCaseError as e:
        sys.stderr.write("lc guidance-check: %s\n" % e)
        return 1
    if failures:
        print("\n".join(failures))
        return 1
    if checked == 0:
        print("no guidance files changed between %s and HEAD (%s mode)" % (a.base, a.mode))
        return 0
    print("%d changed file(s) clean (%s mode)" % (checked, a.mode))
    return 0


def cmd_guidance_conventions(argv):
    build_parser(COMMANDS["guidance-conventions"]).parse_args(argv)
    sys.stdout.write(CONVENTIONS_TEXT)
    return 0


def cmd_audit_criteria(argv):
    a = build_parser(COMMANDS["audit-criteria"]).parse_args(argv)
    c = container()
    try:
        text = ShowAuditCriteriaUseCase(c.fs, c.config).execute(a.material)
    except UnknownMaterial as e:
        sys.stderr.write("lc audit-criteria: %s\n" % e)
        return 1
    print(text)
    return 0


def cmd_worklog(argv):
    a = build_parser(COMMANDS["worklog"]).parse_args(argv)
    import datetime as _dt

    now = _dt.datetime.now().astimezone()
    today, tz = now.date(), now.tzinfo
    args = [x for x in (a.start, a.end) if x is not None]
    resp = WorklogUseCase(container().store).execute(
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
    if resp.subject == "pending":
        print("== retro: pending  (%d reflections) ==" % resp.reflection_count)
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

    try:
        project_ref = resolve_project_ref(container().store, a.project)
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1

    inp = RetroInput(subject=a.id, since=a.since, last=a.last, project=project_ref,
                      pending=a.pending)
    resp = RetroUseCase(container().store, _flow()).execute(inp)
    _print_retro(resp)
    return 0
