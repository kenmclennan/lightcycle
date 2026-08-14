import datetime
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable

from lightcycle.adapters.tui.app import LightcycleApp
from lightcycle.adapters.tui.design_system import COLOURS, DEPENDENCY_BLOCKED_EXTRA_GLYPH, STATE_GLYPHS
from lightcycle.adapters.tui.priority_list import is_gap_key
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("priority-list-renders-current-work.feature")

POLL_INTERVAL_SECONDS = 10


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _cell_text(value):
    return value.plain if hasattr(value, "plain") else value


def _cell(session, row_id, column):
    table = session.app.query_one(DataTable)
    return _cell_text(table.get_cell(row_id, column))


def _icon(session, row_id):
    table = session.app.query_one(DataTable)
    return table.get_cell(row_id, "icon")


def _rendered_icon_style(session, row_id, glyph):
    table = session.app.query_one(DataTable)
    strip = table.render_line(table.get_row_index(row_id))
    for segment in strip:
        if segment.text.strip() == glyph:
            return segment.style
    return None


def _row_order(session):
    table = session.app.query_one(DataTable)
    return [row.key.value for row in table.ordered_rows]


def _real_row_order(session):
    return [rid for rid in _row_order(session) if not is_gap_key(rid)]


def _attach_bell_spy(session):
    calls = {"count": 0}
    original = session.app.bell

    def spy():
        calls["count"] += 1
        original()

    session.app.bell = spy
    return calls


def _launch_with_bell_spy(store):
    calls = {"count": 0}
    original_bell = LightcycleApp.bell

    def spy(self):
        calls["count"] += 1
        original_bell(self)

    with patch.object(LightcycleApp, "bell", spy):
        session = launch(make_test_container(store=store))
    return session, calls


class Clock:
    def __init__(self, dt):
        self.dt = dt

    def now(self):
        return self.dt

    def set(self, dt):
        self.dt = dt

    def advance(self, **kwargs):
        self.dt = self.dt + datetime.timedelta(**kwargs)


BASE_TIME = datetime.datetime(2026, 1, 1, 12, 0, 0)


def _launch(ctx):
    store = ctx.get("store") or FakeStore()
    now = ctx["clock"].now if "clock" in ctx else None
    ctx["session"] = launch(make_test_container(store=store), now=now)


@given("the store has a step in the inbox lane, an active step, and a queued step")
def _g_inbox_active_queued(ctx):
    store = FakeStore()
    ctx["inbox_id"] = store.create_step("inbox item", step="triage", role="human")
    ctx["active_id"] = store.create_step("active item", step="build", role="coder")
    store.assign(ctx["active_id"], "worker-1")
    ctx["queued_id"] = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store


@given(
    "the store has a step in the inbox lane, a step in the blocked lane, an active step, "
    "and a queued step"
)
def _g_inbox_blocked_active_queued(ctx):
    store = FakeStore()
    ctx["inbox_id"] = store.create_step("inbox item", step="triage", role="human")
    blocker = store.create_step("blocker", step="build", role="coder")
    ctx["blocked_id"] = store.create_step(
        "blocked item", step="build", role="coder", deps=[blocker]
    )
    ctx["active_id"] = store.create_step("active item", step="build", role="coder")
    store.assign(ctx["active_id"], "worker-1")
    ctx["queued_id"] = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store


@given(parsers.parse('the store has a step in the inbox lane at step "{step_name}"'))
def _g_inbox_at_step(ctx, step_name):
    store = FakeStore()
    ctx["target_id"] = store.create_step("inbox item", step=step_name, role="human")
    ctx["store"] = store


@given("the store has a step in the inbox lane and a queued step, with no active step")
def _g_inbox_and_queued_no_active(ctx):
    store = FakeStore()
    ctx["inbox_id"] = store.create_step("inbox item", step="triage", role="human")
    ctx["queued_id"] = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store


@given("the store has only a queued step")
def _g_only_queued(ctx):
    store = FakeStore()
    ctx["queued_id"] = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store


@given("the store has queued steps, blocked steps, and an in-progress step")
def _g_queued_blocked_running(ctx):
    store = FakeStore()
    store.create_step("queued", step="build", role="coder")
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("blocked", step="build", role="coder", deps=[blocker])
    ctx["running_id"] = store.create_step("running", step="build", role="coder")
    store.assign(ctx["running_id"], "worker-1")
    ctx["store"] = store


