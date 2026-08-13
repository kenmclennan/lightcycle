import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.support.fake_store import FakeStore

scenarios("blocking-dependency-ids.feature")


@pytest.fixture
def ctx():
    return {"store": FakeStore(), "ids": {}}


def _create_step(ctx, name, deps=None):
    tid = ctx["store"].create_step(name, deps=[ctx["ids"][d] for d in (deps or [])])
    ctx["ids"][name] = tid
    return tid


@given(parsers.parse('a step "{blocked}" needs a step "{dep}"'))
def _needs_one(ctx, blocked, dep):
    _create_step(ctx, dep)
    _create_step(ctx, blocked, deps=[dep])


@given(parsers.parse('a step "{blocked}" needs steps "{dep1}" and "{dep2}"'))
def _needs_two(ctx, blocked, dep1, dep2):
    _create_step(ctx, dep1)
    _create_step(ctx, dep2)
    _create_step(ctx, blocked, deps=[dep1, dep2])


@given(parsers.parse('a step "{name}" with no dependencies'))
def _no_deps(ctx, name):
    _create_step(ctx, name)


@given(parsers.parse('"{name}" is closed'))
def _closed(ctx, name):
    ctx["store"].close(ctx["ids"][name], "done")


@given(parsers.parse('"{name}" is deleted'))
def _deleted(ctx, name):
    ctx["store"].delete(ctx["ids"][name])


@when(parsers.parse('"{name}" is read'))
def _read(ctx, name):
    ctx["node"] = ctx["store"].get_node(ctx["ids"][name])


@then(parsers.parse('its blocking ids are "{name}"'))
def _blocking_ids_one(ctx, name):
    assert set(ctx["node"].blocked_by) == {ctx["ids"][name]}


@then(parsers.parse('its blocking ids are "{name1}" and "{name2}", in either order'))
def _blocking_ids_two(ctx, name1, name2):
    assert set(ctx["node"].blocked_by) == {ctx["ids"][name1], ctx["ids"][name2]}


@then("its blocking ids are empty")
def _blocking_ids_empty(ctx):
    assert ctx["node"].blocked_by == []


@then(parsers.parse("its dependency count is {count:d}"))
def _dependency_count(ctx, count):
    assert ctx["node"].deps == count
