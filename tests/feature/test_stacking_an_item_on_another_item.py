import json

import pytest
from pytest_bdd import given, scenarios, then, when

import lightcycle.cli as cli
from lightcycle.application.pool.release_stacked_items import ReleaseStackedItemsUseCase
from tests.support.harness import DEFAULT_WORKFLOW, Harness

scenarios("stacking-an-item-on-another-item.feature")

_GRAPH = (
    "entry: build\n\n"
    "nodes:\n"
    "  build   coder\n"
    "  review  reviewer\n\n"
    "workspace:\n"
    "  review  specs\n\n"
    "phase:\n"
    "  build   code\n"
    "  review  spec\n\n"
    "edges:\n"
    "  build   done      review\n"
    "  review  done      open-pr\n"
    "  review  rejected  build\n"
)

_BRANCH = "feat/parent-code"
_PR = "https://github.com/o/r/pull/7"


@pytest.fixture
def ctx():
    return {}


@pytest.fixture(autouse=True)
def _isolate():
    orig = cli.container()
    yield
    cli.set_container(orig)


def _show(ctx, node_id):
    rc, out, err = ctx["h"].run("show", node_id)
    assert rc == 0, err
    return json.loads(out)


@given("a workflow whose build phase runs in the project repo")
def _workflow(ctx):
    ctx["h"] = Harness(["coder", "reviewer"], workflow_text=_GRAPH)


@given("a parent item whose build run has a branch but no PR")
def _parent(ctx):
    store = ctx["h"].store
    parent = store.create_item("parent story", "a description", workflow=DEFAULT_WORKFLOW)
    pid = store.open_pass(parent)
    ctx["parent_run"] = store.open_run(parent, pid, "code")
    store.set_branch(ctx["parent_run"], _BRANCH)
    ctx["parent"] = parent
    ctx["child"] = store.create_item("child story", "a description")


def _activate_child(ctx, *extra):
    return ctx["h"].run(
        "set", ctx["child"], "--state", "active", "--workflow", DEFAULT_WORKFLOW,
        "--step", "build", "--stacks-on", ctx["parent"], *extra)


@given("I have activated a child stacked on the parent")
@when("I activate a child stacked on the parent")
def _activate(ctx):
    ctx["rc"], out, ctx["err"] = _activate_child(ctx)
    assert ctx["rc"] == 0, ctx["err"]
    ctx["step"] = out.strip()


@when("I activate a child stacked on the parent and depending on another item")
def _activate_with_depends(ctx):
    other = ctx["h"].store.create_item("other", "a description")
    ctx["rc"], _out, ctx["err"] = _activate_child(ctx, "--depends", other)


@when("the parent's build run gets a PR and a tick runs")
@given("the parent's build run gets a PR and a tick runs")
def _release(ctx):
    store = ctx["h"].store
    store.set_pr(ctx["parent_run"], _PR)
    ReleaseStackedItemsUseCase(store, cli.container().flow_service()).execute()


@when("I show the child's first step")
def _show_step(ctx):
    ctx["shown"] = _show(ctx, ctx["step"])


@when("I show a specs-workspace step of the child")
def _show_specs_step(ctx):
    review = ctx["h"].store.create_step(stage="review", role="agent", item=ctx["child"])
    ctx["shown"] = _show(ctx, review)


@then("the child's first step is blocked by the parent")
def _blocked(ctx):
    assert ctx["h"].store.get_node(ctx["step"]).blocked_by == [ctx["parent"]]
    assert ctx["step"] not in [s.id for s in ctx["h"].store.ready_steps()]


@then("the child is recorded as stacked on the parent")
def _recorded(ctx):
    assert ctx["h"].store.get_item(ctx["child"]).stacks_on == ctx["parent"]


@then("the child's first step is claimable")
def _claimable(ctx):
    assert ctx["step"] in [s.id for s in ctx["h"].store.ready_steps()]


@then("the step's stack names the parent, its title, its branch and its PR")
def _stack(ctx):
    assert ctx["shown"]["stack"] == {
        "parent": ctx["parent"], "parent_title": "parent story", "branch": _BRANCH, "pr": _PR,
    }


@then("showing the child reports it is stacked on the parent")
def _child_shown(ctx):
    assert _show(ctx, ctx["child"])["stacks_on"] == ctx["parent"]


@then("showing the parent lists the child as stacked on it")
def _parent_shown(ctx):
    assert _show(ctx, ctx["parent"])["stacked_children"] == [ctx["child"]]


@then("the step reports no stack")
def _no_stack(ctx):
    assert ctx["shown"]["stack"] is None


@then("the command is rejected naming both flags")
def _rejected(ctx):
    assert ctx["rc"] != 0
    assert "--stacks-on" in ctx["err"] and "--depends" in ctx["err"]


@then("the child is still backlogged, with no step filed")
def _untouched(ctx):
    store = ctx["h"].store
    assert store.get_node(ctx["child"]).state == "backlogged"
    assert store.children(ctx["child"]) == []