@given(
    parsers.parse(
        'the store has a step at step "{step_name}" that was claimed {minutes:d} minutes ago '
        "and is still in progress"
    )
)
def _g_claimed_minutes_ago(ctx, step_name, minutes):
    clock = Clock(BASE_TIME - datetime.timedelta(minutes=minutes))
    store = FakeStore(now=lambda: clock.now().isoformat())
    tid = store.create_step("active item", step=step_name, role="coder")
    store.assign(tid, "worker-1")
    store.update_state(tid, State.IN_PROGRESS)
    clock.set(BASE_TIME)
    ctx["store"] = store
    ctx["clock"] = clock
    ctx["target_id"] = tid


@given("the dashboard has launched with a step that was claimed some time ago and is still in progress")
def _g_launched_with_claimed_step(ctx):
    clock = Clock(BASE_TIME - datetime.timedelta(seconds=55))
    store = FakeStore(now=lambda: clock.now().isoformat())
    tid = store.create_step("active item", step="build", role="coder")
    store.assign(tid, "worker-1")
    store.update_state(tid, State.IN_PROGRESS)
    clock.set(BASE_TIME)
    ctx["store"] = store
    ctx["clock"] = clock
    ctx["target_id"] = tid
    _launch(ctx)
    ctx["initial_elapsed"] = _cell(ctx["session"], tid, "time")
    ctx["initial_order"] = _row_order(ctx["session"])


@given("the store has an active step and a queued step")
def _g_active_and_queued(ctx):
    store = FakeStore()
    ctx["active_id"] = store.create_step("active item", step="build", role="coder")
    store.assign(ctx["active_id"], "worker-1")
    ctx["queued_id"] = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store


@given(parsers.parse('the store has a queued step at step "{step_name}"'))
def _g_queued_at_step(ctx, step_name):
    store = FakeStore()
    ctx["target_id"] = store.create_step("queued item", step=step_name, role="coder")
    ctx["store"] = store


@given("the dashboard has launched with a queued step")
def _g_launched_with_queued(ctx):
    store = FakeStore()
    ctx["target_id"] = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store
    _launch(ctx)


@given(
    parsers.parse(
        "the store has a {group} step with a title longer than the priority list can fit "
        "on one line"
    )
)
def _g_long_title_step(ctx, group):
    store = FakeStore()
    long_title = "word " * 60
    if group == "needs-attention":
        tid = store.create_step(long_title, step="triage", role="human")
    elif group == "active":
        tid = store.create_step(long_title, step="build", role="coder")
        store.assign(tid, "worker-1")
    else:
        tid = store.create_step(long_title, step="build", role="coder")
    ctx["store"] = store
    ctx["target_id"] = tid


@given(
    parsers.parse(
        "the store has a step in the blocked lane, an active step, and a queued step, each "
        'belonging to the registered project "{project}"'
    )
)
def _g_three_steps_with_project(ctx, project):
    store = FakeStore()

    blocked_item = store.create_item("blocked item")
    store.add_artifact(blocked_item, "repo", project)
    blocker = store.create_step("blocker", step="build", role="coder")
    blocked = store.create_step(
        "blocked step", step="build", role="coder", deps=[blocker], parent=blocked_item
    )

    active_item = store.create_item("active item")
    store.add_artifact(active_item, "repo", project)
    active = store.create_step("active step", step="build", role="coder", parent=active_item)
    store.assign(active, "worker-1")

    queued_item = store.create_item("queued item")
    store.add_artifact(queued_item, "repo", project)
    queued = store.create_step("queued step", step="build", role="coder", parent=queued_item)

    ctx["store"] = store
    ctx["row_ids"] = [blocked, active, queued]


@given("the store has a queued step with no registered project")
def _g_queued_no_project(ctx):
    store = FakeStore()
    ctx["target_id"] = store.create_step("queued item", step="build", role="coder")
    ctx["store"] = store


@given("the dashboard has launched with no needs-attention steps")
def _g_launched_no_attention(ctx):
    store = FakeStore()
    store.create_step("queued", step="build", role="coder")
    ctx["store"] = store
    _launch(ctx)
    ctx["bell_calls"] = _attach_bell_spy(ctx["session"])


