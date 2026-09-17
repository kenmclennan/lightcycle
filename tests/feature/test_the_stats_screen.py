import datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.adapters.tui.app import DoneTable, PickerOption, StatsTable, StatsView
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-stats-screen.feature")

_TODAY = datetime.date(2026, 1, 3)
_NOW = datetime.datetime(2026, 1, 3, 9, 0, 0)


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _rendered_text(widget):
    strip = widget.render_line(0)
    return "".join(segment.text for segment in strip)


def _stats_cell(session, key, column):
    table = session.app.query_one(StatsTable)
    return table.get_cell(key, column).plain


def _picker_option_by_label(screen, label):
    from lightcycle.adapters.tui.design_system import CURSOR_GLYPH

    for option in screen.query(PickerOption):
        text = _rendered_text(option.query_one("#picker-option-label"))
        if text.replace(CURSOR_GLYPH.glyph, "").strip() == label:
            return option
    raise AssertionError("no picker option labelled %r" % label)


def _launch(ctx, store):
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store), now=lambda: _NOW)


@given("the store has no closed items anywhere")
def _store_no_closed_items(ctx):
    _launch(ctx, FakeStore(now=lambda: _NOW.isoformat()))


@given("the store has a closed item today, costing money, with a completed disposition")
def _store_closed_item_today_with_cost(ctx):
    store = FakeStore(now=lambda: _NOW.isoformat())
    item = store.create_item("done item", "a description")
    step = store.create_step(step="build", role="agent", parent=item)
    store.claim_ready("agent")
    store.record_usage(step, 100, 10, 0, 0, 2.50, "list", None)
    store.complete_node(step, "done")
    store.complete_node(item, "merged", disposition="completed")
    store._records[item]["closed_at"] = _NOW.isoformat()
    _launch(ctx, store)


@given("the store has closed items on two distinct days before today")
def _store_closed_items_two_days(ctx):
    store = FakeStore(now=lambda: _NOW.isoformat())
    earlier = store.create_item("earlier item", "a description")
    store.complete_node(earlier, "merged", disposition="completed")
    store._records[earlier]["closed_at"] = "2026-01-01T10:00:00+00:00"
    later = store.create_item("later item", "a description")
    store.complete_node(later, "merged", disposition="completed")
    store._records[later]["closed_at"] = "2026-01-02T10:00:00+00:00"
    ctx["earlier_day"] = datetime.date(2026, 1, 1)
    ctx["later_day"] = datetime.date(2026, 1, 2)
    ctx["earlier_item"] = earlier
    ctx["later_item"] = later
    _launch(ctx, store)


@when("I switch to the stats tab")
def _switch_to_stats(ctx):
    ctx["session"].press("tab")
    ctx["session"].press("tab")
    ctx["session"].press("tab")


@when("d is pressed")
def _press_d(ctx):
    ctx["session"].press("d")


@when("Down is pressed")
def _press_down(ctx):
    ctx["session"].press("down")


@when("Enter is pressed")
def _press_enter(ctx):
    ctx["session"].press("enter")


@then("the stats tab is shown")
def _stats_tab_shown(ctx):
    session = ctx["session"]
    assert session.app.query_one(StatsView).display
    assert "tab-active" in session.app.query_one("#tab-stats").classes


@then(parsers.parse(
    "the stats table shows {completed:d} items completed and {closed:d} items closed"
))
def _stats_table_closed(ctx, completed, closed):
    session = ctx["session"]
    assert _stats_cell(session, "Items Completed", "value") == str(completed)
    assert _stats_cell(session, "Items Closed", "value") == str(closed)


@then("the stats table shows a recorded cost")
def _stats_table_cost(ctx):
    assert _stats_cell(ctx["session"], "Spend", "value") == "$2.50"


@then(parsers.parse('the picker\'s header reads "{text}"'))
def _picker_header(ctx, text):
    widget = ctx["session"].app.screen.query_one("#picker-head")
    assert _rendered_text(widget).strip() == text


@then("the picker shows today with a zero count")
def _picker_shows_today_zero(ctx):
    screen = ctx["session"].app.screen
    option = _picker_option_by_label(screen, _TODAY.isoformat())
    count_widget = option.query_one(".picker-option-count")
    assert _rendered_text(count_widget).strip() == "0"


@then("the picker shows each distinct day with its own item count, most recent first")
def _picker_shows_days(ctx):
    from lightcycle.adapters.tui.design_system import CURSOR_GLYPH

    screen = ctx["session"].app.screen
    labels = []
    for option in screen.query(PickerOption):
        text = _rendered_text(option.query_one("#picker-option-label"))
        text = text.replace(CURSOR_GLYPH.glyph, "").strip()
        if text != _TODAY.isoformat():
            labels.append(text)
    assert labels == [ctx["later_day"].isoformat(), ctx["earlier_day"].isoformat()]


@then("the stats day filter row shows the earlier day")
def _stats_day_filter_row(ctx):
    widget = ctx["session"].app.query_one("#stats-day-filter-left")
    assert _rendered_text(widget).strip() == ctx["earlier_day"].isoformat()


@then("the done tab is shown, filtered to the earlier day, with its row already populated")
def _done_tab_filtered_to_earlier_day(ctx):
    session = ctx["session"]
    assert session.app._view == "done"
    assert session.app._done_day_filter == ctx["earlier_day"]
    table = session.app.query_one(DoneTable)
    assert table.row_count == 1
    assert table.ordered_rows[0].key.value == ctx["earlier_item"]
