import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from tests.support.harness import Harness

scenarios("artifact-fields.feature")


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
        "new", "item", title, "--workflow", "lightcycle/spec-driven")
    assert rc == 0, err
    item = item.strip()
    ctx["h"].run("attach", item, "spec", spec)
    rc, _out, err = ctx["h"].run("set", item, "--state", "active", "--step", step)
    assert rc == 0, err
    ctx["item"] = item


@when(parsers.parse('I attach a "{atype}" artifact "{value}" to the item'))
def _attach(ctx, atype, value):
    rc, _out, err = ctx["h"].run("attach", ctx["item"], atype, value)
    assert rc == 0, err


@when(parsers.parse('I attach a "{atype}" artifact "{value}" to the item with kind "{kind}"'))
def _attach_with_kind(ctx, atype, value, kind):
    rc, _out, err = ctx["h"].run("attach", ctx["item"], atype, value, "--kind", kind)
    assert rc == 0, err


@when(parsers.parse('I attach a "{atype}" artifact "{value}" to the item with the internal flag'))
def _attach_internal(ctx, atype, value):
    rc, _out, err = ctx["h"].run("attach", ctx["item"], atype, value, "--internal")
    assert rc == 0, err


def _attached_artifact(ctx, value="some-value"):
    arts = [a for a in ctx["h"].store.item_artifacts(ctx["item"]) if a.value == value]
    return arts[-1]


@then(parsers.parse('the attached artifact has kind "{kind}"'))
def _has_kind(ctx, kind):
    assert _attached_artifact(ctx).kind == kind


@then("the attached artifact is not internal")
def _not_internal(ctx):
    assert not _attached_artifact(ctx).internal


@then("the attached artifact is internal")
def _is_internal(ctx):
    assert _attached_artifact(ctx).internal
