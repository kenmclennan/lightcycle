import datetime
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable

from lightcycle.adapters.tui.app import LightcycleApp, PriorityTable
from lightcycle.adapters.tui.design_system import (
    ACTIVE_GLYPH_FRAMES, COLOURS, DEPENDENCY_BLOCKED_EXTRA_GLYPH, STATE_GLYPHS,
)
from lightcycle.adapters.tui.row_grid import (
    FLEXIBLE_MINIMUM, GLYPH_WIDTHS, atomic_column_width, scrollbar_reservation_width,
)
from lightcycle.domain.work import State
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("priority-list-renders-current-work.feature")

def _is_active_glyph(plain):
    return plain in ACTIVE_GLYPH_FRAMES

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
    y = 0
    for r in table.ordered_rows:
        if r.key.value == row_id:
            break
        y += r.height
    strip = table.render_line(y)
    for segment in strip:
        if segment.text.strip() == glyph:
            return segment.style
    return None


def _row_order(session):
    table = session.app.query_one(DataTable)
    return [row.key.value for row in table.ordered_rows]


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


DEFAULT_SIZE = (120, 24)


def _launch(ctx):
    store = ctx.get("store") or FakeStore()
    now = ctx["clock"].now if "clock" in ctx else None
    ctx["session"] = launch(
        make_test_container(store=store, fs=ctx.get("fs")),
        now=now,
        size=ctx.get("size") or DEFAULT_SIZE,
    )


def _rendered_cell_text_at(table, strip, column_key):
    pad = table.cell_padding
    offset = 0
    for column in table.ordered_columns:
        start = offset + pad
        end = start + column.width
        if column.key.value == column_key:
            return "".join(segment.text for segment in strip.crop(start, end))
        offset = end + pad
    raise AssertionError("column %r not found" % column_key)


def _row_lines(session, row_id):
    table = session.app.query_one(DataTable)
    y = 0
    target = None
    height = 1
    for r in table.ordered_rows:
        if r.key.value == row_id:
            target = y
            height = r.height
            break
        y += r.height
    assert target is not None
    return [table.render_line(target + i) for i in range(height)]


@given("the store has a step in the inbox lane, an active step, and a queued step")
def _g_inbox_active_queued(ctx):
    store = FakeStore()
    ctx["inbox_id"] = store.create_step("inbox item", step="triage", role="human")
    ctx["active_id"] = store.create_step("active item", step="build", role="agent")
    store.assign(ctx["active_id"], "worker-1")
    ctx["queued_id"] = store.create_step("queued item", step="build", role="agent")
    ctx["store"] = store


@given(
    "the store has a step in the inbox lane, a dependency-held step, an active step, "
    "and a queued step"
)
def _g_inbox_blocked_active_queued(ctx):
    store = FakeStore()
    ctx["inbox_id"] = store.create_step("inbox item", step="triage", role="human")
    blocker = store.create_step("blocker", step="build", role="agent")
    ctx["blocked_id"] = store.create_step(
        "blocked item", step="build", role="agent", deps=[blocker]
    )
    ctx["active_id"] = store.create_step("active item", step="build", role="agent")
    store.assign(ctx["active_id"], "worker-1")
    ctx["queued_id"] = store.create_step("queued item", step="build", role="agent")
    ctx["store"] = store


@given(parsers.parse('the store has a step in the inbox lane at step "{step_name}"'))
def _g_inbox_at_step(ctx, step_name):
    store = FakeStore()
    ctx["target_id"] = store.create_step("inbox item", step=step_name, role="human")
    ctx["store"] = store


@given(parsers.parse(
    'the store has a step in the inbox lane at step "{step_name}", with the display phrase '
    '"{phrase}" declared for that stage'
))
def _g_inbox_at_step_with_display(ctx, step_name, phrase):
    store = FakeStore()
    ctx["target_id"] = store.create_step("inbox item", step=step_name, role="human")
    ctx["store"] = store
    ctx["fs"] = FakeFs(metas={
        step_name: {"step": step_name, "display": phrase},
    })


