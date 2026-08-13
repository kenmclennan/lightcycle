import datetime
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable

from lightcycle.adapters.tui.app import COLOR_CYAN, POLL_INTERVAL_SECONDS, LightcycleApp
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("priority-list-renders-current-work.feature")


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()
    patcher = state.get("bell_patcher")
    if patcher is not None:
        patcher.stop()


def _order(table):
    return [k.value for k in table.rows]


def _is_gap(value):
    return str(value).startswith("__gap")


def _icon_style(table, tid):
    return table.get_cell(tid, "icon").style


def _assert_single_gap_between(table, before_ids, after_ids):
    order = _order(table)
    end = max(order.index(i) for i in before_ids)
    start = min(order.index(i) for i in after_ids)
    between = order[end + 1 : start]
    assert len(between) == 1
    assert _is_gap(between[0])


def _launch(ctx):
    store = ctx.get("store") or FakeStore()
    container = make_test_container(store=store)
    now = ctx.get("now")
    now_callable = (lambda: now) if now is not None else None
    ctx["session"] = launch(container, now=now_callable)


@given("the store has a step in the inbox lane, an active step, and a queued step")
def _inbox_active_queued(ctx):
    store = FakeStore()
    inbox = store.create_step("inbox item", step="build", role="human")
    active = store.create_step("active item", step="build", role="coder")
    store.assign(active, "worker-1")
    store.update_state(active, State.IN_PROGRESS)
    queued = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    ctx["inbox_id"] = inbox
    ctx["active_id"] = active
    ctx["queued_id"] = queued
    ctx["attention_ids"] = [inbox]
    ctx["active_ids"] = [active]
    ctx["queued_ids"] = [queued]


@given(
    "the store has a step in the inbox lane, a step in the blocked lane, "
    "an active step, and a queued step"
)
def _inbox_blocked_active_queued(ctx):
    store = FakeStore()
    inbox = store.create_step("inbox item", step="build", role="human")
    blocker = store.create_step("blocker", step="build", role="coder")
    blocked = store.create_step("blocked item", step="build", role="coder", deps=[blocker])
    active = store.create_step("active item", step="build", role="coder")
    store.assign(active, "worker-1")
    store.update_state(active, State.IN_PROGRESS)
    queued = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    ctx["inbox_id"] = inbox
    ctx["blocked_id"] = blocked
    ctx["active_id"] = active
    ctx["queued_id"] = queued
    ctx["attention_ids"] = [inbox, blocked]
    ctx["active_ids"] = [active]
    ctx["queued_ids"] = [queued, blocker]


@given(parsers.parse('the store has a step in the blocked lane at step "{step}"'))
def _blocked_at_step(ctx, step):
    store = FakeStore()
    blocker = store.create_step("blocker", step="build", role="coder")
    blocked = store.create_step("blocked item", step=step, role="coder", deps=[blocker])
    ctx["store"] = store
    ctx["target_id"] = blocked


@given("the store has a step in the inbox lane and a queued step, with no active step")
def _inbox_and_queued_no_active(ctx):
    store = FakeStore()
    inbox = store.create_step("inbox item", step="build", role="human")
    queued = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    ctx["attention_ids"] = [inbox]
    ctx["active_ids"] = []
    ctx["queued_ids"] = [queued]


@given("the store has only a queued step")
def _only_queued(ctx):
    store = FakeStore()
    queued = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    ctx["queued_id"] = queued


@given("the store has queued steps, blocked steps, and an in-progress step")
def _queued_blocked_in_progress(ctx):
    store = FakeStore()
    store.create_step("queued", step="build", role="coder")
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("blocked", step="build", role="coder", deps=[blocker])
    running = store.create_step("running", step="build", role="coder")
    store.assign(running, "worker-1")
    store.update_state(running, State.IN_PROGRESS)
    ctx["store"] = store
    ctx["running_id"] = running


@given(
    parsers.parse(
        'the store has a step at step "{step}" that was claimed {minutes:d} minutes ago '
        "and is still in progress"
    )
)
def _claimed_minutes_ago(ctx, step, minutes):
    claimed_at = datetime.datetime(2026, 1, 1, 12, 0, 0)
    store = FakeStore(now=lambda: claimed_at.isoformat())
    tid = store.create_step("active item", step=step, role="coder")
    store.assign(tid, "worker-1")
    store.update_state(tid, State.IN_PROGRESS)
    ctx["store"] = store
    ctx["target_id"] = tid
    ctx["now"] = claimed_at + datetime.timedelta(minutes=minutes)


