import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.planned_steps import PlannedStepsInput, PlannedStepsUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

scenarios("planned-steps.feature")


@pytest.fixture
def ctx():
    return {}


def _graph(ctx):
    return ctx.setdefault("graph", {"entry": None, "nodes": {}, "edges": {}, "hooks": []})


def _metas(ctx):
    return ctx.setdefault("metas", {})


def _store(ctx):
    return ctx.setdefault("store", FakeStore())


def _item(ctx):
    if "item" not in ctx:
        ctx["item"] = _store(ctx).create_item("it", "a description")
    return ctx["item"]


def _add_stage(ctx, stage, file, agent=True):
    g = _graph(ctx)
    g["nodes"][stage] = file
    _metas(ctx)[file] = {"model": "sonnet"} if agent else {}
    if g["entry"] is None:
        g["entry"] = stage


def _add_edge(ctx, frm, outcome, to=None):
    _graph(ctx)["edges"].setdefault(frm, {})[outcome] = to


def _add_hook(ctx, *parts):
    _graph(ctx)["hooks"].append(parts)


def _render_graph_text(ctx):
    g = _graph(ctx)
    lines = []
    if g["entry"]:
        lines.append("entry: %s" % g["entry"])
    if g["nodes"]:
        lines.append("")
        lines.append("nodes:")
        for stage, file in g["nodes"].items():
            lines.append("  %s  %s" % (stage, file))
    if g["edges"]:
        lines.append("")
        lines.append("edges:")
        for frm, outs in g["edges"].items():
            for outcome, to in outs.items():
                lines.append("  %s  %s%s" % (frm, outcome, ("  " + to) if to else ""))
    if g["hooks"]:
        lines.append("")
        lines.append("hooks:")
        for hook in g["hooks"]:
            lines.append("  " + "  ".join(str(part) for part in hook))
    return "\n".join(lines) + "\n"


def _flow_service(ctx):
    return FlowService(FakeFs(_metas(ctx), workflow=_render_graph_text(ctx)), _store(ctx))


def _file_step(ctx, spec, stage):
    item = _item(ctx)
    _store(ctx).create_step("%s: %s" % (stage, spec), step=stage, parent=item)


@given("a flow where the coder builds, the reviewer reviews, and the auditor audits")
def _chain_flow(ctx):
    _add_stage(ctx, "build", "coder")
    _add_stage(ctx, "review", "reviewer")
    _add_stage(ctx, "audit", "auditor")
    _add_edge(ctx, "build", "done", "review")
    _add_edge(ctx, "review", "done", "audit")
    _add_edge(ctx, "audit", "clean")


@given("a flow where the coder builds and the reviewer reviews")
def _two_step_flow(ctx):
    _add_stage(ctx, "build", "coder")
    _add_stage(ctx, "review", "reviewer")
    _add_edge(ctx, "build", "done", "review")
    _add_edge(ctx, "review", "done")


@given(parsers.parse(
    'a flow where "{stage}" merges the item on outcome "{merge_outcome}", '
    'and its "{o1}" and "{o2}" outcomes loop back to earlier steps'
))
def _merge_gated_flow(ctx, stage, merge_outcome, o1, o2):
    _add_stage(ctx, stage, "human", agent=False)
    _add_stage(ctx, "cleanup", "human", agent=False)
    _add_stage(ctx, "earlier", "human", agent=False)
    _add_edge(ctx, stage, merge_outcome, "cleanup")
    _add_edge(ctx, stage, o1, "earlier")
    _add_edge(ctx, stage, o2, "earlier")
    _add_hook(ctx, "pr_merge", stage, merge_outcome)
    ctx["loop_target"] = "earlier"


@given(parsers.parse(
    'a flow where "{stage}" advances to "{done_target}" on outcome "{done_outcome}", '
    'and retries up to {n:d} times before escalating on outcome "{cap_outcome}"'
))
def _ci_cap_flow(ctx, stage, done_target, done_outcome, n, cap_outcome):
    _add_stage(ctx, stage, "watcher")
    _add_stage(ctx, done_target, "human", agent=False)
    _add_stage(ctx, "escalate-step", "human", agent=False)
    _add_edge(ctx, stage, done_outcome, done_target)
    _add_edge(ctx, stage, cap_outcome, stage)
    _add_hook(ctx, "ci_failed_cap", stage, cap_outcome, n, "escalate-step")
    ctx["escalation_step"] = "escalate-step"


@given(parsers.parse(
    'a flow where the reviewer\'s "{outcome}" outcome on step "{stage}" '
    'closes the item with no further step'
))
def _terminal_flow(ctx, outcome, stage):
    _add_stage(ctx, stage, "reviewer")
    _add_edge(ctx, stage, outcome)