@given("the store has a gate step and an escalation step, both in the inbox lane")
def _g_inbox_gate_and_escalation(ctx):
    store = FakeStore()
    ctx["gate_id"] = store.create_step("await merge", step="ready-merge", role="human")
    ctx["escalation_id"] = store.create_step("stuck build", step="build", role="human")
    ctx["store"] = store
    ctx["fs"] = FakeFs(metas={
        "coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}},
        "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    })


@given(parsers.parse(
    "the store has a gate step and an escalation step, both in the inbox lane, with the "
    'display phrase "{phrase}" declared for the escalation step\'s stage'
))
def _g_inbox_gate_and_escalation_with_display(ctx, phrase):
    store = FakeStore()
    ctx["gate_id"] = store.create_step("await merge", step="ready-merge", role="human")
    ctx["escalation_id"] = store.create_step("stuck build", step="build", role="human")
    ctx["store"] = store
    ctx["fs"] = FakeFs(metas={
        "coder": {
            "model": "sonnet", "step": "build", "display": phrase, "routes": {"done": "review"},
        },
        "ready-merge": {"step": "ready-merge", "routes": {"merged": "cleanup", "changes": "build"}},
    })


@given("the store has a step in the inbox lane and a queued step, with no active step")
def _g_inbox_and_queued_no_active(ctx):
    store = FakeStore()
    ctx["inbox_id"] = store.create_step("inbox item", step="triage", role="human")
    ctx["queued_id"] = store.create_step("queued item", step="build", role="agent")
    ctx["store"] = store


@given("the store has only a queued step")
def _g_only_queued(ctx):
    store = FakeStore()
    ctx["queued_id"] = store.create_step("queued item", step="build", role="agent")
    ctx["store"] = store


@given("the store has queued steps, blocked steps, and an in-progress step")
def _g_queued_blocked_running(ctx):
    store = FakeStore()
    store.create_step("queued", step="build", role="agent")
    blocker = store.create_step("blocker", step="build", role="agent")
    store.create_step("blocked", step="build", role="agent", deps=[blocker])
    ctx["running_id"] = store.create_step("running", step="build", role="agent")
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
    tid = store.create_step("active item", step=step_name, role="agent")
    store.assign(tid, "worker-1")
    store.update_state(tid, State.IN_PROGRESS)
    clock.set(BASE_TIME)
    ctx["store"] = store
    ctx["clock"] = clock
    ctx["target_id"] = tid


@given(parsers.parse(
    'the store has a step at step "{step_name}" that was claimed {minutes:d} minutes ago '
    'and is still in progress, with the display phrase "{phrase}" declared for that stage'
))
def _g_claimed_minutes_ago_with_display(ctx, step_name, minutes, phrase):
    _g_claimed_minutes_ago(ctx, step_name, minutes)
    ctx["fs"] = FakeFs(metas={
        step_name: {"model": "sonnet", "step": step_name, "display": phrase},
    })


@given("the dashboard has launched with a step that was claimed some time ago and is still in progress")
def _g_launched_with_claimed_step(ctx):
    clock = Clock(BASE_TIME - datetime.timedelta(seconds=55))
    store = FakeStore(now=lambda: clock.now().isoformat())
    tid = store.create_step("active item", step="build", role="agent")
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
    ctx["active_id"] = store.create_step("active item", step="build", role="agent")
    store.assign(ctx["active_id"], "worker-1")
    ctx["queued_id"] = store.create_step("queued item", step="build", role="agent")
    ctx["store"] = store


@given("the store has an item with an active step and a queued step of its own")
def _g_item_active_and_queued_own(ctx):
    clock = Clock(BASE_TIME - datetime.timedelta(minutes=14))
    store = FakeStore(now=lambda: clock.now().isoformat())
    item = store.create_item("An item with two open steps", "a description")
    active = store.create_step("write the code", step="write-code", role="agent", parent=item)
    store.assign(active, "worker-1")
    store.update_state(active, State.IN_PROGRESS)
    store.create_step("open the pr", step="code-open-pr", role="agent", parent=item)
    clock.set(BASE_TIME)
    ctx["store"] = store
    ctx["clock"] = clock
    ctx["item_id"] = item
    ctx["item_title"] = "An item with two open steps"


@given("the store has an item with a step in the inbox lane and a separate active step of its own")
def _g_item_inbox_and_active_own(ctx):
    store = FakeStore()
    item = store.create_item("An item with an inbox step and an active step", "a description")
    store.create_step("await merge", step="code-await-merge", role="human", parent=item)
    active = store.create_step("write the code", step="write-code", role="agent", parent=item)
    store.assign(active, "worker-1")
    ctx["store"] = store
    ctx["item_id"] = item


@given(parsers.parse('the store has a queued step at step "{step_name}"'))
def _g_queued_at_step(ctx, step_name):
    store = FakeStore()
    ctx["target_id"] = store.create_step("queued item", step=step_name, role="agent")
    ctx["store"] = store


@given(parsers.parse(
    'the store has a queued step at step "{step_name}", with the display phrase "{phrase}" '
    "declared for that stage"
))
def _g_queued_at_step_with_display(ctx, step_name, phrase):
    _g_queued_at_step(ctx, step_name)
    ctx["fs"] = FakeFs(metas={
        step_name: {"model": "sonnet", "step": step_name, "display": phrase},
    })


@given("the dashboard has launched with a queued step")
def _g_launched_with_queued(ctx):
    store = FakeStore()
    ctx["target_id"] = store.create_step("queued item", step="build", role="agent")
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
    long_title = ("word " * 20).strip()
    if group == "needs-attention":
        tid = store.create_step(long_title, step="triage", role="human")
    elif group == "active":
        tid = store.create_step(long_title, step="build", role="agent")
        store.assign(tid, "worker-1")
    else:
        tid = store.create_step(long_title, step="build", role="agent")
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

    blocked_item = store.create_item("blocked item", "a description")
    store.add_artifact(blocked_item, "repo", project)
    blocker = store.create_step("blocker", step="build", role="agent")
    store.create_step(
        "blocked step", step="build", role="agent", deps=[blocker], parent=blocked_item
    )

    active_item = store.create_item("active item", "a description")
    store.add_artifact(active_item, "repo", project)
    active = store.create_step("active step", step="build", role="agent", parent=active_item)
    store.assign(active, "worker-1")

    queued_item = store.create_item("queued item", "a description")
    store.add_artifact(queued_item, "repo", project)
    store.create_step("queued step", step="build", role="agent", parent=queued_item)

    ctx["store"] = store
    ctx["row_ids"] = [blocked_item, active_item, queued_item]


@given("the store has a queued step with no registered project")
def _g_queued_no_project(ctx):
    store = FakeStore()
    ctx["target_id"] = store.create_step("queued item", step="build", role="agent")
    ctx["store"] = store


@given("the dashboard has launched with no needs-attention steps")
def _g_launched_no_attention(ctx):
    store = FakeStore()
    store.create_step("queued", step="build", role="agent")
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
    blocker = store.create_step("blocker", step="build", role="agent")
    store.create_step("blocked", step="build", role="agent", deps=[blocker])
    ctx["session"].poll_tick()
    ctx["bell_calls"] = _attach_bell_spy(ctx["session"])


@given("the store has a step already in the inbox lane")
def _g_store_has_inbox_step(ctx):
    store = FakeStore()
    store.create_step("inbox item", step="triage", role="human")
    ctx["store"] = store
    ctx["launch_with_bell_spy"] = True


@given("the store has three queued steps")
def _g_three_queued(ctx):
    store = FakeStore()
    ctx["row_ids"] = [store.create_step("q%d" % i, step="build", role="agent") for i in range(3)]
    ctx["store"] = store


@given("the store has more queued steps than fit on one screen")
def _g_more_than_one_screen(ctx):
    def build():
        store = FakeStore()
        for i in range(60):
            store.create_step("q%d" % i, step="build", role="agent")
        return store

    ctx["build_store"] = build
    ctx["store"] = build()


@given(parsers.parse('the store has a queued step with id "{id}" ({source})'))
def _g_queued_step_with_id(ctx, id, source):
    store = FakeStore()
    ctx["target_id"] = store.create_step("queued item", step="build", role="agent", id=id)
    ctx["store"] = store


@given(
    "the store has more queued steps than fit on one screen, one of which has a longer id "
    "than any visible row"
)
def _g_more_than_screen_with_deep_long_id(ctx):
    store = FakeStore()
    for i in range(60):
        store.create_step("q%d" % i, step="build", role="agent")
    ctx["long_id"] = "LIGHTCYCLE-999.10.10"
    ctx["target_id"] = store.create_step(
        "deep item", step="build", role="agent", id=ctx["long_id"]
    )
    ctx["store"] = store


_STACK_ID = "LC-290.1.90"
_STACK_PROJECT = "lightcycle"
_STACK_STEP = "code-review-rounds"
_STACK_TIME_MINUTES = 14
_STACK_TIME_TEXT = "14m"
_STACK_TITLE = "A title needing one continuation line"
_PRIORITY_NUM_COLUMNS = 7


def _priority_stack_terminal_width(mode):
    glyph_total = GLYPH_WIDTHS["cursor"] + GLYPH_WIDTHS["icon"]
    atomic_values = {
        "id": [_STACK_ID],
        "project": [_STACK_PROJECT],
        "step": [_STACK_STEP],
        "time": [_STACK_TIME_TEXT],
    }
    atomic_total = sum(max(1, atomic_column_width(v)) for v in atomic_values.values())
    first_line_width = glyph_total + atomic_total
    floor_width = max(first_line_width, glyph_total + FLEXIBLE_MINIMUM)
    breakpoint_width = first_line_width + FLEXIBLE_MINIMUM
    row_budget = floor_width if mode == "just wide enough to clear the floor" else breakpoint_width - 1
    return row_budget + 2 + 2 * _PRIORITY_NUM_COLUMNS + scrollbar_reservation_width(PriorityTable)


@given(parsers.parse(
    "a row whose atomic and glyph columns leave less than the flexible minimum for the title, "
    "on a terminal {mode}"
))
def _g_row_forces_stacked(ctx, mode):
    clock = Clock(BASE_TIME - datetime.timedelta(minutes=_STACK_TIME_MINUTES))
    store = FakeStore(now=lambda: clock.now().isoformat())
    tid = store.create_step(_STACK_TITLE, step=_STACK_STEP, role="agent", id=_STACK_ID)
    store.add_artifact(tid, "repo", _STACK_PROJECT)
    store.assign(tid, "worker-1")
    store.update_state(tid, State.IN_PROGRESS)
    clock.set(BASE_TIME)
    ctx["store"] = store
    ctx["clock"] = clock
    ctx["target_id"] = tid
    ctx["size"] = (_priority_stack_terminal_width(mode), 24)


@given("the dashboard has launched with a selected queued step")
def _g_launched_with_selected_queued(ctx):
    store = FakeStore()
    store.create_step("other", step="build", role="agent")
    target = store.create_step("target", step="build", role="agent")
    ctx["store"] = store
    ctx["target_id"] = target
    _launch(ctx)
    table = ctx["session"].app.query_one(DataTable)
    table.move_cursor(row=table.get_row_index(target))
    ctx["session"].pause()


@given("the dashboard has launched with a selected step")
def _g_launched_with_selected_step(ctx):
    store = FakeStore()
    first = store.create_step("first", step="build", role="agent")
    target = store.create_step("target", step="build", role="agent")
    last = store.create_step("last", step="build", role="agent")
    ctx["store"] = store
    ctx["target_id"] = target
    ctx["first_id"] = first
    ctx["last_id"] = last
    _launch(ctx)
    table = ctx["session"].app.query_one(DataTable)
    table.move_cursor(row=table.get_row_index(target))
    ctx["session"].pause()


@given("the store has a runnable queued step and a dependency-held queued step")
def _g_runnable_and_held_queued(ctx):
    store = FakeStore()
    ctx["runnable_id"] = store.create_step("runnable item", step="build", role="agent")
    blocker = store.create_step("blocker", step="build", role="agent")
    ctx["held_id"] = store.create_step(
        "held item", step="build", role="agent", deps=[blocker]
    )
    ctx["store"] = store


@given("the store has a step blocked on another item's completion")
def _g_blocked_on_other_item(ctx):
    store = FakeStore()
    blocker = store.create_step("blocker", step="build", role="agent")
    ctx["blocker_id"] = blocker
    ctx["target_id"] = store.create_step("blocked", step="build", role="agent", deps=[blocker])
    ctx["store"] = store


@given(parsers.parse(
    "the store has a step blocked on another item's completion, with the display phrase "
    '"{phrase}" declared for that step\'s own stage'
))
def _g_blocked_on_other_item_with_display(ctx, phrase):
    _g_blocked_on_other_item(ctx)
    ctx["fs"] = FakeFs(metas={
        "build": {"model": "sonnet", "step": "build", "display": phrase},
    })


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
    blocker = store.create_step("blocker", step="build", role="agent")
    store.create_step("blocked", step="build", role="agent", deps=[blocker])


@when("a step is created directly into the inbox lane")
def _w_new_inbox_step_directly(ctx):
    ctx["store"].create_step("new inbox item", step="triage", role="human")


@when("a new step is created directly into the queue")
def _w_new_queue_step_directly(ctx):
    ctx["store"].create_step("new queued", step="build", role="agent")


@when("a new step is created into the queue")
def _w_new_queue_step(ctx):
    ctx["target_id"] = ctx["store"].create_step("new item", step="build", role="agent")


@when("Down is pressed")
def _w_press_down(ctx):
    ctx["session"].press("down")


def _current_selected_row_id(session):
    table = session.app.query_one(DataTable)
    return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value


@when(parsers.parse("Down is pressed {n:d} times"))
def _w_press_down_n_times(ctx, n):
    session = ctx["session"]
    visited = [_current_selected_row_id(session)]
    for _ in range(n):
        session.press("down")
        visited.append(_current_selected_row_id(session))
    ctx["down_visits"] = visited


@when("Down is pressed once more")
def _w_press_down_once_more(ctx):
    session = ctx["session"]
    session.press("down")
    ctx["down_visits"].append(_current_selected_row_id(session))


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
    assert inbox_icon.plain == "●"
    inbox_style = _rendered_icon_style(session, ctx["inbox_id"], "●")
    assert inbox_style.color.get_truecolor().hex.lower() == COLOURS["amber"].lower()


@then("the dependency-held step appears in the queued group, not the needs-attention group")
def _t_blocked_step_in_queued_group(ctx):
    order = _row_order(ctx["session"])
    assert order.index(ctx["inbox_id"]) < order.index(ctx["blocked_id"])
    assert order.index(ctx["active_id"]) < order.index(ctx["blocked_id"])
    assert order.index(ctx["queued_id"]) < order.index(ctx["blocked_id"])


@then("the dependency-held step's icon is the queued glyph, not the needs-attention glyph")
def _t_blocked_step_queued_glyph(ctx):
    icon = _icon(ctx["session"], ctx["blocked_id"]).plain
    assert STATE_GLYPHS["queued"].glyph in icon
    assert STATE_GLYPHS["needs-attention"].glyph not in icon


@then(parsers.parse('the needs-attention row for that step shows "{step_name}" as its step'))
def _t_attention_row_shows_step(ctx, step_name):
    assert _cell(ctx["session"], ctx["target_id"], "step") == step_name


@then(parsers.parse('the gate\'s row shows icon "{glyph}" at colour {colour}'))
def _t_gate_row_icon_colour(ctx, glyph, colour):
    session = ctx["session"]
    assert _icon(session, ctx["gate_id"]).plain == glyph
    style = _rendered_icon_style(session, ctx["gate_id"], glyph)
    assert style.color.get_truecolor().hex.lower() == COLOURS[colour].lower()


@then(parsers.parse('the escalation\'s row shows icon "{glyph}" at colour {colour}'))
def _t_escalation_row_icon_colour(ctx, glyph, colour):
    session = ctx["session"]
    assert _icon(session, ctx["escalation_id"]).plain == glyph
    style = _rendered_icon_style(session, ctx["escalation_id"], glyph)
    assert style.color.get_truecolor().hex.lower() == COLOURS[colour].lower()


@then(parsers.parse('the escalation\'s step-column text reads "{text}"'))
def _t_escalation_step_text(ctx, text):
    assert _cell(ctx["session"], ctx["escalation_id"], "step") == text


@then("the escalation's row is positioned before the gate's row within the needs-attention group")
def _t_escalation_before_gate(ctx):
    order = _row_order(ctx["session"])
    assert order.index(ctx["escalation_id"]) < order.index(ctx["gate_id"])


@then("the table contains exactly 3 rows, one for each step, with no extra row of any kind")
def _t_table_exactly_three_rows(ctx):
    order = _row_order(ctx["session"])
    assert order == [ctx["inbox_id"], ctx["active_id"], ctx["queued_id"]]


@then("each row's key is a real node id")
def _t_each_row_key_is_real_node_id(ctx):
    known_ids = {ctx["inbox_id"], ctx["active_id"], ctx["queued_id"]}
    for row_id in _row_order(ctx["session"]):
        assert row_id in known_ids


@then("each row's rendered height is 2, one line of content plus one spacer line")
def _t_each_row_height_is_two(ctx):
    table = ctx["session"].app.query_one(DataTable)
    for row in table.ordered_rows:
        assert row.height == 2


@then("the table contains exactly one row, for that queued step, with no extra row of any kind")
def _t_table_exactly_one_row(ctx):
    assert _row_order(ctx["session"]) == [ctx["queued_id"]]


@then("the active group renders no rows")
def _t_active_group_empty(ctx):
    assert _row_order(ctx["session"]) == [ctx["inbox_id"], ctx["queued_id"]]


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
    assert _is_active_glyph(active_icon.plain)


@then("the priority list contains a row for the in-progress step, in the active group")
def _t_in_progress_in_active(ctx):
    session = ctx["session"]
    assert ctx["running_id"] in _row_order(session)
    assert _is_active_glyph(_icon(session, ctx["running_id"]).plain)


@then(parsers.parse('the active row for that step shows "{step_name}" as its step'))
def _t_active_row_shows_step(ctx, step_name):
    assert _cell(ctx["session"], ctx["target_id"], "step") == step_name


@then("that item's row appears exactly once, in the active group")
def _t_item_once_in_active(ctx):
    order = _row_order(ctx["session"])
    assert order.count(ctx["item_id"]) == 1
    assert _is_active_glyph(_icon(ctx["session"], ctx["item_id"]).plain)


@then("that item's row shows the item's own id and title, not the step's")
def _t_item_row_shows_item_identity(ctx):
    session = ctx["session"]
    assert ctx["item_id"] in _row_order(session)
    assert _cell(session, ctx["item_id"], "title").rstrip() == ctx["item_title"]


@then("the active row for that item shows its active step's own step name and elapsed time")
def _t_item_active_step_fields(ctx):
    session = ctx["session"]
    assert _cell(session, ctx["item_id"], "step") == "write-code"
    assert _cell(session, ctx["item_id"], "time") == "14m"


@then("that item's row's rendered height includes exactly one spacer line, the same as any other row")
def _t_item_row_height_includes_spacer(ctx):
    table = ctx["session"].app.query_one(DataTable)
    row = next(r for r in table.ordered_rows if r.key.value == ctx["item_id"])
    assert row.height == 2


@then("that item's row appears exactly once, in the needs-attention group")
def _t_item_once_in_attention(ctx):
    order = _row_order(ctx["session"])
    assert order.count(ctx["item_id"]) == 1
    assert _icon(ctx["session"], ctx["item_id"]).plain == STATE_GLYPHS["needs-attention"].glyph


@then("that item's row does not also appear in the active group")
def _t_item_not_in_active(ctx):
    session = ctx["session"]
    assert not _is_active_glyph(_icon(session, ctx["item_id"]).plain)


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
    assert _is_active_glyph(_icon(ctx["session"], ctx["target_id"]).plain)


@then("that step's row wraps its title onto a second line rather than truncating it with an ellipsis")
def _t_title_wraps(ctx):
    table = ctx["session"].app.query_one(DataTable)
    row = next(r for r in table.ordered_rows if r.key.value == ctx["target_id"])
    assert row.height > 1


@then("that step's row renders at a height of 3, two wrapped content lines plus one spacer line")
def _t_wrapped_row_height_is_three(ctx):
    table = ctx["session"].app.query_one(DataTable)
    row = next(r for r in table.ordered_rows if r.key.value == ctx["target_id"])
    assert row.height == 3


@then(parsers.parse('every row shows "{project}" as its project'))
def _t_every_row_shows_project(ctx, project):
    session = ctx["session"]
    for row_id in ctx["row_ids"]:
        assert _cell(session, row_id, "project") == project


@then("that step's row shows a blank project field")
def _t_blank_project(ctx):
    assert _cell(ctx["session"], ctx["target_id"], "project") == ""


@then(parsers.parse('that step\'s row shows "{id}" as its id, in full, on one line'))
def _t_row_shows_id_in_full(ctx, id):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    lines = _row_lines(session, ctx["target_id"])
    assert _rendered_cell_text_at(table, lines[0], "id").strip() == id


@then("the id column is already wide enough for that off-screen id, before it is scrolled into view")
def _t_id_column_wide_enough_offscreen(ctx):
    table = ctx["session"].app.query_one(DataTable)
    assert table.columns.get("id").width >= len(ctx["long_id"])


def _stacked_cell_text(table, strip):
    pad = table.cell_padding
    column = table.ordered_columns[0]
    start = pad
    end = start + column.width
    return "".join(segment.text for segment in strip.crop(start, end))


@then(
    "the cursor, icon, id, project and step remain on the row's first line, each padded to "
    "its atomic width, with time right-aligned alongside them"
)
def _t_stacked_first_line(ctx):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    lines = _row_lines(session, ctx["target_id"])
    assert len(lines) > 1
    content = _stacked_cell_text(table, lines[0])
    rest = content[GLYPH_WIDTHS["cursor"] + GLYPH_WIDTHS["icon"]:]
    assert rest.startswith(_STACK_ID)
    rest = rest[len(_STACK_ID):]
    assert rest.startswith(_STACK_PROJECT)
    rest = rest[len(_STACK_PROJECT):]
    assert rest.startswith(_STACK_STEP)
    assert content.endswith(_STACK_TIME_TEXT)


@then(parsers.parse(
    "the title appears on a continuation line indented {indent:d} characters - the row's "
    "glyph width, not where the title column starts in the unstacked grid"
))
def _t_stacked_continuation(ctx, indent):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    lines = _row_lines(session, ctx["target_id"])
    assert len(lines) > 1
    words = []
    for line in lines[1:-1]:
        text = _stacked_cell_text(table, line)
        stripped = text.rstrip()
        leading = len(stripped) - len(stripped.lstrip(" "))
        assert leading == indent
        words.extend(stripped.strip().split())
    assert words == _STACK_TITLE.split()
    ctx["_continuation_words"] = words


@then("no fragment of the title's prose is split mid-word")
def _t_no_mid_word_split(ctx):
    assert ctx["_continuation_words"] == _STACK_TITLE.split()


@then(
    "that row renders at a height of 3, the row's first line plus one continuation line "
    "plus one spacer line"
)
def _t_stacked_row_height_is_three(ctx):
    table = ctx["session"].app.query_one(DataTable)
    row = next(r for r in table.ordered_rows if r.key.value == ctx["target_id"])
    assert row.height == 3


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


@then(
    "the selection has visited the needs-attention row, then the active row, then the "
    "queued row, each exactly once"
)
def _t_visited_each_group_once(ctx):
    visited = ctx["down_visits"]
    deduped = [visited[0]]
    for row_id in visited[1:]:
        if row_id != deduped[-1]:
            deduped.append(row_id)
    assert deduped == [ctx["inbox_id"], ctx["active_id"], ctx["queued_id"]]


@then("the selection is still on the queued row")
def _t_selection_still_on_queued(ctx):
    assert ctx["down_visits"][-1] == ctx["queued_id"]


def _row_background_colours(session, row_id):
    lines = _row_lines(session, row_id)
    return {
        segment.style.bgcolor.get_truecolor().hex
        for strip in lines
        for segment in strip
        if segment.style and segment.style.bgcolor
    }


@then("every line of the selected row's rendered height carries the same cursor-highlight background colour")
def _t_selected_row_highlight_consistent(ctx):
    session = ctx["session"]
    selected_id = _current_selected_row_id(session)
    colours = _row_background_colours(session, selected_id)
    assert len(colours) == 1
    ctx["_selected_id"] = selected_id
    ctx["_selected_bg"] = next(iter(colours))


@then("that colour differs from an unselected row's background colour")
def _t_colour_differs_from_unselected(ctx):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    other_id = next(
        r.key.value for r in table.ordered_rows if r.key.value != ctx["_selected_id"]
    )
    other_colours = _row_background_colours(session, other_id)
    assert ctx["_selected_bg"] not in other_colours


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
    assert _is_active_glyph(_icon(session, ctx["target_id"]).plain)


@then("the selection is on a remaining row near the previous position")
def _t_selection_falls_near(ctx):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
    row_id = cell_key.row_key.value
    assert row_id in (ctx["first_id"], ctx["last_id"])


@then("that step's row shows the dependency chain-link icon alongside its queued icon")
def _t_shows_dependency_icon(ctx):
    icon = _icon(ctx["session"], ctx["target_id"]).plain
    assert STATE_GLYPHS["queued"].glyph in icon
    assert DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph in icon


@then("that step's row shows the blocking item's id in its step cell")
def _t_shows_blocking_id(ctx):
    step_text = _cell(ctx["session"], ctx["target_id"], "step")
    assert ctx["blocker_id"] in step_text


@then(parsers.parse(
    "that step's row shows the blocking item's id in its step cell, not \"{phrase}\""
))
def _t_shows_blocking_id_not_phrase(ctx, phrase):
    step_text = _cell(ctx["session"], ctx["target_id"], "step")
    assert ctx["blocker_id"] in step_text
    assert phrase not in step_text


@then("that step's row shows no dependency chain-link icon")
def _t_no_dependency_icon(ctx):
    icon = _icon(ctx["session"], ctx["target_id"]).plain
    assert DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph not in icon


@then("the runnable step's row is positioned before the dependency-held step's row")
def _t_runnable_before_held(ctx):
    order = _row_order(ctx["session"])
    assert order.index(ctx["runnable_id"]) < order.index(ctx["held_id"])


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


@then("the new step's row is built at the table's real width, not a stranded single-character wrap")
def _t_new_row_built_at_real_width(ctx):
    session = ctx["session"]
    table = session.app.query_one(DataTable)
    row = next(r for r in table.ordered_rows if r.key.value == ctx["target_id"])
    assert row.height == 2


def test_a_selected_rows_own_state_colour_survives_rendering():
    store = FakeStore()
    attention_id = store.create_step("inbox item", step="triage", role="human")
    active_id = store.create_step("active item", step="build", role="agent")
    store.assign(active_id, "worker-1")
    session = launch(make_test_container(store=store))

    selected_style = _rendered_icon_style(session, attention_id, STATE_GLYPHS["gate"].glyph)
    assert selected_style.color.get_truecolor().hex.lower() == COLOURS["amber"].lower()
    assert selected_style.bgcolor.get_truecolor().hex.lower() == COLOURS["selected-bg"].lower()

    session.press("down")
    deselected_style = _rendered_icon_style(session, attention_id, STATE_GLYPHS["gate"].glyph)
    assert deselected_style.color.get_truecolor().hex.lower() == COLOURS["amber"].lower()
    assert deselected_style.bgcolor.get_truecolor().hex.lower() == COLOURS["bg"].lower()

    session.close()
