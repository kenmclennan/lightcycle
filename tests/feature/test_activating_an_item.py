import json
import os
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from tests.support.fake_fs import graph_text_from_metas
from tests.support.harness import Harness

scenarios("activating-an-item.feature")

_METAS = {
    "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
    "reviewer": {"model": "opus", "step": "review", "routes": {"done": "open-pr", "rejected": "build"}},
}

_CODER_STEP_REQUIRES_SPEC = (
    "---\n"
    "model: sonnet\n"
    "step: build\n"
    "routes:\n"
    "  done: review\n"
    "accepts:\n"
    "  spec: required\n"
    "---\n"
    "# coder\n"
    "stub\n"
)


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
    ctx["filed_step"] = out.strip()


@given(parsers.parse('a workflow "{workflow}" that requires a brief'))
def _workflow_requires_brief(ctx, workflow):
    ctx["h"] = Harness(
        ["coder", "reviewer"],
        workflow_text=graph_text_from_metas(_METAS, entry="build", requires={"brief"}),
    )
    ctx["workflow_name"] = workflow


@given(parsers.parse('a workflow "{workflow}" whose entry step requires a spec'))
def _workflow_entry_requires_spec(ctx, workflow):
    ctx["h"] = Harness(["coder", "reviewer"], extra_steps={"coder": _CODER_STEP_REQUIRES_SPEC})
    ctx["workflow_name"] = workflow


@given(parsers.parse('an item with that workflow, with no {atype} attached'))
def _item_with_that_workflow_missing(ctx, atype):
    ctx["item"] = _new_item(ctx, workflow=ctx["workflow_name"])
    if atype != "spec":
        ctx["h"].run("attach", ctx["item"], "spec", "specs/x.md")


@given("a step")
def _plain_step(ctx):
    item = _new_item(ctx, workflow="lightcycle/spec-driven")
    ctx["h"].run("attach", item, "spec", "specs/x.md")
    rc, out, err = ctx["h"].run("set", item, "--state", "active")
    assert rc == 0, err
    ctx["step"] = out.strip()


@given("an item with no workflow, and a spec attached")
def _item_no_workflow(ctx):
    ctx["item"] = _new_item(ctx)
    ctx["h"].run("attach", ctx["item"], "spec", "specs/x.md")


@given(parsers.parse(
    'a second workflow "{workflow}" in the same origin, entering at a step owned by the reviewer'
))
def _second_workflow(ctx, workflow):
    origin, name = workflow.split("/", 1)
    text = graph_text_from_metas(_METAS, entry="review")
    path = Path(ctx["h"].root) / "workflows" / origin / "testsha" / "workflows" / ("%s.md" % name)
    path.write_text(text)


@when("I activate the item")
@when("I activate the item again")
def _activate(ctx):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("set", ctx["item"], "--state", "active")
    ctx["filed_step"] = ctx["out"].strip() if ctx["rc"] == 0 else None


@when(parsers.parse('I activate the item with workflow "{workflow}"'))
def _activate_with_workflow(ctx, workflow):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run(
        "set", ctx["item"], "--state", "active", "--workflow", workflow
    )
    ctx["filed_step"] = ctx["out"].strip() if ctx["rc"] == 0 else None


@when(parsers.parse('I activate the item at step "{step}"'))
def _activate_at_step(ctx, step):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run(
        "set", ctx["item"], "--state", "active", "--step", step
    )


@when("I activate the step")
def _activate_step(ctx):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("set", ctx["step"], "--state", "active")


@when("the coder claims the next step")
def _claim(ctx):
    rc, out, err = ctx["h"].run("claim", "coder")
    assert rc == 0, err
    ctx["claimed"] = json.loads(out) if out.strip() else None


@then("the entry step is filed for the coder")
def _entry_for_coder(ctx):
    assert ctx["rc"] == 0, ctx["err"]
    node = ctx["h"].store.get_node(ctx["filed_step"])
    assert node.role == "coder"


@then(parsers.parse('the entry step is filed for the {role}, not the {other_role}'))
def _entry_for_role_not_other(ctx, role, other_role):
    assert ctx["rc"] == 0, ctx["err"]
    node = ctx["h"].store.get_node(ctx["filed_step"])
    assert node.role == role
    assert node.role != other_role


@then("it is ready")
def _it_is_ready(ctx):
    node = ctx["h"].store.get_node(ctx["filed_step"])
    assert node.state == "ready"


@then("the claimed step is in progress")
def _claimed_in_progress(ctx):
    assert ctx["claimed"]["state"] == "in_progress"


@then("the command is rejected")
def _rejected(ctx):
    assert ctx["rc"] != 0


@then("the item is still backlogged, with no step filed")
def _still_backlogged(ctx):
    node = ctx["h"].store.get_node(ctx["item"])
    assert node.state == "backlogged"
    steps = [
        n for n in ctx["h"].store.all_nodes()
        if n.parent == ctx["item"] and n.type == "step"
    ]
    assert steps == []


@then("the item still has exactly one step filed")
def _exactly_one_step(ctx):
    steps = [
        n for n in ctx["h"].store.all_nodes()
        if n.parent == ctx["item"] and n.type == "step"
    ]
    assert len(steps) == 1


@then(parsers.parse('the item is pinned to the "{workflow}" workflow, not to "{other}"'))
def _pinned_to(ctx, workflow, other):
    node = ctx["h"].store.get_node(ctx["item"])
    pinned = node.workflow.split("@")[0]
    assert pinned == workflow
    assert pinned != other