@given(parsers.parse(
    'a flow where "{stage}" can complete as "{o1}" or "{o2}", with neither outcome backed by '
    'a merge or retry hook, and "{o1}" leads to "{done_target}"'
))
def _undeterminable_flow(ctx, stage, o1, o2, done_target):
    _add_stage(ctx, stage, "opener")
    _add_stage(ctx, done_target, "watcher")
    _add_edge(ctx, stage, o1, done_target)
    _add_edge(ctx, stage, o2, None)


@given(parsers.parse('the item "{spec}" is filed at step "{stage}"'))
def _filed_at(ctx, spec, stage):
    _file_step(ctx, spec, stage)


@given(parsers.parse(
    'the item "{spec}" is filed at step "{stage}", where "{stage}" leads to "{target}"'
))
def _filed_with_lead_in(ctx, spec, stage, target):
    _add_stage(ctx, stage, "coder")
    _add_edge(ctx, stage, "done", target)
    _file_step(ctx, spec, stage)


@given(parsers.parse(
    'the item "{spec}" completed step "{done_step}" and is now filed at step "{stage}"'
))
def _completed_then_filed(ctx, spec, done_step, stage):
    item = _item(ctx)
    done_id = _store(ctx).create_step("%s: %s" % (done_step, spec), step=done_step, parent=item)
    _store(ctx).close(done_id, "done")
    _file_step(ctx, spec, stage)


@given(parsers.parse('the item "{spec}" has not been filed at any step yet'))
def _not_yet_filed(ctx, spec):
    _item(ctx)


@given(parsers.parse('the item "{spec}" has completed its last step on a terminal outcome'))
def _completed_terminal(ctx, spec):
    item = _item(ctx)
    sid = _store(ctx).create_step("last: %s" % spec, step="last", parent=item)
    _store(ctx).close(sid, "done")


@when("the item's planned steps are read")
def _read(ctx):
    ctx["children_before"] = len(_store(ctx).children(_item(ctx)))
    ctx["result"] = PlannedStepsUseCase(_store(ctx), _flow_service(ctx)).execute(
        PlannedStepsInput(item_id=_item(ctx))
    )


@then(parsers.re(
    r'the planned steps are "(?P<step1>[^"]+)" for the (?P<role1>[a-z-]+), '
    r'then "(?P<step2>[^"]+)" for the (?P<role2>[a-z-]+)'
))
def _then_two_steps(ctx, step1, role1, step2, role2):
    result = ctx["result"]
    assert [p.step for p in result] == [step1, step2]
    assert [p.role for p in result] == [role1, role2]


@then(parsers.re(
    r'the planned steps are "(?P<step>[^"]+)" for the (?P<role>[a-z-]+)'
))
def _then_one_step(ctx, step, role):
    result = ctx["result"]
    assert [p.step for p in result] == [step]
    assert [p.role for p in result] == [role]


@then(parsers.parse('the planned steps are "{step}" for its owner, and nothing beyond it'))
def _then_one_step_owner(ctx, step):
    result = ctx["result"]
    assert [p.step for p in result] == [step]


@then("the planned steps are empty")
def _then_empty(ctx):
    assert ctx["result"] == []


@then(parsers.parse('neither "{o1}" nor "{o2}" leads to a planned step'))
def _then_neither_leads(ctx, o1, o2):
    steps = [p.step for p in ctx["result"]]
    assert ctx["loop_target"] not in steps


@then("the escalation step is not among the planned steps")
def _then_no_escalation(ctx):
    steps = [p.step for p in ctx["result"]]
    assert ctx["escalation_step"] not in steps


@then("reading the planned steps does not raise an error")
def _then_no_error(ctx):
    assert ctx["result"] is not None


@then(parsers.parse(
    "its id is the item's id with position {position:d}, "
    "following the {filed:d} steps already filed"
))
def _then_id_position(ctx, position, filed):
    item = _item(ctx)
    assert len(_store(ctx).children(item)) == filed
    assert ctx["result"][0].id == "%s.%d" % (item, position)


@then(parsers.parse(
    'none of the planned step ids match the id of the "{step_a}" step '
    'or the id of the "{step_b}" step'
))
def _then_no_id_collision(ctx, step_a, step_b):
    item = _item(ctx)
    filed_ids = {
        c.id for c in _store(ctx).children(item) if c.step in (step_a, step_b)
    }
    projected_ids = {p.id for p in ctx["result"]}
    assert not (filed_ids & projected_ids)


@then("no new step has been filed for the item")
def _then_no_new_step(ctx):
    assert len(_store(ctx).children(_item(ctx))) == ctx["children_before"]