@given(
    "the dashboard has launched and a step has already entered needs-attention, ringing the "
    "bell once"
)
def _g_launched_with_attention_already_rung(ctx):
    store = FakeStore()
    ctx["store"] = store
    _launch(ctx)
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("blocked", step="build", role="coder", deps=[blocker])
    ctx["session"].poll_tick()
    ctx["bell_calls"] = _attach_bell_spy(ctx["session"])


@given("the store has a step already in the blocked lane")
def _g_store_has_blocked_step(ctx):
    store = FakeStore()
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("blocked", step="build", role="coder", deps=[blocker])
    ctx["store"] = store
    ctx["launch_with_bell_spy"] = True


@given("the store has three queued steps")
def _g_three_queued(ctx):
    store = FakeStore()
    ctx["row_ids"] = [store.create_step("q%d" % i, step="build", role="coder") for i in range(3)]
    ctx["store"] = store


@given("the store has more queued steps than fit on one screen")
def _g_more_than_one_screen(ctx):
    def build():
        store = FakeStore()
        for i in range(60):
            store.create_step("q%d" % i, step="build", role="coder")
        return store

    ctx["build_store"] = build
    ctx["store"] = build()


@given("the dashboard has launched with a selected queued step")
def _g_launched_with_selected_queued(ctx):
    store = FakeStore()
    store.create_step("other", step="build", role="coder")
    target = store.create_step("target", step="build", role="coder")
    ctx["store"] = store
    ctx["target_id"] = target
    _launch(ctx)
    table = ctx["session"].app.query_one(DataTable)
    table.move_cursor(row=table.get_row_index(target))
    ctx["session"].pause()


@given("the dashboard has launched with a selected step")
def _g_launched_with_selected_step(ctx):
    store = FakeStore()
    first = store.create_step("first", step="build", role="coder")
    target = store.create_step("target", step="build", role="coder")
    last = store.create_step("last", step="build", role="coder")
    ctx["store"] = store
    ctx["target_id"] = target
    ctx["first_id"] = first
    ctx["last_id"] = last
    _launch(ctx)
    table = ctx["session"].app.query_one(DataTable)
    table.move_cursor(row=table.get_row_index(target))
    ctx["session"].pause()


@given("the store has a step blocked on another item's completion")
def _g_blocked_on_other_item(ctx):
    store = FakeStore()
    blocker = store.create_step("blocker", step="build", role="coder")
    ctx["blocker_id"] = blocker
    ctx["target_id"] = store.create_step("blocked", step="build", role="coder", deps=[blocker])
    ctx["store"] = store


@given("the store has a step in the inbox lane")
def _g_inbox_only(ctx):
    store = FakeStore()
    ctx["target_id"] = store.create_step("inbox item", step="triage", role="human")
    ctx["store"] = store


@given("the store has no steps in any lane")
def _g_no_steps(ctx):
    ctx["store"] = FakeStore()


@given("the dashboard has launched with no steps in any lane")
def _g_launched_no_steps(ctx):
    ctx["store"] = FakeStore()
    _launch(ctx)


@when("I launch the dashboard")
def _w_launch(ctx):
    if "session" in ctx:
        return
    if ctx.get("launch_with_bell_spy"):
        session, calls = _launch_with_bell_spy(ctx["store"])
        ctx["session"] = session
        ctx["bell_calls"] = calls
    else:
        _launch(ctx)


@when("that step is claimed and becomes active")
def _w_claim_and_activate(ctx):
    store = ctx["store"]
    tid = ctx["target_id"]
    store.assign(tid, "worker-1")
    store.update_state(tid, State.IN_PROGRESS)


@when("one poll interval elapses")
def _w_poll_elapses(ctx):
    if "clock" in ctx:
        ctx["clock"].advance(seconds=POLL_INTERVAL_SECONDS)
    ctx["session"].poll_tick()


@when("one more poll interval elapses with nothing new entering needs-attention")
def _w_poll_elapses_nothing_new(ctx):
    ctx["session"].poll_tick()


@when("a step becomes blocked by an unresolved dependency")
def _w_step_becomes_blocked(ctx):
    store = ctx["store"]
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("blocked", step="build", role="coder", deps=[blocker])


