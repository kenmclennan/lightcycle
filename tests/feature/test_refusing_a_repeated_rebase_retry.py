import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import lightcycle.cli as cli
from tests.support.rebase_retry_world import RebaseWorld

scenarios("refusing-a-repeated-rebase-retry.feature")


@pytest.fixture
def ctx():
    return {}


@pytest.fixture(autouse=True)
def _isolate():
    orig = cli.container()
    yield
    cli.set_container(orig)


@given(parsers.parse('a recheck pass that closed retried for the check "{check}"'))
def _first(ctx, check):
    ctx["w"] = RebaseWorld()
    _step, rc, err = ctx["w"].retry("rebase-retried: %s; behind by 1" % check)
    assert rc == 0, err


@given(parsers.parse('CI failed on "{check}" again'))
def _failed(ctx, check):
    ctx["step"] = ctx["w"].recheck()


@when("the next recheck pass is claimed")
def _claim(ctx):
    ctx["claim"] = json.loads(ctx["w"].claim_next())


@then(parsers.parse('its claim lists "{check}" as already retried'))
def _listed(ctx, check):
    assert ctx["claim"]["rebase_retried"] == [check]


@then(parsers.parse('closing it retried for "{check}" is refused'))
def _refused(ctx, check):
    rc, _out, err = ctx["w"].close(ctx["claim"]["id"], "retried", "rebase-retried: %s" % check)
    assert rc != 0
    assert check in err


@then("closing it broke is accepted")
def _accepted(ctx):
    rc, _out, err = ctx["w"].close(ctx["claim"]["id"], "broke", "still failing")
    assert rc == 0, err
