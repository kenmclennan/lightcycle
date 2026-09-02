import json
import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from tests.support.harness import Harness

scenarios("closing-and-reopening-an-item.feature")


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
    args = ["new", "item", title]
    if workflow:
        args += ["--workflow", workflow]
    rc, out, err = ctx["h"].run(*args)
    assert rc == 0, err
    return out.strip()


def _step_node(ctx, step_name):
    return next(
        n for n in ctx["h"].store.all_nodes_including_done()
        if n.parent == ctx["item"] and n.step == step_name
    )


def _item_node(ctx):
    return ctx["h"].store.get_node(ctx["item"])


@given("a flow where the coder builds and the reviewer reviews")
def _flow(ctx):
    ctx["h"] = Harness(["coder", "reviewer"])


@given(parsers.parse('an item with workflow "{workflow}", with a spec attached'))
def _item_with_workflow_and_spec(ctx, workflow):
    ctx["item"] = _new_item(ctx, workflow=workflow)
    ctx["h"].run("attach", ctx["item"], "spec", "specs/x.md")


@given("I have activated the item")
def _have_activated(ctx):
    rc, out, err = ctx["h"].run("set", ctx["item"], "--state", "active")
    assert rc == 0, err


@given("the coder has completed the build step with outcome \"done\"")
def _coder_completed_build(ctx):
    rc, out, err = ctx["h"].run("claim", "coder")
    assert rc == 0, err
    claimed = json.loads(out)
    rc, out, err = ctx["h"].run("done", claimed["id"], "done")
    assert rc == 0, err


@given("the reviewer has claimed the review step")
def _reviewer_has_claimed(ctx):
    rc, out, err = ctx["h"].run("claim", "reviewer")
    assert rc == 0, err


@given(parsers.parse('I have closed the item with outcome "{outcome}"'))
def _have_closed(ctx, outcome):
    rc, out, err = ctx["h"].run("done", ctx["item"], outcome)
    assert rc == 0, err


@given("I have reopened the item")
def _have_reopened(ctx):
    rc, out, err = ctx["h"].run("set", ctx["item"], "--state", "in_progress")
    assert rc == 0, err


@when("I activate the item")
def _activate(ctx):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("set", ctx["item"], "--state", "active")


@when("the coder claims the next step")
def _claim(ctx):
    rc, out, err = ctx["h"].run("claim", "coder")
    assert rc == 0, err


@when(parsers.parse('I close the item with outcome "{outcome}"'))
def _close(ctx, outcome):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("done", ctx["item"], outcome)


@when("I reopen the item")
def _reopen_item(ctx):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("set", ctx["item"], "--state", "in_progress")



@when("I reopen the build step")
def _reopen_build_step(ctx):
    step = _step_node(ctx, "build")
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("set", step.id, "--state", "in_progress")


@when("a step is filed directly against the item")
def _file_step(ctx):
    rc, out, err = ctx["h"].run(
        "new", "step", "resume work", "--step", "build", "--parent", ctx["item"]
    )
    assert rc == 0, err


@then("the item is backlogged")
def _item_backlogged(ctx):
    assert _item_node(ctx).state == "backlogged"


@then("the item is ready")
def _item_ready(ctx):
    assert _item_node(ctx).state == "ready"


@then("the item is in progress")
def _item_in_progress(ctx):
    assert _item_node(ctx).state == "in_progress"


@then("the item is done")
def _item_done(ctx):
    assert _item_node(ctx).state == "done"


@then(parsers.parse('the item is done with outcome "{outcome}"'))
def _item_done_with_outcome(ctx, outcome):
    node = _item_node(ctx)
    assert node.state == "done"
    assert node.outcome == outcome


@then(parsers.parse('the build step is done with outcome "{outcome}"'))
def _build_step_done_with_outcome(ctx, outcome):
    node = _step_node(ctx, "build")
    assert node.state == "done"
    assert node.outcome == outcome


@then(parsers.parse('the review step is done with outcome "{outcome}"'))
def _review_step_done_with_outcome(ctx, outcome):
    node = _step_node(ctx, "review")
    assert node.state == "done"
    assert node.outcome == outcome


@then("the item's outcome and close time are cleared")
def _outcome_and_close_time_cleared(ctx):
    node = _item_node(ctx)
    assert node.outcome is None
    assert node.closed_at is None


@then("the command is rejected")
def _rejected(ctx):
    assert ctx["rc"] != 0


@then(parsers.parse('the refusal names "{text}" as the way to hand a step back to its lane'))
def _refusal_names_state_ready(ctx, text):
    assert text in ctx["err"]


@then("the refusal names the item's current state")
def _refusal_names_current_state(ctx):
    node = _item_node(ctx)
    assert ("state=%s" % node.state) in ctx["err"]

