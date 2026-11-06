import json
import sys
import time
from collections import namedtuple

from lightcycle.cli_commands import COMMANDS, build_parser
from lightcycle.render import (
    display_stage, render_backlog, render_inbox, render_queue, render_search,
)

from lightcycle.domain.work import (
    compose_step_title,
)
from lightcycle.application.work.resolve_project_ref import resolve_project_ref
from lightcycle.application.work import (
    ActiveStepsUseCase,
    BacklogInput,
    BacklogUseCase,
    InboxInput,
    InboxUseCase,
    PeekStepInput,
    PeekStepUseCase,
    QueueInput,
    QueueUseCase,
    SearchInput,
    SearchUseCase,
    ShowNodeInput,
    ShowNodeUseCase,
    StatusUseCase,
    TraceInput,
    TraceUseCase,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.pool import (
    PoolRunningUseCase,
)
from lightcycle.ports.store import NodeNotFoundError
from lightcycle.ports.workers import RegistryUnreadable


from lightcycle.commands.shared import drain_status as shared_drain_status
from lightcycle.commands.context import container, flow as _flow



def cmd_show(argv):
    a = build_parser(COMMANDS["show"]).parse_args(argv)
    resp = ShowNodeUseCase(container().store, _flow()).execute(ShowNodeInput(step=a.id))
    print(json.dumps(resp.as_dict(), indent=2))
    return 0


def cmd_peek(argv):
    a = build_parser(COMMANDS["peek"]).parse_args(argv)
    try:
        resp = PeekStepUseCase(
            container().store, _flow(), container().workflow_source
        ).execute(PeekStepInput(node_id=a.id, stage=a.stage))
    except KeyError:
        sys.stderr.write("unknown node '%s'\n" % a.id)
        return 1
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    print("# %s @ %s\n\n%s" % (a.stage, resp.pin, resp.body))
    return 0


def cmd_inbox(argv):
    a = build_parser(COMMANDS["inbox"]).parse_args(argv)
    flow_service = _flow()
    resp = InboxUseCase(container().store, flow_service).execute(InboxInput(n=a.n))
    for line in render_inbox(resp.rows, container().config.max_title_length(), flow_service):
        print(line)
    return 0


def cmd_backlog(argv):
    a = build_parser(COMMANDS["backlog"]).parse_args(argv)
    try:
        project_ref = resolve_project_ref(container().store, a.project)
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    resp = BacklogUseCase(container().store, _flow()).execute(
        BacklogInput(n=a.n, project=project_ref))
    for line in render_backlog(resp.rows, container().config.max_title_length()):
        print(line)
    return 0


def cmd_search(argv):
    a = build_parser(COMMANDS["search"]).parse_args(argv)
    try:
        resp = SearchUseCase(container().store).execute(SearchInput(text=a.text))
    except UseCaseError as e:
        print(e, file=sys.stderr)
        return 1
    for line in render_search(resp.matches, container().config.max_title_length()):
        print(line)
    return 0


def _step_title(t):
    try:
        item_title = container().store.get_node(t.item).title
    except NodeNotFoundError:
        item_title = None
    return compose_step_title(t.stage, item_title)


def cmd_active(argv):
    build_parser(COMMANDS["active"]).parse_args(argv)
    for t in ActiveStepsUseCase(container().store).execute().steps:
        print("  %s  %s" % (t.id, _step_title(t)))
    return 0


_QueueRow = namedtuple("_QueueRow", ("state", "id", "title"))


def cmd_queue(argv):
    a = build_parser(COMMANDS["queue"]).parse_args(argv)
    steps = QueueUseCase(container().store).execute(QueueInput(n=a.n)).steps
    rows = [_QueueRow(t.state, t.id, _step_title(t)) for t in steps]
    for line in render_queue(rows, container().config.max_title_length()):
        print(line)
    return 0


def cmd_status(argv):
    a = build_parser(COMMANDS["status"]).parse_args(argv)
    lanes = StatusUseCase(container().store).execute().lanes
    if a.json:
        print(json.dumps({k: [t.as_dict() for t in v] for k, v in lanes.items()}, indent=2))
    else:
        drain_status = shared_drain_status(time.time(), PoolRunningUseCase(container().lock).execute().running)
        if drain_status.draining:
            print("pool draining (%s)" % drain_status.waiting_text())
        flow_service = _flow()
        spin_ledger = container().spin.load()
        for key in ("inbox", "active", "queue"):
            print("== %s (%d) ==" % (key, len(lanes[key])))
            for t in lanes[key]:
                suffix = "  [blocked by %s]" % ", ".join(sorted(t.blocked_by)) if t.blocked_by else ""
                step_suffix = (
                    "  %s" % display_stage(flow_service.display_for(t), t.stage) if t.stage else ""
                )
                spin_entry = spin_ledger.entry(t.id)
                spin_suffix = (
                    "  [worker died %d times, no observed work]" % spin_entry.count
                    if spin_entry and spin_entry.count > 0 else ""
                )
                print(
                    "  %s  %s%s%s%s"
                    % (t.id, _step_title(t), suffix, step_suffix, spin_suffix)
                )
    return 0


def cmd_trace(argv):
    a = build_parser(COMMANDS["trace"]).parse_args(argv)
    try:
        resp = TraceUseCase(
            container().store, container().workers, container().fs, container().config
        ).execute(TraceInput(item=a.item))
    except (RegistryUnreadable, UseCaseError) as e:
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
            calls = "-" if t.api_calls is None else str(t.api_calls)
            print("  step %s  %s  [%s]  calls:%s%s" % (t.id, t.step or "-", t.state, calls, log))
            for art in t.artifacts:
                if art.type == "findings":
                    print("    artifact findings: see lc show %s" % t.id)
                else:
                    print("    artifact %s" % art.type)
    return 0
