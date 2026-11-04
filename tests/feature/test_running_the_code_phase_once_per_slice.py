import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from lightcycle.application.pool.release_stacked_items import ReleaseStackedItemsUseCase
from tests.support.harness import DEFAULT_WORKFLOW, Harness

scenarios("running-the-code-phase-once-per-slice.feature")

_GRAPH = (
    "entry: plan\n\n"
    "nodes:\n"
    "  plan     planner\n"
    "  write    coder\n"
    "  gate     gate\n"
    "  cleanup  cleaner\n\n"
    "phase:\n"
    "  plan     spec\n"
    "  write    code\n"
    "  gate     code\n"
    "  cleanup  code\n\n"
    "slices: code from slices\n\n"
    "edges:\n"
    "  plan     done     write\n"
    "  write    done     gate\n"
    "  gate     merged   cleanup\n"
    "  gate     changes  write\n"
    "  cleanup  done\n\n"
    "hooks:\n"
    "  pr_merge  gate  merged\n"
)

_STEPS = {
    "planner": "---\nmodel: sonnet\n---\n# planner\nstub\n",
    "coder": "---\nmodel: sonnet\n---\n# coder\nstub\n",
    "gate": "# gate\nstub\n",
    "cleaner": "---\nmodel: sonnet\n---\n# cleaner\nstub\n",
}


@pytest.fixture
def ctx():
    return {}


@pytest.fixture(autouse=True)
def _isolate():
    orig = cli.container()
    yield
    cli.set_container(orig)


def _store(ctx):
    return ctx["h"].store


def _open_steps(ctx, stage=None, slice=None):
    return [
        s for s in _store(ctx).children(ctx["item"])
        if s.state != "done" and (stage is None or s.stage == stage)
        and (slice is None or s.slice == slice)
    ]


def _runs(ctx):
    return [r for r in _store(ctx).runs_of(ctx["item"]) if r.phase == "code"]


def _run_of_slice(ctx, n):
    return next(r for r in _runs(ctx) if r.slice == n and r.is_open)


def _show(ctx, node_id):
    rc, out, err = ctx["h"].run("show", node_id)
    assert rc == 0, err
    return json.loads(out)


def _tick(ctx):
    ReleaseStackedItemsUseCase(_store(ctx), cli.container().flow_service()).execute()


@given("a workflow whose code phase is sliced")
def _workflow(ctx):
    ctx["h"] = Harness([], workflow_text=_GRAPH, extra_steps=dict(_STEPS))


def _file_item(ctx):
    store = _store(ctx)
    ctx["item"] = store.create_item("feature story", "a description", workflow=DEFAULT_WORKFLOW)


@given(parsers.parse('an item with the single slice "{one}"'))
def _item_one(ctx, one):
    _file_item(ctx)
    ctx["h"].run("attach", ctx["item"], "slices", one)


@given(parsers.parse('an item with the slices "{a}", "{b}" and "{c}"'))
def _item_three(ctx, a, b, c):
    _file_item(ctx)
    rc, _out, err = ctx["h"].run("attach", ctx["item"], "slices", "\n".join([a, b, c]))
    assert rc == 0, err


@given("an item with no slices artifact")
def _item_none(ctx):
    _file_item(ctx)


def _enter(ctx):
    rc, _out, err = ctx["h"].run("set", ctx["item"], "--state", "active", "--step", "plan")
    assert rc == 0, err
    (plan,) = _open_steps(ctx, "plan")
    rc, _out, err = ctx["h"].run("done", plan.id, "done")
    assert rc == 0, err


@given("the item has entered the code phase")
@when("the item enters the code phase")
def _entered(ctx):
    _enter(ctx)


@given("every slice has reached its merge gate")
def _all_gates(ctx):
    for n in (1, 2, 3):
        run = _run_of_slice(ctx, n)
        _store(ctx).set_branch(run.id, "feat/slice-%d" % n)
        _store(ctx).set_pr(run.id, "https://github.com/o/r/pull/%d" % n)
    _tick(ctx)
    for n in (1, 2, 3):
        (write,) = _open_steps(ctx, "write", n)
        rc, _out, err = ctx["h"].run("done", write.id, "done")
        assert rc == 0, err


@when(parsers.parse("slice {n:d}'s run gets a PR and a tick runs"))
def _pr_and_tick(ctx, n):
    run = _run_of_slice(ctx, n)
    _store(ctx).set_branch(run.id, "feat/slice-%d" % n)
    _store(ctx).set_pr(run.id, "https://github.com/o/r/pull/%d" % n)
    _tick(ctx)


@when(parsers.parse("slice {n:d}'s run gets a branch and a tick runs"))
def _branch_and_tick(ctx, n):
    _store(ctx).set_branch(_run_of_slice(ctx, n).id, "feat/slice-%d" % n)
    _tick(ctx)


@when(parsers.parse("the slices merge in order {a:d}, {b:d} and {c:d}"))
def _merge_in_order(ctx, a, b, c):
    ctx["closed_after"] = []
    ctx["cleanup_runs"] = []
    for n in (a, b, c):
        (gate,) = _open_steps(ctx, "gate", n)
        rc, _out, err = ctx["h"].run("done", gate.id, "merged")
        assert rc == 0, err
        ctx["closed_after"].append(_store(ctx).get_item(ctx["item"]).state == "done")
        if n != c:
            ctx["cleanup_runs"].append(len(_open_steps(ctx, "cleanup")))
    cleanups = [s for s in _store(ctx).children(ctx["item"]) if s.stage == "cleanup"]
    ctx["cleanups"] = cleanups
    for cleanup in cleanups:
        if cleanup.state != "done":
            rc, _out, err = ctx["h"].run("done", cleanup.id, "done")
            assert rc == 0, err
    ctx["closed_after"].append(_store(ctx).get_item(ctx["item"]).state == "done")


