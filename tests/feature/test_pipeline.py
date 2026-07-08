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
    rc, theme, err = ctx["h"].run("new", "theme", "objective for %s" % spec)
    assert rc == 0, err
    title = os.path.splitext(os.path.basename(spec))[0]
    rc, item, err = ctx["h"].run("new", "item", title, "--parent", theme.strip())
    assert rc == 0, err
    item = item.strip()
    ctx["h"].run("attach", item, "spec", spec)
    rc, _out, err = ctx["h"].run("set", item, "--state", "active", "--step", step)
    assert rc == 0, err
    ctx["item"] = item


@given("the coder has claimed the build step")
def _has_claimed(ctx):
    rc, out, err = ctx["h"].run("claim", "coder")
    assert rc == 0, err
    ctx["claimed"] = json.loads(out)


@when(parsers.parse('I file the item "{spec}" at step "{step}"'))
def _file(ctx, spec, step):
    rc, theme, err = ctx["h"].run("new", "theme", "objective for %s" % spec)
    assert rc == 0, err
    title = os.path.splitext(os.path.basename(spec))[0]
    rc, item, err = ctx["h"].run("new", "item", title, "--parent", theme.strip())
    assert rc == 0, err
    item = item.strip()
    ctx["h"].run("attach", item, "spec", spec)
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run(
        "set", item, "--state", "active", "--step", step
    )


@when("the coder claims the next step")
def _claim(ctx):
    rc, out, err = ctx["h"].run("claim", "coder")
    assert rc == 0, err
    ctx["claimed"] = json.loads(out) if out.strip() else None


@when(parsers.parse('the coder completes it with outcome "{outcome}"'))
def _complete(ctx, outcome):
    ctx["rc"], ctx["out"], ctx["err"] = ctx["h"].run("done", ctx["claimed"]["id"], outcome)


@then(parsers.parse("there is one ready step for the {role}"))
def _one_ready(ctx, role):
    assert len(ctx["h"].ready_steps(role)) == 1


@then(parsers.parse("there are no ready steps for the {role}"))
def _no_ready(ctx, role):
    assert ctx["h"].ready_steps(role) == []


@then("the claimed step is in progress")
def _in_progress(ctx):
    assert ctx["claimed"]["status"] == "in-progress"


@then("the command is rejected")
def _rejected(ctx):
    assert ctx["rc"] != 0