@when("a new step is created directly into the queue")
def _w_new_queue_step_directly(ctx):
    ctx["store"].create_step("new queued", step="build", role="coder")


@when("a new step is created into the queue")
def _w_new_queue_step(ctx):
    ctx["store"].create_step("new item", step="build", role="coder")


@when("Down is pressed")
def _w_press_down(ctx):
    ctx["session"].press("down")


@when("Up is pressed")
def _w_press_up(ctx):
    ctx["session"].press("up")


@when("the selection is on the last row")
def _w_selection_on_last_row(ctx):
    table = ctx["session"].app.query_one(DataTable)
    table.move_cursor(row=table.row_count - 1)
    ctx["session"].pause()


@when("Ctrl-D is pressed")
def _w_press_ctrl_d(ctx):
    ctx["session"].press("ctrl+d")


@when("Ctrl-U is pressed")
def _w_press_ctrl_u(ctx):
    ctx["session"].press("ctrl+u")


@when("that step is completed")
def _w_complete_target(ctx):
    ctx["store"].close(ctx["target_id"], "done")


@then("the inbox step's row is grouped above the active and queued groups")
def _t_inbox_above(ctx):
    order = _row_order(ctx["session"])
    assert order.index(ctx["inbox_id"]) < order.index(ctx["active_id"])
    assert order.index(ctx["inbox_id"]) < order.index(ctx["queued_id"])


@then(
    "the inbox step's row is shown with its own icon and colour, distinct from the active "
    "and queued rows"
)
def _t_inbox_distinct(ctx):
    session = ctx["session"]
    inbox_icon = _icon(session, ctx["inbox_id"])
    active_icon = _icon(session, ctx["active_id"])
    queued_icon = _icon(session, ctx["queued_id"])
    assert (inbox_icon.plain, inbox_icon.style) != (active_icon.plain, active_icon.style)
    assert (inbox_icon.plain, inbox_icon.style) != (queued_icon.plain, queued_icon.style)
    assert inbox_icon.plain == STATE_GLYPHS["needs-attention"].glyph


@then(
    "the inbox step and the blocked step both appear together in the needs-attention group, "
    "above the active and queued groups"
)
def _t_inbox_and_blocked_together(ctx):
    order = _row_order(ctx["session"])
    attention_index = min(order.index(ctx["inbox_id"]), order.index(ctx["blocked_id"]))
    between = order[
        attention_index : max(order.index(ctx["inbox_id"]), order.index(ctx["blocked_id"])) + 1
    ]
    assert set(between) == {ctx["inbox_id"], ctx["blocked_id"]}
    assert order.index(ctx["inbox_id"]) < order.index(ctx["active_id"])
    assert order.index(ctx["blocked_id"]) < order.index(ctx["active_id"])
    assert order.index(ctx["inbox_id"]) < order.index(ctx["queued_id"])
    assert order.index(ctx["blocked_id"]) < order.index(ctx["queued_id"])


@then("neither of them appears in the active group or the queued group")
def _t_neither_in_active_or_queued(ctx):
    session = ctx["session"]
    for row_id in (ctx["inbox_id"], ctx["blocked_id"]):
        icon = _icon(session, row_id).plain
        assert STATE_GLYPHS["active"].glyph not in icon
        assert STATE_GLYPHS["queued"].glyph not in icon


@then(parsers.parse('the needs-attention row for that step shows "{step_name}" as its step'))
def _t_attention_row_shows_step(ctx, step_name):
    assert _cell(ctx["session"], ctx["target_id"], "step") == step_name


@then(
    "there is exactly one blank separator row between the needs-attention group and the "
    "active group"
)
def _t_gap_attention_active(ctx):
    order = _row_order(ctx["session"])
    start = order.index(ctx["inbox_id"])
    end = order.index(ctx["active_id"])
    between = order[start + 1 : end]
    assert len(between) == 1
    assert is_gap_key(between[0])


@then("there is exactly one blank separator row between the active group and the queued group")
def _t_gap_active_queued(ctx):
    order = _row_order(ctx["session"])
    start = order.index(ctx["active_id"])
    end = order.index(ctx["queued_id"])
    between = order[start + 1 : end]
    assert len(between) == 1
    assert is_gap_key(between[0])


