import json
import sys
import time

from lightcycle.cli_commands import COMMANDS, build_parser

from lightcycle.application.pool.request_schedule_run import RequestScheduleRunUseCase
from lightcycle.application.inspect.list_schedules import (
    ListSchedulesInput,
    ListSchedulesUseCase,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.pool import (
    BackfillUsageUseCase,
    ListWorkersUseCase,
)
from lightcycle.ports.workers import RegistryUnreadable


from lightcycle.commands.context import container, flow as _flow



def cmd_ps(argv):
    a = build_parser(COMMANDS["ps"]).parse_args(argv)
    try:
        rows = ListWorkersUseCase(container().workers, container().store).execute().workers
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


def cmd_sweep(argv):
    build_parser(COMMANDS["sweep"]).parse_args(argv)
    result = container().sweep().execute(
        time.time(), container().config.max_boot_seconds(), container().config.stall_seconds()
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


def cmd_schedule(argv):
    parser = build_parser(COMMANDS["schedule"])
    a = parser.parse_args(argv)
    if a.sub is None:
        parser.print_help()
        return 2
    c = container()
    if a.sub == "run":
        try:
            RequestScheduleRunUseCase(c.store, c.config, _flow(), c.workflow_source).execute(a.id)
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
        print("schedule %s: the pool will fire it on its next tick" % a.id)
        return 0
    resp = ListSchedulesUseCase(
        c.store, c.config, _flow(), c.workflow_source, c.git,
    ).execute(ListSchedulesInput(now=time.time()))
    if a.json:
        print(json.dumps([r.as_dict() for r in resp.rows], indent=2))
        return 0
    for r in resp.rows:
        print("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" % (
            r.id, r.source, r.state, r.reason, r.cron or "-", r.guard or "-",
            r.last_fire, r.next_fire, r.guard_result, r.workflow or "-", r.name or "-"))
    return 0


def cmd_backfill_usage(argv):
    a = build_parser(COMMANDS["backfill-usage"]).parse_args(argv)
    try:
        resp = BackfillUsageUseCase(
            container().store, container().fs, container().workers, container().config,
            container().worker_log, container().claude_stream,
        ).execute(repair=a.repair)
    except RegistryUnreadable as e:
        sys.stderr.write("%s\n" % e)
        return 1
    ledger_total = len(container().store.usage_backfilled_logs())
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
