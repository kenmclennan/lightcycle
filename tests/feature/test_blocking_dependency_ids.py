import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.domain.work import Lane, lane_for
from tests.support.fake_store import FakeStore

scenarios("blocking-dependency-ids.feature")


@pytest.fixture
def ctx():
    return {"store": FakeStore(), "ids": {}}


def _create_step(ctx, name, deps=None, role=None, parent=None):
    tid = ctx["store"].create_step(
        name, role=role, deps=[ctx["ids"][d] for d in (deps or [])], parent=parent
    )
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


@given(parsers.parse('a step "{blocked}", owned by the coder, needs a step "{dep}"'))
def _needs_one_owned(ctx, blocked, dep):
    _create_step(ctx, dep)
    _create_step(ctx, blocked, deps=[dep], role="agent")


@given(parsers.parse('a step "{blocked}", owned by the coder, needs steps "{dep1}" and "{dep2}"'))
def _needs_two_owned(ctx, blocked, dep1, dep2):
    _create_step(ctx, dep1)
    _create_step(ctx, dep2)
    _create_step(ctx, blocked, deps=[dep1, dep2], role="agent")


@then(parsers.parse('"{name}" is not ready for the coder to claim'))
def _not_ready_for_coder(ctx, name):
    ready_ids = {n.id for n in ctx["store"].ready_steps()}
    assert ctx["ids"][name] not in ready_ids


@then(parsers.parse('"{name}" is ready for the coder to claim'))
def _ready_for_coder(ctx, name):
    ready_ids = {n.id for n in ctx["store"].ready_steps()}
    assert ctx["ids"][name] in ready_ids


@when("the coder tries to claim the next step")
@when("the coder claims the next step")
def _claim(ctx):
    ctx["claimed"] = ctx["store"].claim_ready("agent")


@then("nothing is claimed")
def _nothing_claimed(ctx):
    assert ctx["claimed"] is None


@then(parsers.parse('"{name}" is the step claimed'))
def _is_the_step_claimed(ctx, name):
    assert ctx["claimed"] is not None
    assert ctx["claimed"].id == ctx["ids"][name]


@then(parsers.parse('"{name}" belongs to the queue lane, not the inbox lane'))
def _queue_lane(ctx, name):
    node = ctx["store"].get_node(ctx["ids"][name])
    assert lane_for(node.state, node.role) == Lane.QUEUE


@given(parsers.parse('an item whose only step "{blocked}" needs a step "{dep}"'))
def _item_with_dependency_held_step(ctx, blocked, dep):
    item = ctx["store"].create_item("some item")
    ctx["ids"]["item:" + blocked] = item
    _create_step(ctx, dep)
    _create_step(ctx, blocked, deps=[dep], parent=item)


@then(parsers.parse('the item containing "{name}" is ready'))
def _item_containing_is_ready(ctx, name):
    item = ctx["store"].get_node(ctx["ids"]["item:" + name])
    assert item.state == "ready"
