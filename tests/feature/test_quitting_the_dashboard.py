import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("quitting-the-dashboard.feature")


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


@given("the dashboard has launched")
def _given_launched(ctx):
    ctx["session"] = launch(make_test_container(store=FakeStore()))


@when(parsers.parse('the "{key}" key is pressed'))
def _press_key(ctx, key):
    ctx["session"].press(key)


@then("the dashboard exits")
def _dashboard_exits(ctx):
    assert not ctx["session"].app.is_running
