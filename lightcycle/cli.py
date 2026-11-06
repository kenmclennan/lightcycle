import os
import signal
import sys
import time
import traceback
from dataclasses import replace

from lightcycle import __version__
from lightcycle.cli_commands import COMMANDS, build_parser
from lightcycle.adapters.upgrade import UpgradeAdapter
from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.adapters.log_parser import LogLineParser

from lightcycle.domain.work import worker_permitted
from lightcycle.render import worker_refusal_message
from lightcycle.application.pool import (
    AcquireRunLockUseCase,
    ClearDrainUseCase,
    DrainPoolUseCase,
    RecordTickTimingUseCase,
    ReleaseRunLockUseCase,
    StartPoolUseCase,
    ResolveLogInput,
    ResolveLogUseCase,
    StopPoolSignalUseCase,
    TickInput,
    UpgradeCadenceUseCase,
)
from lightcycle.application.setup import (
    ProcessListUnreadableError,
    RemoteVersionUnavailableError,
    UpgradeNoticeUseCase,
    BundleRangeError,
    VenvBusyError,
    upgrade,
)
from lightcycle.application.setup.upgrade import scan_venv_holders
from lightcycle.application.workflows.engine_requirement_check import installed_bundle_conflicts
from lightcycle.adapters.stop_signal import StopSignal
from lightcycle.adapters.sqlite_store import LiveStoreRefused, SchemaVersionRefused
from lightcycle.config import Config, ConfigError
from lightcycle.container import (
    Container,
)
from lightcycle.ports.store import NodeNotFoundError
from lightcycle.ports.upgrade import UpgradeInstallError
from lightcycle.ports.workers import RegistryUnreadable


from lightcycle.commands.inspect import cmd_show as cmd_show
from lightcycle.commands.inspect import cmd_peek as cmd_peek
from lightcycle.commands.inspect import cmd_inbox as cmd_inbox
from lightcycle.commands.inspect import cmd_backlog as cmd_backlog
from lightcycle.commands.inspect import cmd_search as cmd_search
from lightcycle.commands.inspect import cmd_active as cmd_active
from lightcycle.commands.inspect import cmd_queue as cmd_queue
from lightcycle.commands.inspect import cmd_status as cmd_status
from lightcycle.commands.inspect import cmd_trace as cmd_trace
from lightcycle.commands.intake import cmd_new as cmd_new
from lightcycle.commands.intake import cmd_set as cmd_set
from lightcycle.commands.intake import cmd_attach as cmd_attach
from lightcycle.commands.intake import cmd_dep as cmd_dep
from lightcycle.commands.intake import cmd_rm as cmd_rm
from lightcycle.commands.flow import cmd_claim as cmd_claim
from lightcycle.commands.flow import cmd_spawn as cmd_spawn
from lightcycle.commands.flow import cmd_advance as cmd_advance
from lightcycle.commands.flow import cmd_ready_roles as cmd_ready_roles
from lightcycle.commands.flow import cmd_done as cmd_done
from lightcycle.commands.flow import cmd_close as cmd_close
from lightcycle.commands.flow import cmd_reopen as cmd_reopen
from lightcycle.commands.pool import cmd_ps as cmd_ps
from lightcycle.commands.pool import cmd_sweep as cmd_sweep
from lightcycle.commands.pool import cmd_schedule as cmd_schedule
from lightcycle.commands.pool import cmd_backfill_usage as cmd_backfill_usage
from lightcycle.commands.feedback import cmd_specs_dir as cmd_specs_dir
from lightcycle.commands.feedback import cmd_guidance as cmd_guidance
from lightcycle.commands.feedback import cmd_guidance_dir as cmd_guidance_dir
from lightcycle.commands.feedback import cmd_guidance_check as cmd_guidance_check
from lightcycle.commands.feedback import cmd_guidance_conventions as cmd_guidance_conventions
from lightcycle.commands.feedback import cmd_review_yield as cmd_review_yield
from lightcycle.commands.feedback import cmd_audit_criteria as cmd_audit_criteria
from lightcycle.commands.feedback import cmd_worklog as cmd_worklog
from lightcycle.commands.feedback import cmd_retro as cmd_retro
from lightcycle.commands.setup import cmd_restore as cmd_restore
from lightcycle.commands.setup import cmd_doctor as cmd_doctor
from lightcycle.commands.setup import cmd_init as cmd_init
from lightcycle.commands.setup import cmd_project as cmd_project
from lightcycle.commands.setup import cmd_config as cmd_config
from lightcycle.commands.workflow import cmd_workflow as cmd_workflow
from lightcycle.commands.workflow import _workflow_simulate as _workflow_simulate