@given("the dashboard has launched with a step that was claimed some time ago and is still in progress")
def _launched_with_claimed_step(ctx):
    claimed_at = datetime.datetime(2026, 1, 1, 12, 0, 0)
    store = FakeStore(now=lambda: claimed_at.isoformat())
    tid = store.create_step("active item", step="build", role="coder")
    store.assign(tid, "worker-1")
    store.update_state(tid, State.IN_PROGRESS)
    clock = {"now": claimed_at + datetime.timedelta(minutes=4, seconds=50)}
    ctx["clock"] = clock
    ctx["store"] = store
    ctx["target_id"] = tid
    container = make_test_container(store=store)
    ctx["session"] = launch(container, now=lambda: clock["now"])
    table = ctx["session"].app.query_one(DataTable)
    ctx["initial_time_text"] = table.get_cell(tid, "time").plain
    ctx["initial_order"] = _order(table)


@given("the store has an active step and a queued step")
def _active_and_queued(ctx):
    store = FakeStore()
    active = store.create_step("active item", step="build", role="coder")
    store.assign(active, "worker-1")
    store.update_state(active, State.IN_PROGRESS)
    queued = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    ctx["active_id"] = active
    ctx["queued_id"] = queued


@given(parsers.parse('the store has a queued step at step "{step}"'))
def _queued_at_step(ctx, step):
    store = FakeStore()
    queued = store.create_step("queued item", step=step, role="coder")
    ctx["store"] = store
    ctx["target_id"] = queued


@given("the dashboard has launched with a queued step")
def _launched_with_queued(ctx):
    store = FakeStore()
    tid = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    ctx["target_id"] = tid
    container = make_test_container(store=store)
    ctx["session"] = launch(container)


@given(
    parsers.parse(
        "the store has a {group} step with a title longer than the priority list can fit on one line"
    )
)
def _long_title_step(ctx, group):
    store = FakeStore()
    long_title = "x" * 400
    if group == "needs-attention":
        tid = store.create_step(long_title, step="build", role="human")
    elif group == "active":
        tid = store.create_step(long_title, step="build", role="coder")
        store.assign(tid, "worker-1")
        store.update_state(tid, State.IN_PROGRESS)
    elif group == "queued":
        tid = store.create_step(long_title, step="build", role="coder")
    else:
        raise ValueError(group)
    ctx["store"] = store
    ctx["target_id"] = tid


@given(
    parsers.parse(
        "the store has a step in the blocked lane, an active step, and a queued step, "
        'each belonging to the registered project "{project}"'
    )
)
def _all_groups_with_project(ctx, project):
    store = FakeStore()
    item = store.create_item("item")
    store.add_artifact(item, "repo", project)
    blocker = store.create_step("blocker", step="build", role="coder", parent=item)
    store.create_step("blocked item", step="build", role="coder", parent=item, deps=[blocker])
    active = store.create_step("active item", step="build", role="coder", parent=item)
    store.assign(active, "worker-1")
    store.update_state(active, State.IN_PROGRESS)
    store.create_step("queued item", step="build", role="coder", parent=item)
    ctx["store"] = store


@given("the store has a queued step with no registered project")
def _queued_no_project(ctx):
    store = FakeStore()
    tid = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    ctx["target_id"] = tid


@given("the dashboard has launched with no needs-attention steps")
def _launched_no_attention(ctx):
    store = FakeStore()
    store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    patcher = patch.object(LightcycleApp, "bell")
    ctx["bell_mock"] = patcher.start()
    ctx["bell_patcher"] = patcher
    container = make_test_container(store=store)
    ctx["session"] = launch(container)


@given(
    "the dashboard has launched and a step has already entered needs-attention, "
    "ringing the bell once"
)
def _launched_with_attention_already_rung(ctx):
    store = FakeStore()
    ctx["store"] = store
    patcher = patch.object(LightcycleApp, "bell")
    ctx["bell_mock"] = patcher.start()
    ctx["bell_patcher"] = patcher
    container = make_test_container(store=store)
    ctx["session"] = launch(container)
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("blocked item", step="build", role="coder", deps=[blocker])
    ctx["session"].poll_tick()
    assert ctx["bell_mock"].call_count == 1
    ctx["bell_mock"].reset_mock()