@then("the active group renders no rows")
def _t_active_group_empty(ctx):
    assert _real_row_order(ctx["session"]) == [ctx["inbox_id"], ctx["queued_id"]]


@then(
    "there is exactly one blank separator row between the needs-attention group and the "
    "queued group"
)
def _t_gap_attention_queued(ctx):
    order = _row_order(ctx["session"])
    start = order.index(ctx["inbox_id"])
    end = order.index(ctx["queued_id"])
    between = order[start + 1 : end]
    assert len(between) == 1
    assert is_gap_key(between[0])


@then("the priority list has no blank separator row")
def _t_no_gap_row(ctx):
    order = _row_order(ctx["session"])
    assert not any(is_gap_key(rid) for rid in order)


@then("the active step's row is grouped below the needs-attention group and above the queued group")
def _t_active_between(ctx):
    order = _row_order(ctx["session"])
    assert order.index(ctx["inbox_id"]) < order.index(ctx["active_id"]) < order.index(
        ctx["queued_id"]
    )


@then(
    "the active step's row is shown with its own icon and colour, distinct from the "
    "needs-attention and queued rows"
)
def _t_active_distinct(ctx):
    session = ctx["session"]
    active_icon = _icon(session, ctx["active_id"])
    inbox_icon = _icon(session, ctx["inbox_id"])
    queued_icon = _icon(session, ctx["queued_id"])
    assert (active_icon.plain, active_icon.style) != (inbox_icon.plain, inbox_icon.style)
    assert (active_icon.plain, active_icon.style) != (queued_icon.plain, queued_icon.style)
    assert active_icon.plain == STATE_GLYPHS["active"].glyph


@then("the priority list contains a row for the in-progress step, in the active group")
def _t_in_progress_in_active(ctx):
    session = ctx["session"]
    assert ctx["running_id"] in _real_row_order(session)
    assert _icon(session, ctx["running_id"]).plain == STATE_GLYPHS["active"].glyph


@then(parsers.parse('the active row for that step shows "{step_name}" as its step'))
def _t_active_row_shows_step(ctx, step_name):
    assert _cell(ctx["session"], ctx["target_id"], "step") == step_name


@then(parsers.parse('the active row\'s elapsed time reads "{expected}"'))
def _t_active_row_elapsed_reads(ctx, expected):
    assert _cell(ctx["session"], ctx["target_id"], "time") == expected


@then("the active row's elapsed time reflects the additional time that passed")
def _t_elapsed_increased(ctx):
    current = _cell(ctx["session"], ctx["target_id"], "time")
    assert current != ctx["initial_elapsed"]


@then("the priority list's rows stay in the same order")
def _t_order_unchanged(ctx):
    assert _row_order(ctx["session"]) == ctx["initial_order"]


@then("the queued step's row is grouped below the active group")
def _t_queued_below_active(ctx):
    order = _row_order(ctx["session"])
    assert order.index(ctx["active_id"]) < order.index(ctx["queued_id"])


@then("the queued step's row is shown with its own icon and colour, distinct from the active rows")
def _t_queued_distinct(ctx):
    session = ctx["session"]
    queued_icon = _icon(session, ctx["queued_id"])
    active_icon = _icon(session, ctx["active_id"])
    assert (queued_icon.plain, queued_icon.style) != (active_icon.plain, active_icon.style)
    assert queued_icon.plain == STATE_GLYPHS["queued"].glyph


@then(parsers.parse('the queued row for that step shows "{step_name}" as its next step'))
def _t_queued_row_shows_step(ctx, step_name):
    assert _cell(ctx["session"], ctx["target_id"], "step") == step_name


@then("the step's row moves from the queued group into the active group")
def _t_step_moves_to_active(ctx):
    assert _icon(ctx["session"], ctx["target_id"]).plain == STATE_GLYPHS["active"].glyph


@then("that step's row wraps its title onto a second line rather than truncating it with an ellipsis")
def _t_title_wraps(ctx):
    table = ctx["session"].app.query_one(DataTable)
    row = next(r for r in table.ordered_rows if r.key.value == ctx["target_id"])
    assert row.height > 1


@then(parsers.parse('every row shows "{project}" as its project'))
def _t_every_row_shows_project(ctx, project):
    session = ctx["session"]
    for row_id in ctx["row_ids"]:
        assert _cell(session, row_id, "project") == project


