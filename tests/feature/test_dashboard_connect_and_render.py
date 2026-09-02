import time

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable, Static

from lightcycle import __version__
from lightcycle.adapters.tui.app import POLL_INTERVAL_SECONDS, StatusBar
from lightcycle.adapters.tui.design_system import COLOURS, FOOTER_GLYPHS
from lightcycle.application.setup import UpgradeResponse
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


def _rendered_segment(session, widget_id):
    widget = session.app.query_one(widget_id, Static)
    strip = widget.render_line(0)
    text = "".join(segment.text for segment in strip)
    style = None
    for segment in strip:
        if segment.text.strip():
            style = segment.style
            break
    return widget, text, style


def _colour_of(style):
    return style.color.get_truecolor().hex.lower()


def _launch(ctx):
    store = ctx.get("store") or FakeStore()
    ctx["store"] = store
    container = make_test_container(
        store=store, lock=ctx.get("lock"), breaker=ctx.get("breaker")
    )
    ctx["session"] = launch(container, upgrade_check=ctx.get("upgrade_check"))


@given("the lightcycle store is reachable")
def _reachable(ctx):
    store = FakeStore()
    store.create_step("a", step="build", role="agent")
    store.create_step("b", step="build", role="agent")
    blocker = store.create_step("blocker", step="build", role="agent")
    store.create_step("c", step="build", role="agent", deps=[blocker])
    ctx["store"] = store


@given("the store has more than ten queued or blocked steps")
def _many(ctx):
    store = FakeStore()
    ctx["ids"] = [store.create_step("t%d" % i, step="build", role="agent") for i in range(12)]
    ctx["store"] = store


@given(parsers.parse("the pool is {state}"))
def _pool_state(ctx, state):
    ctx["lock"] = FakeLock(running=(state == "running"))


@given("the breaker is closed")
def _breaker_closed(ctx):
    ctx["breaker"] = FakeBreakerPort(is_open=False)


@given("the breaker is open with a reset time")
def _breaker_open(ctx):
    ctx["reset_at"] = time.time() + 3600
    ctx["breaker"] = FakeBreakerPort(is_open=True, reset_at=ctx["reset_at"])


@given("a newer version is available")
def _newer_version_available(ctx):
    ctx["remote_version"] = "9.9.9"
    ctx["upgrade_check"] = lambda: UpgradeResponse(
        current=__version__, remote=ctx["remote_version"], available=True, applied=False
    )


@given("no newer version is available")
def _no_newer_version(ctx):
    ctx["upgrade_check"] = lambda: UpgradeResponse(
        current=__version__, remote=__version__, available=False, applied=False
    )


@given("the upgrade check fails")
def _upgrade_check_fails(ctx):
    def _raise():
        raise RuntimeError("network down")

    ctx["upgrade_check"] = _raise


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
        "new", step="build", role="agent"
    )


@when("the pool or breaker state changes")
def _state_changes(ctx):
    session = ctx["session"]
    session.app.container.lock.set_running(True)
    session.app.container.breaker.save({"open": True, "reset_at": time.time() + 3600})


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
    expected = {n.id for n in lanes["queue"]}
    table = ctx["session"].app.query_one(DataTable)
    actual = {key.value for key in table.rows if not key.value.startswith("__gap-")}
    assert actual == expected


@then("the priority list and the status bar are both visible in the first rendered frame")
def _both_visible(ctx):
    table = ctx["session"].app.query_one(DataTable)
    status_bar = ctx["session"].app.query_one(StatusBar)
    assert table.is_mounted
    assert status_bar.is_mounted
    _, version_text, _ = _rendered_segment(ctx["session"], "#status-version")
    assert version_text.strip() != ""


@then("the priority list contains a row for every one of them")
def _contains_all(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert table.row_count == len(ctx["ids"])
    for tid in ctx["ids"]:
        assert tid in table.rows


@then(parsers.parse("the status bar reports the pool as {state}"))
def _reports_pool(ctx, state):
    _, text, style = _rendered_segment(ctx["session"], "#status-pool")
    if state == "running":
        assert text == "%s pool running" % FOOTER_GLYPHS["pool-running"].glyph
        assert _colour_of(style) == COLOURS["cyan"].lower()
    else:
        assert text == "%s pool not running" % FOOTER_GLYPHS["pool-stopped"].glyph
        assert _colour_of(style) == COLOURS["dim"].lower()


@then("the status bar reports the breaker as closed")
def _reports_breaker_closed(ctx):
    _, text, style = _rendered_segment(ctx["session"], "#status-claude")
    assert text == "%s claude available" % FOOTER_GLYPHS["claude-available"].glyph
    assert _colour_of(style) == COLOURS["cyan"].lower()


@then("the status bar reports the breaker as open with that reset time")
def _reports_breaker_open(ctx):
    _, text, style = _rendered_segment(ctx["session"], "#status-claude")
    expected_ts = time.strftime("%H:%M:%S", time.localtime(ctx["reset_at"]))
    assert text == "%s claude unavailable · resumes %s" % (
        FOOTER_GLYPHS["claude-unavailable"].glyph, expected_ts
    )
    assert _colour_of(style) == COLOURS["red"].lower()


@then("the status bar shows the installed version")
def _shows_installed_version(ctx):
    _, text, style = _rendered_segment(ctx["session"], "#status-version")
    assert text == "v%s" % __version__
    assert _colour_of(style) == COLOURS["dim"].lower()


@then("the status bar shows the upgrade indicator with that version")
def _shows_upgrade_indicator(ctx):
    widget, text, style = _rendered_segment(ctx["session"], "#status-upgrade")
    assert widget.display
    assert text == "%s v%s available" % (
        FOOTER_GLYPHS["upgrade-available"].glyph, ctx["remote_version"]
    )
    assert _colour_of(style) == COLOURS["amber"].lower()


@then("the status bar shows no upgrade indicator")
def _shows_no_upgrade_indicator(ctx):
    widget, text, _ = _rendered_segment(ctx["session"], "#status-upgrade")
    assert not widget.display
    assert text.strip() == ""


@then("the priority list reflects the changed queue")
def _reflects_changed_queue(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert ctx["new_step"] in table.rows


@then("the status bar reflects the changed state")
def _reflects_changed_state(ctx):
    _, pool_text, _ = _rendered_segment(ctx["session"], "#status-pool")
    _, claude_text, _ = _rendered_segment(ctx["session"], "#status-claude")
    assert pool_text == "%s pool running" % FOOTER_GLYPHS["pool-running"].glyph
    assert "claude unavailable" in claude_text
