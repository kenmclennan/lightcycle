import sys

from lightcycle.cli_commands import COMMANDS, build_parser

from lightcycle.application.feedback import (
    ReflectInput,
    ReflectUseCase,
)
from lightcycle.domain.goals import goal_log_stamp
from lightcycle.domain.work import (
    ALLOWED_STATES_BY_FLAG, FIELDS_BY_TYPE, FieldRefusal, State,
    UNSETTABLE_FIELDS, UNSET_REFUSAL_REASONS, all_states, missing_for_state, refuse_fields, refuse_state, render_cap_refusal,
)
from lightcycle.domain.work.state import ALIASES
from lightcycle.application.goals import (
    AppendGoalLogUseCase,
    CreateGoalInput,
    CreateGoalUseCase,
    EditGoalInput,
    EditGoalUseCase,
    LinkGoalItemUseCase,
    ListGoalsUseCase,
    ShowGoalUseCase,
    UnlinkGoalItemUseCase,
)
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from lightcycle.application.work.resolve_backlog import link_resolves
from lightcycle.application.work.return_to_backlog import (
    ReturnToBacklogInput, ReturnToBacklogUseCase,
)
from lightcycle.application.work.resolve_project_ref import resolve_project_ref
from lightcycle.application.work.resolve_workflow_selection import (
    ResolveWorkflowSelectionInput,
    ResolveWorkflowSelectionUseCase,
)
from lightcycle.application.work import (
    CreateItemInput,
    CreateItemUseCase,
    CreateStepInput,
    CreateStepUseCase,
    EditNodeInput,
    EditNodeUseCase,
    LinkArtifactInput,
    LinkArtifactUseCase,
    RemoveNodeInput,
    RemoveNodeUseCase,
)
from lightcycle.application.errors import FieldRefusalError, UseCaseError
from lightcycle.application.flow import (
    BlockInput,
    BlockStepUseCase,
    UnblockInput,
)
from lightcycle.ports.workers import RegistryUnreadable


from lightcycle.commands.context import container, flow as _flow, worktrees as _worktrees



_NODE_TYPES = ("item", "step")