from lightcycle.commands import context
from lightcycle.commands.shared import drain_status as _drain_status
from lightcycle.commands.workflow import _repin_lines as _repin_lines
from lightcycle.commands.workflow import _workflow_check as _workflow_check
from lightcycle.commands.workflow import _workflow_check_dir as _workflow_check_dir
from lightcycle.commands.workflow import _workflow_check_pinned as _workflow_check_pinned

_container = None


def set_container(impl):
    global _container
    _container = impl
    context.set_container(impl)


def container():
    return _container


def _flow():
    return context.flow()


def _worktrees():
    return context.worktrees()


def require_store():
    return context.require_store()


COMMAND_GROUPS = [
    ("Setup", [
        ("init", "", "create the lightcycle store + seed the HOME config (run once)."),
        ("project", "<add|list|rm|scan> ...", "manage the project registry: add <owner/name> "
         "[--shortcode X] [--path P], list, rm <owner/name>, scan [dir] [--json] lists git repos "
         "under dir (default cwd) as registration candidates - read-only, registers nothing"),
        ("config", "[--edit]", "show every resolved config setting, or edit the config file"),
        ("version", "", "print the lightcycle version"),
        ("upgrade", "[--check]", "upgrade lc in place from main if it's ahead; --check only reports"),
        ("workflow", "<add|upgrade|set|list|rm|check|describe|simulate> ...", "manage workflow sources and "
         "inspect workflows: check <origin>/<name> validates composition, describe <origin>/<name> "
         "shows its summary/shape, simulate <origin>/<name> dry-runs the bundle through the real "
         "engine (no LLM/GitHub) to its terminals, --trace also prints the walk taken - separate from `lc upgrade`, which updates the engine"),
    ]),
    ("Start working", [
        ("start", "[--once] [--detach]", "the agent pool: each tick, sweep stale claims, then fill up to LC_MAX_AGENTS (see `lc config`) workers from the ready queue; --detach spawns it in the background and returns immediately"),
        ("stop", "", "signal a detached pool to stop (--drain lets running workers finish first); reports the pid signalled"),
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
        ("tui", "[--start]", "launch the interactive dashboard (priority list + pool/breaker status); --start first starts the pool in the background if it is not already running"),
    ]),
    ("Work primitives", [
        ("new", "<type> \"title\" [item: --description/--workflow/--repo | step: --parent/--step/--note]",
         "create an item or a step; each takes only its own fields"),
        ("set", "<id> [item: --title/--desc/--workflow/--state | step: --notes/--needs/--state]",
         "update an item or a step; refuses a field the other one owns"),
        ("rm", "<id> [--force]", "delete a node; refuses on a live worker, a dirty worktree or an unmerged branch "
         "- --force overrides the dirty worktree, the unmerged branch and stale claims"),
        ("attach", "<id> <type> <value> [--label] [--internal] [--kind K]", "attach an artifact"),
        ("dep", "<id> --needs <id> | --remove <id>", "add or remove a blocker on a node"),
        ("close", "<item> [--outcome \"<text>\"] [--disposition completed|abandoned] "
         "[--note \"<text>\"]",
         "end an item outright; --outcome is free-form (default \"closed\"), --disposition "
         "defaults to completed - refuses a step, use `done` for that"),
        ("reopen", "<item>", "undo a close: clears its outcome and close time so its state "
         "rolls up fresh from its children again - filing a step (or `lc set <item> --state "
         "active`) is a separate, second action to actually resume it; refuses a step "
         "(`--state ready` instead), a non-item node, or an item that isn't closed"),
    ]),
    ("Agent verbs (workers call these)", [
        ("claim", "<role>", "atomically claim the next ready step for a role"),
        ("done", "<id> <outcome> [--note \"<text>\"] [--disposition completed|abandoned]",
         "close a node; a step done-with-outcome advances the flow"),
    ]),
    ("Schedules", [
        ("schedule", "<list|run> ...", "list [--json] shows every schedule - config-enabled and "
         "bundle-suggested - as on, off or paused with the reason, its cadence, guard, last and "
         "next fire and the guard's current result; run <id> asks the pool to fire an enabled "
         "schedule on its next tick, skipping only the cron check; config is edited by hand"),
    ]),
    ("Feedback loop", [
        ("retro", "<item>", "gather child feedback + objective signals into a read digest"),
    ]),
    ("Maintenance", [
        ("sweep", "", "reclaim orphaned step claims and prune dead worker entries (kept: LC_WORKER_HISTORY, see `lc config`)"),
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
        ("guidance", "[--json]", "report each guidance entry's deliveries and citations and "
         "flag retirement candidates (read-only; counts cover steps still in the store)"),
        ("review-yield", "[--since YYYY-MM-DD] [--json]", "report each review stage's verdicts, "
         "findings, escapes after a pass and cost (read-only)"),
        ("guidance-dir", "[--check]", "print the resolved guidance repo directory (absolute "
         "path); --check validates it against the registered guidance remote"),
        ("guidance-check", "[--dir PATH] [--mode draft|final] [--base REF]", "check changed "
         "guidance entries against the engine's guidance conventions (read-only; exits 1 on "
         "any failure or an unreadable base)"),
        ("guidance-conventions", "", "print the engine's guidance conventions text exactly as "
         "`lc init` writes it (read-only)"),
        ("audit-criteria", "<material>", "print the periodic audit's criteria for one material "
         "(guidance, workflows) from the engine's audit prompt"),
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
    if _container is not None:
        port = _container.upgrade
        source = _container.workflow_source
    else:
        config = Config()
        port = UpgradeAdapter(config)
        source = WorkflowSourceAdapter(config, WorkflowBundleAdapter())
    try:
        resp = upgrade(
            __version__, check_only=a.check, fetch=port.fetch_remote_version,
            install=port.install_upgrade, installed=port.installed_version,
            holders=lambda: scan_venv_holders(port.list_processes),
            bundle_conflicts=lambda target: installed_bundle_conflicts(source, target),
            force=a.force,
        )
    except BundleRangeError as e:
        for message in e.conflicts:
            sys.stderr.write("%s\n" % message)
        sys.stderr.write(
            "run `lc workflow upgrade` first, or `lc upgrade --force` to install anyway\n")
        return 1
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
    except UpgradeInstallError as e:
        sys.stderr.write("lc upgrade failed: %s\n" % e)
        return 1
    if not resp.available:
        print("already at latest (%s)" % resp.current)
    elif a.check:
        print("upgrade available: %s -> %s" % (resp.current, resp.remote))
        for message in resp.conflicts:
            print("blocked: %s" % message)
    else:
        print("upgraded: %s -> %s" % (resp.current, resp.remote))
        for message in resp.conflicts:
            sys.stderr.write("warning: %s\n" % message)
    return 0


def _set_flags(args):
    ns, _extras = build_parser(COMMANDS["set"]).parse_known_args(args)
    return vars(ns)


def _attach_flags(args):
    ns, _extras = build_parser(COMMANDS["attach"]).parse_known_args(args)
    return vars(ns)


def _workflow_flags(args):
    try:
        ns, _extras = build_parser(COMMANDS["workflow"]).parse_known_args(args)
    except SystemExit:
        return {}
    return vars(ns)


def _config_flags(args):
    try:
        ns, _extras = build_parser(COMMANDS["config"]).parse_known_args(args)
    except SystemExit:
        return {}
    return vars(ns)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("version", "--version"):
        return cmd_version([])
    if argv and argv[0] == "upgrade":
        if Config().is_worker():
            sys.stderr.write(worker_refusal_message("upgrade"))
            return 1
        return cmd_upgrade(argv[1:])
    try:
        set_container(Container())
    except (LiveStoreRefused, SchemaVersionRefused) as e:
        sys.stderr.write("%s\n" % e)
        return 1
    _container.config.reconcile_config(_container.registered_seed_paths())
    if not argv or argv[0] in ("-h", "--help"):
        print_help()
        return 0
    cmd = argv[0]
    if cmd not in VERBS:
        sys.stderr.write("unknown subcommand: %s\n" % cmd)
        return 2
    if _container.config.is_worker() and _container.config.is_live_home():
        parsed_flags = {}
        if cmd == "set":
            parsed_flags = _set_flags(argv[1:])
        elif cmd == "attach":
            parsed_flags = _attach_flags(argv[1:])
        elif cmd == "workflow":
            parsed_flags = _workflow_flags(argv[1:])
        elif cmd == "config":
            parsed_flags = _config_flags(argv[1:])
        if not worker_permitted(cmd, parsed_flags):
            sys.stderr.write(worker_refusal_message(cmd))
            return 1
    fn = globals().get("cmd_" + cmd.replace("-", "_"))
    if fn is None:
        sys.stderr.write("not implemented: %s\n" % cmd)
        return 2
    try:
        return fn(argv[1:]) or 0
    except (NodeNotFoundError, ConfigError) as e:
        sys.stderr.write("%s\n" % e)
        return 1


def cmd_logs(argv):
    a = build_parser(COMMANDS["logs"]).parse_args(argv)
    try:
        path = (
            ResolveLogUseCase(_container.store, _container.workers, _container.fs, _container.config)
            .execute(ResolveLogInput(target=a.target))
            .path
        )
    except RegistryUnreadable as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if not path or not _container.fs.exists(path):
        sys.stderr.write("no log for %s\n" % a.target)
        return 1

    def emit(ll):
        if ll.text:
            print(ll.text, flush=True)

    if a.f:
        parser = LogLineParser()
        offset = 0
        try:
            while True:
                data, offset = _container.worker_log.read_from(path, offset)
                if not data:
                    time.sleep(0.3)
                    continue
                for ll in parser.feed(data):
                    emit(ll)
        except KeyboardInterrupt:
            pass
    else:
        data, _ = _container.worker_log.read_from(path, 0)
        if data and not data.endswith(b"\n"):
            data += b"\n"
        for ll in LogLineParser().feed(data):
            emit(ll)
    return 0


def cmd_tui(argv):
    a = build_parser(COMMANDS["tui"]).parse_args(argv)
    if a.start:
        if not require_store():
            return 1
        resp = StartPoolUseCase(_container.lock, _container.spawner).execute()
        if resp.started:
            print("lc start detached, pid %d - `lc stop` ends it" % resp.pid)
        else:
            print("pool already running, pid %d" % resp.pid)
    from lightcycle.adapters.tui.app import run
    run(_container)
    return 0


def _tick_event_lines(result, ts):
    lines = []
    for role in result.spawned:
        lines.append("%s  %-7s  %s" % (ts, "spawn", role))
    for sid in result.monitor.merged:
        lines.append("%s  %-7s  %s" % (ts, "merge", sid))
    for sid in result.monitor.abandoned:
        lines.append("%s  %-7s  %s" % (ts, "abandon", sid))
    for sid in result.monitor.reworked:
        lines.append("%s  %-7s  %s" % (ts, "rework", sid))
    for sid in result.monitor.conflicted:
        lines.append("%s  %-7s  %s" % (ts, "conflict", sid))
    for sid in result.monitor.head_moved:
        lines.append("%s  %-7s  %s" % (ts, "head-moved", sid))
    for sid in result.monitor.ci_resolved:
        lines.append("%s  %-7s  %s" % (ts, "ci-resolved", sid))
    for unread in result.monitor.ci_unread:
        detail = ": %s" % unread.detail if unread.detail else ""
        lines.append("%s  %-7s  %s" % (ts, "ci-unread", "%s %s%s" % (unread.step, unread.reason, detail)))
    for bid in result.sweep.swept:
        lines.append("%s  %-7s  %s" % (ts, "sweep", bid))
    for bid in result.sweep.preserved:
        lines.append("%s  %-7s  %s" % (ts, "preserve", bid))
    for bid in result.sweep.capture_failed:
        lines.append("%s  %-7s  %s" % (ts, "preserve-fail", bid))
    for bid in result.sweep.parked:
        lines.append("%s  %-7s  %s" % (ts, "park", bid))
    for spawnid in result.sweep.killed:
        lines.append("%s  %-7s  %s" % (ts, "kill", spawnid))
    if result.stranded is not None:
        for sid in result.stranded.closed:
            lines.append("%s  %-7s  %s" % (ts, "recover", sid))
        for sid, findings in result.stranded.refused:
            lines.append("%s  %-7s  %s: %s" % (ts, "refused", sid, findings))
    if result.config is not None and result.config.outcome == "reloaded":
        text = "config reloaded"
        if result.config.restart_required:
            text += " - restart needed for: %s" % ", ".join(result.config.restart_required)
        lines.append("%s  %s" % (ts, text))
    if result.schedules is not None:
        for sid in result.schedules.fired:
            lines.append("%s  %-7s  %s" % (ts, "schedule", sid))
    for step, tid, detail in result.hooks.completed:
        msg = "%s: %s" % (tid, detail) if detail else tid
        lines.append("%s  %-7s  %s" % (ts, step, msg))
    if result.backup.created:
        msg = result.backup.created
        if result.backup.pruned:
            msg += " pruned=%d" % len(result.backup.pruned)
        lines.append("%s  %-7s  %s" % (ts, "backup", msg))
    if result.breaker.opened:
        reset_ts = time.strftime("%H:%M:%S", time.localtime(result.breaker.reset_at))
        lines.append("%s  %-7s  %s" % (ts, "breaker", "opened until %s" % reset_ts))
    if result.breaker.closed:
        lines.append("%s  %-7s  %s" % (ts, "breaker", "closed"))
    if result.breaker.rearmed:
        reset_ts = time.strftime("%H:%M:%S", time.localtime(result.breaker.reset_at))
        lines.append("%s  %-7s  %s" % (ts, "breaker", "probe stalled, retrying after %s" % reset_ts))
    if result.breaker.spin_opened:
        lines.append(
            "%s  %-7s  %s" % (ts, "spin", "opened - workers died with no observed work")
        )
    if result.github is not None and result.github.opened:
        reading = result.github.reading
        reset_ts = time.strftime("%H:%M:%S", time.localtime(reading.reset))
        lines.append("%s  %-7s  %s" % (
            ts, "github", "budget low, %d remaining, resets at %s" % (reading.remaining, reset_ts)))
    if result.github is not None and result.github.closed:
        lines.append("%s  %-7s  %s" % (ts, "github", "budget recovered"))
    return lines


def _state_line(result, ts, reason=None):
    state = "active=%d/%d ready=%d inflight=%d" % (
        result.pool.alive, result.pool.max_agents, result.pool.ready, result.pool.inflight_count)
    if result.sweep.pruned:
        state += " pruned=%d" % result.sweep.pruned
    if reason:
        state += " reason=%s" % reason
    return "%s  %-7s  %s" % (ts, "state", state)


def _idle_reason(result):
    if not result.pool.ready:
        return None
    if result.breaker.open:
        return "breaker-open"
    if result.breaker.spin_open:
        return "spin-open"
    if result.spawned:
        return None
    if result.pool.draining:
        return "draining"
    if result.pool.free_slots <= 0:
        return "no-free-slots"
    return "ready-role-already-inflight"


def _format_tick(result, prev_snapshot, now):
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    lines = _tick_event_lines(result, ts)
    cur = (result.pool.alive, result.pool.max_agents, result.pool.ready, result.pool.inflight_count)
    if cur != prev_snapshot or result.sweep.pruned:
        lines.append(_state_line(result, ts))
    return lines, cur


def _tick_duration_lines(duration, interval):
    if duration > interval:
        return ["tick overran: took %.1fs against poll-seconds %s" % (duration, interval)]
    return []


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


def _advance_tick_state(prev_now, consecutive_failures, now, succeeded, cap):
    if succeeded:
        return now, 0, "continue"
    consecutive_failures += 1
    return prev_now, consecutive_failures, _tick_failure_action(consecutive_failures, cap)


def _upgrade_notice_lines(resp):
    if resp.notice:
        return [resp.notice]
    if resp.error:
        return ["could not check for updates: %s" % resp.error]
    return []


def _stop_pool_lines(resp, grace_seconds):
    lines = ["lc start stopped: %d worker(s) stopped, %d step(s) reclaimed"
             % (len(resp.stopped), len(resp.reclaimed))]
    if resp.survivors:
        lines.append(
            "  WARNING: %d worker(s) ignored SIGTERM and were still alive after the %ds grace: %s"
            " - kill them by hand"
            % (len(resp.survivors), grace_seconds,
               ", ".join("%s (pid %d)" % (w.spawnid, w.pid) for w in resp.survivors))
        )
    scripts = len(set(resp.scripts_terminated) | set(resp.scripts_killed))
    if scripts:
        lines.append("  stopped %d running script(s); their steps re-run on the next pool" % scripts)
    if resp.preserved:
        lines.append("  preserved uncommitted work on: %s" % ", ".join(resp.preserved))
    if resp.capture_failed:
        lines.append(
            "  COULD NOT read the worktree to preserve work on: %s - check it by hand"
            % ", ".join(resp.capture_failed)
        )
    return lines


def _stop_pool():
    grace_seconds = _container.config.shutdown_grace_seconds()
    resp = _container.stop_pool(flow=_flow()).execute(
        time.time(), _container.config.max_boot_seconds(),
        _container.config.stall_seconds(),
        shutdown_grace_seconds=grace_seconds,
    )
    return _stop_pool_lines(resp, grace_seconds)


def _drain_complete(result, status):
    return result.pool.draining and result.pool.alive == 0 and status.engine_steps == 0


def _drain_progress_lines(status, last_waiting):
    waiting = status.waiting_text()
    if waiting == last_waiting:
        return [], last_waiting
    return ["lc start draining - waiting for %s" % waiting], waiting


def _shutdown_pool_lines():
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    lines = []
    try:
        lines.extend(_stop_pool())
    except Exception as e:
        sys.stderr.write("shutdown could not finish cleanly: %s\n" % e)
    return lines


def _stop_pool_and_report(lead=""):
    print(lead + "lc start stopping - press Ctrl-C again only if it hangs")
    for line in _shutdown_pool_lines():
        print(line)
    return 0


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
        print("lc start detached, pid %d - output goes to %s - `lc stop` ends it"
              % (resp.pid, os.path.join(_container.config.data_root(), "logs", "run.log")))
        return 0
    lock_result = AcquireRunLockUseCase(_container.lock).execute()
    if not lock_result.acquired:
        sys.stderr.write("lc start already running, pid %d\n" % lock_result.holder_pid)
        return 1
    _container.gh_shim.install()
    ClearDrainUseCase(_container.drain).execute()

    stop = StopSignal()
    stop.install()
    try:
        tick = _container.tick(flow=_flow())
        if a.once:
            now = time.time()
            started = time.monotonic()
            tick.prime(now)
            result = _run_tick(tick, _container.worker_log, TickInput(now=now), now)
            lines, _ = _format_tick(result, None, now)
            lines.append("tick took %.1fs" % (time.monotonic() - started))
            for line in lines:
                print(line)
            return 0
        interval = _container.config.poll_seconds()
        max_agents = _container.config.max_agents()
        _container.config.tick_lag_window_seconds()
        _container.config.tick_lag_share()
        _container.config.tick_stall_seconds()
        record = RecordTickTimingUseCase(_container.tick_timing_status, _container.config)
        record.started(os.getpid(), time.time())
        upgrade_cadence = UpgradeCadenceUseCase(
            UpgradeNoticeUseCase(__version__, port=_container.upgrade),
            _container.config.pool_upgrade_check_seconds(),
        )
        for line in _upgrade_notice_lines(upgrade_cadence.execute(time.time())):
            print(line)
        print("lc start  poll=%ds  max-agents=%d" % (interval, max_agents))
        prev_snapshot = None
        prev_now = time.time()
        consecutive_failures = 0
        tick_failure_cap = _container.config.tick_failure_cap()
        last_waiting = None
        while not stop.requested:
            now = time.time()
            tick_started = time.monotonic()
            for line in _upgrade_notice_lines(upgrade_cadence.execute(now)):
                print(line)
            drain = _drain_status(now).draining
            try:
                result = _run_tick(
                    tick, _container.worker_log, TickInput(now=now, since=prev_now, drain=drain), now
                )
            except Exception:
                record.finished(os.getpid(), time.time(), time.monotonic() - tick_started)
                prev_now, consecutive_failures, action = _advance_tick_state(
                    prev_now, consecutive_failures, now, False, tick_failure_cap)
                if action == "raise":
                    raise
                stop.pause(interval)
                continue
            duration = time.monotonic() - tick_started
            record.finished(os.getpid(), time.time(), duration)
            prev_now, consecutive_failures, _ = _advance_tick_state(
                prev_now, consecutive_failures, now, True, tick_failure_cap)
            lines, prev_snapshot = _format_tick(result, prev_snapshot, now)
            lines += _tick_duration_lines(duration, interval)
            for line in lines:
                print(line)
            if result.pool.draining:
                status = replace(_drain_status(time.time()), running=result.pool.alive)
                progress, last_waiting = _drain_progress_lines(status, last_waiting)
                for line in progress:
                    print(line)
                if _drain_complete(result, status):
                    print("lc start drained - no workers or engine steps running, stopping")
                    for line in _shutdown_pool_lines():
                        print(line)
                    return 0
            stop.pause(interval)
        return _stop_pool_and_report()
    except KeyboardInterrupt:
        return _stop_pool_and_report("\n")
    finally:
        stop.restore()
        ClearDrainUseCase(_container.drain).execute()
        ReleaseRunLockUseCase(_container.lock).execute()


def cmd_stop(argv):
    a = build_parser(COMMANDS["stop"]).parse_args(argv)
    if a.drain:
        drained = DrainPoolUseCase(_container.lock, _container.drain).execute()
        if drained.outcome == "no-pool":
            sys.stderr.write("no pool running\n")
            return 1
        if drained.outcome == "already-draining":
            print("pool already draining")
            return 0
        print("lc stop --drain asked pid %d to drain - it exits when its running workers and engine steps finish"
              % drained.pid)
        return 0
    resp = StopPoolSignalUseCase(_container.lock, _container.workers).execute()
    if not resp.signalled:
        sys.stderr.write("no pool running\n")
        return 1
    print("lc stop signalled pid %d - the pool finishes its current tick, then exits" % resp.pid)
    return 0

