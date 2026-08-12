import json
import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from tests.support.harness import Harness

scenarios("trace-role.feature")


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


@given("a flow where the coder builds, the reviewer reviews, and the pr-watcher opens the PR")
def _flow(ctx):
    ctx["h"] = Harness(["coder", "reviewer", "pr-watcher"])


@given(parsers.parse('the item "{spec}" is filed at step "{step}"'))
def _filed(ctx, spec, step):
    rc, theme, err = ctx["h"].run("new", "theme", "objective for %s" % spec, "--workflow", "lightcycle/spec-driven")
    assert rc == 0, err
    title = os.path.splitext(os.path.basename(spec))[0]
    rc, item, err = ctx["h"].run("new", "item", title, "--parent", theme.strip())
    assert rc == 0, err
    item = item.strip()
    ctx["h"].run("attach", item, "spec", spec)
    rc, _out, err = ctx["h"].run("set", item, "--state", "active", "--step", step)
    assert rc == 0, err
    ctx["item"] = item


@given(parsers.parse(
    'the pr-watcher has claimed and completed the {step} step with outcome "{outcome}"'
))
def _claimed_and_completed(ctx, step, outcome):
    rc, out, err = ctx["h"].run("claim", "pr-watcher")
    assert rc == 0, err
    claimed = json.loads(out)
    rc, out, err = ctx["h"].run("done", claimed["id"], outcome)
    assert rc == 0, err


@when("I trace the item")
def _trace(ctx):
    rc, out, err = ctx["h"].run("trace", ctx["item"], "--json")
    assert rc == 0, err
    ctx["trace"] = json.loads(out)


@then(parsers.parse('the {step} step\'s role in the trace is "{role}"'))
def _step_role(ctx, step, role):
    matches = [s for s in ctx["trace"]["steps"] if s["step"] == step]
    assert matches, "no step %r in trace" % step
    assert matches[-1]["role"] == role


@then(parsers.parse("the {step} step in the trace has its id, state, and log"))
def _step_fields(ctx, step):
    matches = [s for s in ctx["trace"]["steps"] if s["step"] == step]
    assert matches, "no step %r in trace" % step
    s = matches[-1]
    assert s["id"]
    assert s["state"]
    assert "log" in s