@then("that step's row shows a blank project field")
def _t_blank_project(ctx):
    assert _cell(ctx["session"], ctx["target_id"], "project") == ""


@then("the terminal bell has rung once")
def _t_bell_rung_once(ctx):
    assert ctx["bell_calls"]["count"] == 1


@then("the terminal bell has not rung again")
def _t_bell_not_rung_again(ctx):
    assert ctx["bell_calls"]["count"] == 0


@then("the terminal bell has not rung")
def _t_bell_not_rung(ctx):
    assert ctx["bell_calls"]["count"] == 0


@then("the selection has moved to the second row")
def _t_selection_second_row(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert table.cursor_row == 1


@then("the selection has not moved from the first row")
def _t_selection_first_row(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert table.cursor_row == 0


@then("the selection has not moved past the last row")
def _t_selection_last_row(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert table.cursor_row == table.row_count - 1


@then("the selection has moved forward by the same amount Page Down would move it")
def _t_ctrl_d_matches_page_down(ctx):
    actual = ctx["session"].app.query_one(DataTable).cursor_row
    compare_session = launch(make_test_container(store=ctx["build_store"]()))
    compare_session.press("pagedown")
    expected = compare_session.app.query_one(DataTable).cursor_row
    compare_session.close()
    assert actual == expected
    assert actual > 0


@then("the selection is back on the row it started on")
def _t_selection_back_to_start(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert table.cursor_row == 0


@then("the selection is still on that step, now in the active group")
def _t_selection_follows_to_active(ctx):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
    assert cell_key.row_key.value == ctx["target_id"]
    assert _icon(session, ctx["target_id"]).plain == STATE_GLYPHS["active"].glyph


@then("the selection is on a remaining row near the previous position")
def _t_selection_falls_near(ctx):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
    row_id = cell_key.row_key.value
    assert row_id in (ctx["first_id"], ctx["last_id"])


@then("the selection is not on a blank separator row")
def _t_selection_not_on_gap(ctx):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
    assert not is_gap_key(cell_key.row_key.value)


@then("that step's row shows the dependency chain-link icon alongside its needs-attention icon")
def _t_shows_dependency_icon(ctx):
    icon = _icon(ctx["session"], ctx["target_id"]).plain
    assert STATE_GLYPHS["needs-attention"].glyph in icon
    assert DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph in icon


@then("that step's row shows the blocking item's id in its step cell")
def _t_shows_blocking_id(ctx):
    step_text = _cell(ctx["session"], ctx["target_id"], "step")
    assert ctx["blocker_id"] in step_text


@then("that step's row shows no dependency chain-link icon")
def _t_no_dependency_icon(ctx):
    icon = _icon(ctx["session"], ctx["target_id"]).plain
    assert DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph not in icon


@then("a calm message is shown in place of the priority list")
def _t_calm_message_shown(ctx):
    app = ctx["session"].app
    assert app.query_one("#empty-state").display is True
    assert app.query_one(DataTable).display is False


@then("the priority list is shown in place of the calm message")
def _t_list_shown_again(ctx):
    app = ctx["session"].app
    assert app.query_one("#empty-state").display is False
    assert app.query_one(DataTable).display is True


def test_a_selected_rows_own_state_colour_survives_rendering():
    store = FakeStore()
    attention_id = store.create_step("inbox item", step="triage", role="human")
    active_id = store.create_step("active item", step="build", role="coder")
    store.assign(active_id, "worker-1")
    session = launch(make_test_container(store=store))

    selected_style = _rendered_icon_style(
        session, attention_id, STATE_GLYPHS["needs-attention"].glyph
    )
    assert selected_style.color.get_truecolor().hex.lower() == COLOURS["red"].lower()
    assert selected_style.bgcolor.get_truecolor().hex.lower() == COLOURS["selected-bg"].lower()

    session.press("down")
    deselected_style = _rendered_icon_style(
        session, attention_id, STATE_GLYPHS["needs-attention"].glyph
    )
    assert deselected_style.color.get_truecolor().hex.lower() == COLOURS["red"].lower()
    assert deselected_style.bgcolor.get_truecolor().hex.lower() != COLOURS["selected-bg"].lower()

    session.close()