@when("I list the inbox")
def _inbox(ctx):
    rc, out, err = ctx["h"].run("inbox")
    assert rc == 0, err
    ctx["inbox"] = out.splitlines()


@when(parsers.parse("the second slice's gate asks for changes"))
def _changes(ctx):
    (gate,) = _open_steps(ctx, "gate", 2)
    rc, _out, err = ctx["h"].run("done", gate.id, "changes")
    assert rc == 0, err


@when(parsers.parse('I attach the slices "{value}" to the item'))
def _attach_bad(ctx, value):
    ctx["rc"], _out, ctx["err"] = ctx["h"].run("attach", ctx["item"], "slices", value)


@then("the item has three open slice runs in slice order")
def _three_runs(ctx):
    runs = sorted(_runs(ctx), key=lambda r: r.slice)
    assert [(r.slice, r.slice_name, r.base_slice, r.is_open) for r in runs] == [
        (1, "a", None, True), (2, "b", 1, True), (3, "c", 2, True)]
    assert runs[1].id.endswith(".code.s2")


@then("the first slice's write step is claimable")
def _first_claimable(ctx):
    (write,) = _open_steps(ctx, "write", 1)
    assert write.id in [s.id for s in _store(ctx).ready_steps()]


@then("the second and third slices' write steps are blocked on the item")
def _blocked(ctx):
    for n in (2, 3):
        (write,) = _open_steps(ctx, "write", n)
        assert write.blocked_by == [ctx["item"]]
        assert write.id not in [s.id for s in _store(ctx).ready_steps()]


@then("the second slice's write step is claimable")
def _second_claimable(ctx):
    (write,) = _open_steps(ctx, "write", 2)
    assert write.id in [s.id for s in _store(ctx).ready_steps()]


@then("the third slice's write step is still blocked")
def _third_blocked(ctx):
    (write,) = _open_steps(ctx, "write", 3)
    assert write.id not in [s.id for s in _store(ctx).ready_steps()]


@then("the second slice's write step is still blocked")
def _second_blocked(ctx):
    (write,) = _open_steps(ctx, "write", 2)
    assert write.id not in [s.id for s in _store(ctx).ready_steps()]


@then("the second slice's step stacks on the first slice's branch and PR")
def _stack(ctx):
    (write,) = _open_steps(ctx, "write", 2)
    assert _show(ctx, write.id)["stack"] == {
        "parent": ctx["item"], "parent_title": "feature story - slice a",
        "branch": "feat/slice-1", "pr": "https://github.com/o/r/pull/1",
    }


@then("cleanup ran once")
def _cleanup_once(ctx):
    assert len(ctx["cleanups"]) == 1
    assert ctx["cleanup_runs"] == [0, 0]


@then("the item closed only after the third merge")
def _closed_last(ctx):
    assert ctx["closed_after"][:2] == [False, False]
    assert ctx["closed_after"][-1] is True


@then("the inbox shows the item once with three gates in slice order")
def _inbox_group(ctx):
    lines = ctx["inbox"]
    assert lines[0].startswith(ctx["item"])
    gates = lines[1:]
    assert len(gates) == 3
    assert [("slice:%s" % n) in g for g, n in zip(gates, "abc")] == [True, True, True]
    assert all("pr:https://github.com/o/r/pull/" in g for g in gates)
    assert sum(1 for line in lines if line.startswith(ctx["item"])) == 1


@then("showing the item lists three slices in slice order")
def _show_slices(ctx):
    slices = _show(ctx, ctx["item"])["slices"]
    assert [(s["slice"], s["name"], s["base"]) for s in slices] == [
        (1, "a", None), (2, "b", 1), (3, "c", 2)]
    assert [s["pr"] for s in slices] == [
        "https://github.com/o/r/pull/%d" % n for n in (1, 2, 3)]
    assert all(s["step"] for s in slices)


@then("a new write step exists in slice 2")
def _rework_step(ctx):
    assert len(_open_steps(ctx, "write", 2)) == 1


@then("slices 1 and 3 keep their gates and open runs")
def _others_untouched(ctx):
    assert len(_open_steps(ctx, "gate", 1)) == 1
    assert len(_open_steps(ctx, "gate", 3)) == 1
    assert {r.slice for r in _runs(ctx) if r.is_open} == {1, 2, 3}


@then("the item has one open run with slice 0")
def _unsliced(ctx):
    runs = [r for r in _runs(ctx) if r.is_open]
    assert [(r.slice, r.id.rsplit(".", 1)[-1]) for r in runs] == [(0, "code")]
    assert all(s.slice == 0 for s in _store(ctx).children(ctx["item"]))


@then("the attach is refused naming the line")
def _refused(ctx):
    assert ctx["rc"] != 0
    assert "line 1" in ctx["err"]


@then("the item has no slices artifact")
def _no_artifact(ctx):
    assert not any(a.type == "slices" for a in _store(ctx).item_artifacts(ctx["item"]))
