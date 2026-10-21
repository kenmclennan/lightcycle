import json
import sys
import time

from lightcycle.cli_commands import COMMANDS, build_parser

from lightcycle.domain.work import (
    DONE_FIELDS_BY_TYPE, refuse_fields, render_field_refusal,
)
from lightcycle.application.work.close_item import TeardownRefused
from lightcycle.application.work import (
    CloseItemInput,
    CloseItemUseCase,
    ReopenItemInput,
    ReopenItemUseCase,
)
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import (
    AdvanceInput,
    AdvanceStepUseCase,
    ClaimInput,
    ClaimStepUseCase,
    CompleteInput,
    CompleteStepUseCase,
)
from lightcycle.ports.workers import RegistryUnreadable


from lightcycle.commands.context import container, flow as _flow, worktrees as _worktrees
from lightcycle.commands.intake import _refuse_over_cap


def cmd_claim(argv):
    a = build_parser(COMMANDS["claim"]).parse_args(argv)
    try:
        resp = ClaimStepUseCase(
            container().store, _flow(), _worktrees(), container().workers, container().config,
            container().github_budget(_flow()),
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
    return 0 if container().spawner.spawn_worker(a.role) else 1


def cmd_advance(argv):
    a = build_parser(COMMANDS["advance"]).parse_args(argv)
    resp = AdvanceStepUseCase(container().store, _flow()).execute(
        AdvanceInput(step=a.id, outcome=a.outcome)
    )
    if resp.next_step:
        print(resp.next_step)
    return 0


def cmd_ready_roles(argv):
    build_parser(COMMANDS["ready-roles"]).parse_args(argv)
    print(" ".join(_ready_roles()))
    return 0


def _log_teardown_refusal(message):
    ts = time.strftime("%H:%M:%S", time.localtime(time.time()))
    container().worker_log.append_run_log("%s  %-7s  %s\n" % (ts, "refused", message))


def cmd_done(argv):
    a = build_parser(COMMANDS["done"]).parse_args(argv)
    note = " ".join(a.note) if a.note else None
    node_type = container().store.type_of(a.id)
    if node_type is None:
        sys.stderr.write("unknown node '%s'\n" % a.id)
        return 1
    given = set()
    if note:
        given.add("note")
    if a.disposition:
        given.add("disposition")
    refusal = refuse_fields(node_type, given, table=DONE_FIELDS_BY_TYPE)
    if refusal is not None:
        sys.stderr.write("%s\n" % render_field_refusal(refusal))
        return 2
    rc = _refuse_over_cap([("--note", note)])
    if rc is not None:
        return rc
    try:
        if node_type == "step":
            resp = CompleteStepUseCase(
                container().store, _flow(), _worktrees(), container().config).execute(
                CompleteInput(step=a.id, outcome=a.outcome, note=note)
            )
            if resp.next_step:
                print(resp.next_step)
            if resp.teardown_refusal:
                sys.stderr.write("%s\n" % resp.teardown_refusal)
                _log_teardown_refusal(resp.teardown_refusal)
        else:
            disposition = a.disposition
            if disposition is None:
                item = container().store.get_node(a.id)
                disposition = _flow().flow_for(item).disposition_for(a.outcome)
            if disposition is None:
                sys.stderr.write(
                    "outcome '%s' is not bundle-declared; pass --disposition "
                    "{completed,abandoned} explicitly\n" % a.outcome
                )
                return 2
            CloseItemUseCase(container().store, _worktrees()).execute(
                CloseItemInput(item=a.id, reason=a.outcome, disposition=disposition, note=note)
            )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        if isinstance(e, TeardownRefused):
            _log_teardown_refusal(str(e))
        return 1
    return 0


def cmd_close(argv):
    a = build_parser(COMMANDS["close"]).parse_args(argv)
    node_type = container().store.type_of(a.id)
    if node_type is None:
        sys.stderr.write("unknown node '%s'\n" % a.id)
        return 1
    if node_type == "step":
        sys.stderr.write(
            "lc close ends an item; a step is closed with `lc done <step> <outcome>`\n"
        )
        return 2
    note = " ".join(a.note) if a.note else None
    rc = _refuse_over_cap([("--note", note)])
    if rc is not None:
        return rc
    try:
        CloseItemUseCase(container().store, _worktrees()).execute(
            CloseItemInput(item=a.id, reason=a.outcome, disposition=a.disposition, note=note)
        )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        if isinstance(e, TeardownRefused):
            _log_teardown_refusal(str(e))
        return 1
    return 0


def cmd_reopen(argv):
    a = build_parser(COMMANDS["reopen"]).parse_args(argv)
    node_type = container().store.type_of(a.id)
    if node_type is None:
        sys.stderr.write("unknown node '%s'\n" % a.id)
        return 1
    try:
        ReopenItemUseCase(container().store).execute(ReopenItemInput(item=a.id))
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    return 0


def _ready_roles():
    return _flow().ready_roles()
