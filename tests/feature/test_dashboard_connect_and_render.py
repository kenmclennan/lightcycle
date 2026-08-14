import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable

from lightcycle.adapters.tui.app import POLL_INTERVAL_SECONDS, StatusBar
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeBreakerPort, FakeLock, launch, make_test_container

scenarios("dashboard-connect-and-render.feature")


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _launch(ctx):
    store = ctx.get("store") or FakeStore()
    container = make_test_container(
        store=store, lock=ctx.get("lock"), breaker=ctx.get("breaker")
    )
    ctx["session"] = launch(container)


@given("the lightcycle store is reachable")
def _reachable(ctx):
    store = FakeStore()
    store.create_step("a", step="build", role="coder")
    store.create_step("b", step="build", role="coder")
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("c", step="build", role="coder", deps=[blocker])
    ctx["store"] = store


@given("the store has more than ten queued or blocked steps")
def _many(ctx):
    store = FakeStore()
    ctx["ids"] = [store.create_step("t%d" % i, step="build", role="coder") for i in range(12)]
    ctx["store"] = store


@given(parsers.parse("the pool is {state}"))
def _pool_state(ctx, state):
    ctx["lock"] = FakeLock(running=(state == "running"))


@given("the breaker is closed")
def _breaker_closed(ctx):
    ctx["breaker"] = FakeBreakerPort(is_open=False)


@given("the breaker is open with a reset time")
def _breaker_open(ctx):
    ctx["reset_at"] = 1234567890.0
    ctx["breaker"] = FakeBreakerPort(is_open=True, reset_at=ctx["reset_at"])


@given("the dashboard has launched")
def _given_launched(ctx):
    _launch(ctx)


@given("the dashboard has launched and rendered the initial priority list")
def _given_launched_with_list(ctx):
    _launch(ctx)


@given("the dashboard has launched and rendered the initial status bar")
def _given_launched_with_status(ctx):
    _launch(ctx)


@when("I launch the dashboard")
def _when_launch(ctx):
    if "session" not in ctx:
        _launch(ctx)


@when("the dashboard's poll interval is read")
def _read_interval(ctx):
    ctx["interval"] = POLL_INTERVAL_SECONDS


@when("the store's queue changes")
def _queue_changes(ctx):
    session = ctx["session"]
    ctx["new_step"] = session.app.container.store.create_step(
        "new", step="build", role="coder"
    )


@when("the pool or breaker state changes")
def _state_changes(ctx):
    session = ctx["session"]
    session.app.container.lock.set_running(True)
    session.app.container.breaker.save({"open": True, "reset_at": 999.0})


@when("one poll interval elapses")
def _poll_elapses(ctx):
    ctx["session"].poll_tick()


@then("it is ten seconds")
def _is_ten_seconds(ctx):
    assert ctx["interval"] == 10


@then("the priority list is rendered with one row per queued or blocked step")
def _list_rendered(ctx):
    from lightcycle.domain.work import NodeQueue

    lanes = NodeQueue(ctx["store"].all_steps()).by_lane()
    expected = {n.id for n in lanes["queue"]} | {n.id for n in lanes["blocked"]}
    table = ctx["session"].app.query_one(DataTable)
    actual = {key.value for key in table.rows if not key.value.startswith("__gap-")}
    assert actual == expected


@then("the priority list and the status bar are both visible in the first rendered frame")
def _both_visible(ctx):
    table = ctx["session"].app.query_one(DataTable)
    status_bar = ctx["session"].app.query_one(StatusBar)
    assert table.is_mounted
    assert status_bar.is_mounted
    assert status_bar.status_text != ""


@then("the priority list contains a row for every one of them")
def _contains_all(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert table.row_count == len(ctx["ids"])
    for tid in ctx["ids"]:
        assert tid in table.rows


@then(parsers.parse("the status bar reports the pool as {state}"))
def _reports_pool(ctx, state):
    status_bar = ctx["session"].app.query_one(StatusBar)
    expected = "pool: running" if state == "running" else "pool: stopped"
    assert expected in status_bar.status_text


@then("the status bar reports the breaker as closed")
def _reports_breaker_closed(ctx):
    status_bar = ctx["session"].app.query_one(StatusBar)
    assert "breaker: closed" in status_bar.status_text


@then("the status bar reports the breaker as open with that reset time")
def _reports_breaker_open(ctx):
    status_bar = ctx["session"].app.query_one(StatusBar)
    assert "breaker: open" in status_bar.status_text
    assert str(ctx["reset_at"]) in status_bar.status_text


@then("the priority list reflects the changed queue")
def _reflects_changed_queue(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert ctx["new_step"] in table.rows


@then("the status bar reflects the changed state")
def _reflects_changed_state(ctx):
    status_bar = ctx["session"].app.query_one(StatusBar)
    assert "pool: running" in status_bar.status_text
    assert "breaker: open" in status_bar.status_text
    assert "999.0" in status_bar.status_text
