import json
import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from tests.support.harness import Harness

scenarios("pipeline.feature")


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


@given("a flow where the coder builds and the reviewer reviews")
def _flow(ctx):
    ctx["h"] = Harness(["coder", "reviewer"])


@given(parsers.parse('the item "{spec}" is filed at step "{step}"'))
def _filed(ctx, spec, step):
    title = os.path.splitext(os.path.basename(spec))[0]
    rc, item, err = ctx["h"].run(
        "new", "item", title, "--workflow", "lightcycle/spec-driven", "--description", "a description")
    assert rc == 0, err
    item = item.strip()
    ctx["h"].run("attach", item, "spec", spec)
    rc, _out, err = ctx["h"].run("set", item, "--state", "active", "--step", step)
    assert rc == 0, err
    ctx["item"] = item


@given("an agent has claimed the build step")
def _has_claimed(ctx):
    rc, out, err = ctx["h"].run("claim", "agent")
    assert rc == 0, err
    ctx["claimed"] = json.loads(out)


@when(parsers.parse('I file the item "{spec}" at step "{step}"'))
def _file(ctx, spec, step):
    title = os.path.splitext(os.path.basename(spec))[0]
    rc, item, err = ctx["h"].run(
        "new", "item", title, "--workflow", "lightcycle/spec-driven", "--description", "a description")
    assert rc == 0, err
    item = item.strip()
    ctx["h"].run("attach", item, "spec", spec)
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run(
        "set", item, "--state", "active", "--step", step
    )


@when("an agent claims the next step")
def _claim(ctx):
    rc, out, err = ctx["h"].run("claim", "agent")
    assert rc == 0, err
    ctx["claimed"] = json.loads(out) if out.strip() else None


@when(parsers.parse('that agent completes it with outcome "{outcome}"'))
def _complete(ctx, outcome):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("done", ctx["claimed"]["id"], outcome)


@when(parsers.parse('a worker completes the ready {step} step with outcome "{outcome}"'))
def _worker_routes(ctx, step, outcome):
    sid = ctx["h"].ready_agent_steps("build")[0].id
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run_as_worker(
        "handle-feedback-worker", "done", sid, outcome)


@then(parsers.parse('there is one ready agent step at the "{stage}" stage'))
def _one_ready(ctx, stage):
    assert len(ctx["h"].ready_agent_steps(stage)) == 1


@then("there are no ready agent steps")
def _no_ready(ctx):
    assert ctx["h"].ready_agent_steps() == []


@then(parsers.parse('there is no ready agent step at the "{stage}" stage'))
def _no_ready_at(ctx, stage):
    assert ctx["h"].ready_agent_steps(stage) == []


@then("the claimed step is in progress")
def _in_progress(ctx):
    assert ctx["claimed"]["state"] == "in_progress"


@then("the command is rejected")
def _rejected(ctx):
    assert ctx["rc"] != 0