def cmd_new(argv):
    a = build_parser(COMMANDS["new"]).parse_args(argv)
    if a.type not in _NODE_TYPES:
        sys.stderr.write(
            "unknown type '%s'; expected item | step (item > step)\n" % a.type
        )
        return 2
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
        try:
            resp = CreateItemUseCase(container().store, container().config).execute(
                CreateItemInput(
                    title=a.title, description=a.description, project=a.project,
                    workflow=a.workflow, repo=a.repo, backlog=a.backlog,
                )
            )
        except FieldRefusalError as e:
            sys.stderr.write("%s\n" % render_field_refusal(e.refusal))
            return 1
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
        rc = _refuse_over_cap([("--note", " ".join(a.note) if a.note else None)])
        if rc is not None:
            return rc
        try:
            resp = CreateStepUseCase(container().store, _flow(), container().config).execute(
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


def _refuse_over_cap(fields):
    refusal = render_cap_refusal(fields)
    if not refusal:
        return None
    sys.stderr.write("%s\n" % refusal)
    return 2


def cmd_goal(argv):
    parser = build_parser(COMMANDS["goal"])
    a = parser.parse_args(argv)
    if a.sub is None:
        parser.print_help()
        return 2
    store = container().store
    try:
        if a.sub == "new":
            print(CreateGoalUseCase(store, container().fs, container().config).execute(CreateGoalInput(
                title=a.title,
                description=a.description,
                project=resolve_project_ref(store, a.project),
            )))
            return 0
        if a.sub == "list":
            for g in ListGoalsUseCase(store).execute(include_archived=a.all):
                print("%s\t%s\t%s" % (g.id, g.status, g.title))
            return 0
        if a.sub == "show":
            _print_goal(ShowGoalUseCase(store).execute(a.id))
            return 0
        if a.sub == "set":
            EditGoalUseCase(store).execute(EditGoalInput(
                id=a.id,
                title=a.title,
                description=a.description,
                project=resolve_project_ref(store, a.project),
                status=a.status,
            ))
            print("updated %s" % a.id)
            return 0
        if a.sub == "log":
            AppendGoalLogUseCase(store).execute(a.id, a.title, a.body)
            print("logged to %s" % a.id)
            return 0
        if a.sub == "link":
            LinkGoalItemUseCase(store).execute(a.id, a.item)
            print("linked %s to %s" % (a.item, a.id))
            return 0
        if a.sub == "unlink":
            UnlinkGoalItemUseCase(store).execute(a.id, a.item)
            print("unlinked %s from %s" % (a.item, a.id))
            return 0
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1


def _print_goal(view):
    g = view.goal
    print("%s  %s" % (g.id, g.title))
    print("project: %s" % (g.project or "(none)"))
    print("status: %s" % g.status)
    print("\ndescription:\n%s" % (g.description or "(none)"))
    print("\nitems:")
    for ref in view.items:
        print("  %s%s" % (ref.id, "  %s" % ref.title if ref.title else ""))
    print("\nlog:")
    for e in view.log:
        print("  %s%s" % (goal_log_stamp(e.created_at), "  %s" % e.title if e.title else ""))
        for line in e.body.splitlines():
            print("    %s" % line)


def _set_state_label(state):
    return "--state %s" % state if state is not None else "no --state"


def _reject_flags_ineffective_for_state(a):
    if a.state not in (None,) + tuple(all_states()):
        return None
    offending = [
        f for f in ALLOWED_STATES_BY_FLAG
        if getattr(a, f) is not None and a.state not in ALLOWED_STATES_BY_FLAG[f]
    ]
    if not offending:
        return None
    parts = [
        "--%s (needs %s)"
        % (f, " or ".join(_set_state_label(s) for s in ALLOWED_STATES_BY_FLAG[f]))
        for f in offending
    ]
    return "%s does not accept %s\n" % (_set_state_label(a.state), "; ".join(parts))


_UNSET_REFUSAL_SENTENCES = {
    "title-not-clearable": "a title must not be blank; there is nothing to clear, only to replace",
    "label-not-clearable": "there is no way to clear a label this way",
    "park-cleared-as-whole": "a park's fields are cleared as a whole, via --state ready",
    "backlog-not-a-value": "backlog is a list of ids to resolve, not a value to clear",
    "step-not-persisted": "step is a one-shot input to activation, not a persisted field",
}


def _unset_refusal_sentence(field, default):
    code = UNSET_REFUSAL_REASONS.get(field)
    return _UNSET_REFUSAL_SENTENCES[code] if code else default


def _reject_blank_values(a):
    for f in ("title", "description", "project", "workflow", "label", "notes", "tried"):
        if getattr(a, f, None) != "":
            continue
        if f in UNSETTABLE_FIELDS:
            return "--%s \"\" is refused; use --unset %s to clear it\n" % (f, f)
        return "--%s \"\" is refused; %s\n" % (
            f, _unset_refusal_sentence(f, "it may not be blank")
        )
    return None


def _reject_unset_contradiction(given_values, unset_fields):
    overlap = given_values & unset_fields
    if not overlap:
        return None
    named = ", ".join("--%s" % f for f in sorted(overlap))
    return "given a value and --unset in the same call: %s\n" % named


def _reject_unset_targets(unset_fields):
    bad = sorted(f for f in unset_fields if f not in UNSETTABLE_FIELDS)
    if not bad:
        return None
    parts = [
        "--unset %s: %s" % (f, _unset_refusal_sentence(f, "not a field lc set can clear"))
        for f in bad
    ]
    return "; ".join(parts) + "\n"


def _named(node_type):
    return "an item" if node_type == "item" else "a step"


def _render_refusal(refusal):
    if isinstance(refusal, FieldRefusal):
        return render_field_refusal(refusal)
    return _render_state_refusal(refusal)


def render_field_refusal(refusal):
    named = ", ".join("--%s" % f for f in refusal.fields)
    verb = "belong" if len(refusal.fields) > 1 else "belongs"
    if refusal.owner is None:
        return "%s %s to no structure" % (named, verb)
    return "%s %s to %s, not %s" % (
        named, verb, _named(refusal.owner), _named(refusal.requested_type),
    )


def _render_state_refusal(r):
    if r.owner is None:
        return (
            "unknown --state %r; use %s - to end a node instead, use `lc close <item>` "
            "or `lc done <step> <outcome>`; to reopen a closed item, use `lc reopen <item>`"
        ) % (r.state, ", ".join(r.allowed))
    takes = ", ".join("--state %s" % s for s in r.allowed)
    return "--state %s applies to %s, not %s; %s takes %s" % (
        r.state, _named(r.owner), _named(r.requested_type), _named(r.requested_type), takes,
    )


def cmd_set(argv):
    a = build_parser(COMMANDS["set"]).parse_args(argv)
    node_type = container().store.type_of(a.id)
    if node_type is None:
        sys.stderr.write("unknown node '%s'\n" % a.id)
        return 1
    settable = FIELDS_BY_TYPE["item"] | FIELDS_BY_TYPE["step"]
    given_values = {f for f in settable if getattr(a, f, None) is not None}
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
        if a.state == "active":
            depends_ids = a.depends or []
            for node_id in depends_ids:
                try:
                    node = container().store.get_node(node_id)
                except KeyError:
                    sys.stderr.write("unknown node '%s'\n" % node_id)
                    return 1
                if node.type != "item":
                    sys.stderr.write(
                        "'%s' is a step, not an item; --depends gates on an item's own "
                        "closure - pass the item id, not one of its steps\n" % node_id
                    )
                    return 1
            resp = ActivateItemUseCase(
                container().store, _flow(), container().git, container().config, container().scaffold
            ).execute(
                ActivateItemInput(
                    item=a.id, workflow=a.workflow, step=a.step, deps=depends_ids
                )
            )
            print(resp.step)
            return 0
        if a.state == State.BACKLOGGED.value:
            ReturnToBacklogUseCase(container().store).execute(ReturnToBacklogInput(item=a.id))
            return 0
        if a.state == State.WAITING.value:
            truthy_given = {f for f in given_values if getattr(a, f)}
            missing = missing_for_state(State.WAITING.value, truthy_given)
            if missing:
                field = missing[0]
                sys.stderr.write(
                    "--state waiting requires --%s (%s)\n"
                    % (field, _WAITING_FIELD_HINTS[field])
                )
                return 2
            rc = _refuse_over_cap(
                [("--needs", a.needs), ("--reason", a.reason), ("--tried", a.tried)]
            )
            if rc is not None:
                return rc
            BlockStepUseCase(container().store).execute(
                BlockInput(step=a.id, needs=a.needs, reason=a.reason, tried=a.tried)
            )
            return 0
        if a.state == ALIASES[State.WAITING]:
            container().unblock_step_use_case().execute(UnblockInput(step=a.id))
            return 0

    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    workflow_pin = "" if "workflow" in unset_fields else a.workflow
    resolved_pin = None
    if a.workflow:
        try:
            node = container().store.get_node(a.id)
        except KeyError:
            sys.stderr.write("unknown node '%s'\n" % a.id)
            return 1
        try:
            resp = ResolveWorkflowSelectionUseCase(_flow(), container().store).execute(
                ResolveWorkflowSelectionInput(
                    node_id=node.id, node_type=node.type, selector=a.workflow))
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
        workflow_pin = resp.value
        if resp.resolved:
            resolved_pin = resp.value
    effective_description = "" if "description" in unset_fields else a.description
    if a.project and "project" not in unset_fields:
        try:
            resolved_project = resolve_project_ref(container().store, a.project)
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
    else:
        resolved_project = a.project
    effective_project = "" if "project" in unset_fields else resolved_project
    effective_notes = "" if "notes" in unset_fields else a.notes
    try:
        tid = EditNodeUseCase(container().store, container().config).execute(
            EditNodeInput(step=a.id, title=a.title, description=effective_description,
                          project=effective_project, workflow=workflow_pin,
                          label=a.label, notes=effective_notes)
        ).id
    except FieldRefusalError as e:
        sys.stderr.write("%s\n" % render_field_refusal(e.refusal))
        return 1
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    if resolved_pin:
        print(resolved_pin)
    if a.backlog:
        try:
            link_resolves(container().store, tid, a.backlog)
        except UseCaseError as e:
            sys.stderr.write("%s\n" % e)
            return 1
    return 0


_WAITING_FIELD_HINTS = {
    "needs": "what the human must decide",
    "reason": "what happened that led to this",
}


_REFLECTION_TYPES = ("reflection", "feedback")


def cmd_attach(argv):
    a = build_parser(COMMANDS["attach"]).parse_args(argv)
    value = a.value
    if a.file:
        data = container().fs.read_bytes(a.file)
        if data is None:
            sys.stderr.write("no such file: %s\n" % a.file)
            return 1
        value = data.decode()
        if value == "":
            sys.stderr.write("file '%s' is empty; pass a file with content\n" % a.file)
            return 1
    if a.type in _REFLECTION_TYPES:
        ReflectUseCase(container().store, container().fs, _worktrees()).execute(
            ReflectInput(step=a.id, feedback=value)
        )
        return 0
    try:
        LinkArtifactUseCase(container().store, _flow()).execute(
            LinkArtifactInput(
                item=a.id, atype=a.type, value=value, label=a.label, replace=a.replace,
                internal=a.internal, kind=a.kind, step=_acting_step_id(),
            )
        )
    except UseCaseError as e:
        sys.stderr.write("%s\n" % e)
        return 1
    return 0


def _acting_step_id():
    spawnid = container().config.spawn_id()
    if not spawnid:
        return None
    try:
        return container().workers.step_for(spawnid)
    except RegistryUnreadable:
        return None


def cmd_dep(argv):
    a = build_parser(COMMANDS["dep"]).parse_args(argv)
    if a.remove:
        removed = container().store.dep_remove(a.id, a.remove)
        if removed:
            print("removed: %s no longer blocked by %s" % (a.id, a.remove))
        else:
            print("no-op: %s was not blocked by %s" % (a.id, a.remove))
        return 0
    target = None
    for node_id in (a.id, a.needs):
        try:
            node = container().store.get_node(node_id)
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
    container().store.dep_add(a.id, a.needs)
    return 0


def cmd_rm(argv):
    a = build_parser(COMMANDS["rm"]).parse_args(argv)
    try:
        resp = RemoveNodeUseCase(
            container().store, container().workers, _worktrees(), container().git
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
