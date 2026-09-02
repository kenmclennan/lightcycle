import json
import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from tests.support.harness import DEFAULT_WORKFLOW, Harness

scenarios("rolling-up-and-cascading-parent-state.feature")

_FINALISE_STEP = (
    "---\n"
    "model: sonnet\n"
    "step: finalise\n"
    "---\n"
    "# finaliser\n"
    "stub\n"
)

_FINALISE_WORKFLOW_TEXT = "entry: finalise\n\nnodes:\n  finalise  finaliser\n"


@pytest.fixture
def ctx():
    return {}


@pytest.fixture(autouse=True)
def _isolate():
    saved = dict(os.environ)
    orig = cli.container()
    yield
    os.environ.clear()
    os.environ.update(saved)
    cli.set_container(orig)


def _new_item(ctx, workflow=None, title="some item"):
    args = ["new", "item", title, "--description", "a description"]
    if workflow:
        args += ["--workflow", workflow]
    rc, out, err = ctx["h"].run(*args)
    assert rc == 0, err
    return out.strip()


def _activate(ctx, item):
    rc, out, err = ctx["h"].run("set", item, "--state", "active")
    assert rc == 0, err
    return out.strip()


@given("a flow where the coder builds and the reviewer reviews")
def _flow(ctx):
    ctx["h"] = Harness(["coder", "reviewer"])
    ctx["workflow_name"] = DEFAULT_WORKFLOW


@given("a flow whose entry step is also its terminal step")
def _terminal_flow(ctx):
    ctx["h"] = Harness(
        [], extra_steps={"finaliser": _FINALISE_STEP}, workflow_text=_FINALISE_WORKFLOW_TEXT,
    )
    ctx["workflow_name"] = DEFAULT_WORKFLOW


@given("an item with no steps")
def _item_no_steps(ctx):
    ctx["item"] = _new_item(ctx)


@given("an item with that workflow")
def _item_with_workflow(ctx):
    ctx["item"] = _new_item(ctx, workflow=ctx["workflow_name"])


@given("two items, both with that workflow")
def _two_items(ctx):
    ctx["item"] = _new_item(ctx, workflow=ctx["workflow_name"], title="first item")
    ctx["item2"] = _new_item(ctx, workflow=ctx["workflow_name"], title="second item")


@given("I have activated the item")
def _have_activated(ctx):
    ctx["filed_step"] = _activate(ctx, ctx["item"])


@given("I have activated both items")
def _have_activated_both(ctx):
    ctx["filed_step"] = _activate(ctx, ctx["item"])
    ctx["filed_step2"] = _activate(ctx, ctx["item2"])


@when("the coder claims the next step")
def _claim(ctx):
    rc, out, err = ctx["h"].run("claim", "agent")
    assert rc == 0, err
    ctx["claimed"] = json.loads(out)


@when(parsers.parse('the coder completes the build step with outcome "{outcome}"'))
def _coder_completes_build(ctx, outcome):
    rc, out, err = ctx["h"].run("done", ctx["claimed"]["id"], outcome)
    assert rc == 0, err


@when(parsers.parse("I complete the item's only step with outcome \"{outcome}\""))
def _complete_item_only_step(ctx, outcome):
    rc, out, err = ctx["h"].run("done", ctx["filed_step"], outcome)
    assert rc == 0, err


@when(parsers.parse("I complete the first item's only step with outcome \"{outcome}\""))
def _complete_first_item_only_step(ctx, outcome):
    rc, out, err = ctx["h"].run("done", ctx["filed_step"], outcome)
    assert rc == 0, err


@then("the item is backlogged")
def _item_backlogged(ctx):
    assert ctx["h"].store.get_node(ctx["item"]).state == "backlogged"


@then("the item is done")
def _item_done(ctx):
    assert ctx["h"].store.get_node(ctx["item"]).state == "done"


@then("the item is in progress")
def _item_in_progress(ctx):
    assert ctx["h"].store.get_node(ctx["item"]).state == "in_progress"


@then("the first item is done")
def _first_item_done(ctx):
    assert ctx["h"].store.get_node(ctx["item"]).state == "done"


@then("the second item is ready")
def _second_item_ready(ctx):
    assert ctx["h"].store.get_node(ctx["item2"]).state == "ready"