@given("the store has a step already in the blocked lane")
def _store_already_blocked(ctx):
    store = FakeStore()
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("blocked item", step="build", role="coder", deps=[blocker])
    ctx["store"] = store
    patcher = patch.object(LightcycleApp, "bell")
    ctx["bell_mock"] = patcher.start()
    ctx["bell_patcher"] = patcher


@when("I launch the dashboard")
def _when_launch(ctx):
    if "session" not in ctx:
        _launch(ctx)


@when("that step is claimed and becomes active")
def _claim_and_activate(ctx):
    store = ctx["store"]
    tid = ctx["target_id"]
    store.assign(tid, "worker-1")
    store.update_state(tid, State.IN_PROGRESS)


@when("one poll interval elapses")
@when("one more poll interval elapses with nothing new entering needs-attention")
def _poll_elapses(ctx):
    clock = ctx.get("clock")
    if clock is not None:
        clock["now"] = clock["now"] + datetime.timedelta(seconds=POLL_INTERVAL_SECONDS)
    ctx["session"].poll_tick()


@when("a step becomes blocked by an unresolved dependency")
def _step_becomes_blocked(ctx):
    store = ctx["store"]
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("blocked item", step="build", role="coder", deps=[blocker])


@when("a new step is created directly into the queue")
def _new_queued_step(ctx):
    ctx["store"].create_step("new queued item", step="build", role="coder")


@then("the inbox step's row is grouped above the active and queued groups")
def _inbox_above(ctx):
    table = ctx["session"].app.query_one(DataTable)
    order = _order(table)
    inbox_pos = order.index(ctx["inbox_id"])
    other_positions = [order.index(i) for i in ctx["active_ids"] + ctx["queued_ids"]]
    assert inbox_pos < min(other_positions)


@then(
    "the inbox step's row is shown with its own icon and colour, distinct from the active "
    "and queued rows"
)
def _inbox_distinct(ctx):
    table = ctx["session"].app.query_one(DataTable)
    inbox_style = _icon_style(table, ctx["inbox_id"])
    other_styles = {_icon_style(table, i) for i in ctx["active_ids"] + ctx["queued_ids"]}
    assert inbox_style not in other_styles


@then(
    "the inbox step and the blocked step both appear together in the needs-attention group, "
    "above the active and queued groups"
)
def _inbox_and_blocked_together(ctx):
    table = ctx["session"].app.query_one(DataTable)
    order = _order(table)
    attention_positions = [order.index(i) for i in (ctx["inbox_id"], ctx["blocked_id"])]
    other_positions = [order.index(i) for i in ctx["active_ids"] + [ctx["queued_id"]]]
    assert max(attention_positions) < min(other_positions)
    between = order[min(attention_positions) : max(attention_positions) + 1]
    assert all(not _is_gap(v) for v in between)


@then("neither of them appears in the active group or the queued group")
def _neither_in_active_or_queued(ctx):
    table = ctx["session"].app.query_one(DataTable)
    inbox_style = _icon_style(table, ctx["inbox_id"])
    blocked_style = _icon_style(table, ctx["blocked_id"])
    active_style = _icon_style(table, ctx["active_id"])
    queued_style = _icon_style(table, ctx["queued_id"])
    assert inbox_style == blocked_style
    assert inbox_style != active_style
    assert inbox_style != queued_style


@then(parsers.parse('the needs-attention row for that step shows "{step}" as its step'))
def _needs_attention_step_shown(ctx, step):
    table = ctx["session"].app.query_one(DataTable)
    assert table.get_cell(ctx["target_id"], "step").plain == step


@then("there is exactly one blank separator row between the needs-attention group and the active group")
def _one_gap_attention_active(ctx):
    table = ctx["session"].app.query_one(DataTable)
    _assert_single_gap_between(table, ctx["attention_ids"], ctx["active_ids"])


@then("there is exactly one blank separator row between the active group and the queued group")
def _one_gap_active_queued(ctx):
    table = ctx["session"].app.query_one(DataTable)
    _assert_single_gap_between(table, ctx["active_ids"], ctx["queued_ids"])


@then("the active group renders no rows")
def _active_group_empty(ctx):
    table = ctx["session"].app.query_one(DataTable)
    for key in table.rows:
        if _is_gap(key.value):
            continue
        assert table.get_cell(key.value, "icon").style != COLOR_CYAN


