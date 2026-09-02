import json
import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from lightcycle.application.work.inbox import InboxInput, InboxUseCase
from lightcycle.container import make_flow_service
from tests.support.harness import Harness

scenarios("parking-a-step-for-a-human.feature")


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


def _step_node(ctx):
    return ctx["h"].store.get_node(ctx["step"])


def _block(ctx, needs=None):
    args = ["set", ctx["step"], "--state", "blocked"]
    if needs is not None:
        args += ["--needs", needs, "--reason", "a decision was needed"]
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run(*args)


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


@given("the coder has claimed the build step")
def _coder_has_claimed(ctx):
    rc, out, err = ctx["h"].run("claim", "coder")
    assert rc == 0, err
    ctx["step"] = json.loads(out)["id"]
    node = _step_node(ctx)
    ctx["role_before"] = node.role
    ctx["state_before"] = node.state
    ctx["notes_before"] = node.notes


@given(parsers.parse('I have blocked the build step, asking the human to "{question}"'))
def _have_blocked(ctx, question):
    _block(ctx, needs=question)
    assert ctx["rc"] == 0, ctx["err"]


@when("I block the build step with no stated question")
def _block_no_question(ctx):
    _block(ctx)


@when(parsers.parse('I block the build step, asking the human to "{question}"'))
def _block_with_question(ctx, question):
    _block(ctx, needs=question)


@when("I read the inbox")
def _read_inbox(ctx):
    container = cli.container()
    flow = make_flow_service(container.fs, container.store, container.config,
                              container.workflow_source)
    resp = InboxUseCase(container.store, flow).execute(InboxInput())
    ctx["inbox_rows"] = resp.rows


@then("the command is rejected")
def _rejected(ctx):
    assert ctx["rc"] != 0


@then("the build step's role is unchanged")
def _role_unchanged(ctx):
    assert _step_node(ctx).role == ctx["role_before"]


@then("the build step's state is unchanged")
def _state_unchanged(ctx):
    assert _step_node(ctx).state == ctx["state_before"]


@then("the build step's notes are unchanged")
def _notes_unchanged(ctx):
    assert _step_node(ctx).notes == ctx["notes_before"]


@then("the build step's role is human")
def _role_human(ctx):
    assert ctx["rc"] == 0, ctx["err"]
    assert _step_node(ctx).role == "human"


@then(parsers.parse('the build step\'s need reads "{question}"'))
def _need_reads(ctx, question):
    assert _step_node(ctx).needs == question


@then(parsers.parse('the build step\'s notes explain that it is blocked on "{question}"'))
def _notes_explain(ctx, question):
    assert _step_node(ctx).notes == "BLOCKED: %s" % question


@then(parsers.parse('the build step appears in the inbox with kind "{kind}"'))
def _appears_in_inbox(ctx, kind):
    row = next(r for r in ctx["inbox_rows"] if r.step.id == ctx["step"])
    ctx["row"] = row
    assert row.kind == kind


@then(parsers.parse('its offered actions include "{outcome}"'))
def _offered_actions_include(ctx, outcome):
    assert outcome in ctx["row"].outcomes