@then("there is exactly one blank separator row between the needs-attention group and the queued group")
def _one_gap_attention_queued(ctx):
    table = ctx["session"].app.query_one(DataTable)
    _assert_single_gap_between(table, ctx["attention_ids"], ctx["queued_ids"])


@then("the priority list has no blank separator row")
def _no_gap_rows(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert not any(_is_gap(k.value) for k in table.rows)


@then("the active step's row is grouped below the needs-attention group and above the queued group")
def _active_between(ctx):
    table = ctx["session"].app.query_one(DataTable)
    order = _order(table)
    active_pos = order.index(ctx["active_id"])
    assert max(order.index(i) for i in ctx["attention_ids"]) < active_pos
    assert active_pos < min(order.index(i) for i in ctx["queued_ids"])


@then(
    "the active step's row is shown with its own icon and colour, distinct from the "
    "needs-attention and queued rows"
)
def _active_distinct(ctx):
    table = ctx["session"].app.query_one(DataTable)
    active_style = _icon_style(table, ctx["active_id"])
    other_styles = {_icon_style(table, i) for i in ctx["attention_ids"] + ctx["queued_ids"]}
    assert active_style not in other_styles


@then("the priority list contains a row for the in-progress step, in the active group")
def _in_progress_in_active(ctx):
    table = ctx["session"].app.query_one(DataTable)
    tid = ctx["running_id"]
    assert tid in table.rows
    assert table.get_cell(tid, "icon").style == COLOR_CYAN


@then(parsers.parse('the active row for that step shows "{step}" as its step'))
def _active_row_step_shown(ctx, step):
    table = ctx["session"].app.query_one(DataTable)
    assert table.get_cell(ctx["target_id"], "step").plain == step


@then(parsers.parse('the active row\'s elapsed time reads "{elapsed}"'))
def _active_row_elapsed_reads(ctx, elapsed):
    table = ctx["session"].app.query_one(DataTable)
    assert table.get_cell(ctx["target_id"], "time").plain == elapsed


@then("the active row's elapsed time reflects the additional time that passed")
def _elapsed_reflects_passage(ctx):
    table = ctx["session"].app.query_one(DataTable)
    new_text = table.get_cell(ctx["target_id"], "time").plain
    assert new_text != ctx["initial_time_text"]


@then("the priority list's rows stay in the same order")
def _rows_stay_in_order(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert _order(table) == ctx["initial_order"]


@then("the queued step's row is grouped below the active group")
def _queued_below_active(ctx):
    table = ctx["session"].app.query_one(DataTable)
    order = _order(table)
    assert order.index(ctx["active_id"]) < order.index(ctx["queued_id"])


@then("the queued step's row is shown with its own icon and colour, distinct from the active rows")
def _queued_distinct(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert _icon_style(table, ctx["queued_id"]) != _icon_style(table, ctx["active_id"])


@then(parsers.parse('the queued row for that step shows "{step}" as its next step'))
def _queued_row_next_step(ctx, step):
    table = ctx["session"].app.query_one(DataTable)
    assert table.get_cell(ctx["target_id"], "step").plain == step


@then("the step's row moves from the queued group into the active group")
def _moved_to_active(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert _icon_style(table, ctx["target_id"]) == COLOR_CYAN


@then(
    "that step's row wraps its title onto a second line rather than truncating it with an ellipsis"
)
def _wraps_title(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert table.rows[ctx["target_id"]].height > 1


@then(parsers.parse('every row shows "{project}" as its project'))
def _every_row_shows_project(ctx, project):
    table = ctx["session"].app.query_one(DataTable)
    for key in table.rows:
        if _is_gap(key.value):
            continue
        assert table.get_cell(key.value, "project").plain == project


@then("that step's row shows a blank project field")
def _blank_project_field(ctx):
    table = ctx["session"].app.query_one(DataTable)
    cell = table.get_cell(ctx["target_id"], "project")
    assert cell == ""


@then("the terminal bell has rung once")
def _bell_rung_once(ctx):
    assert ctx["bell_mock"].call_count == 1


@then("the terminal bell has not rung again")
def _bell_not_rung_again(ctx):
    assert ctx["bell_mock"].call_count == 0


@then("the terminal bell has not rung")
def _bell_not_rung(ctx):
    assert ctx["bell_mock"].call_count == 0
