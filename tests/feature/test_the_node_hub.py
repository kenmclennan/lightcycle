import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.app import BacklogTable, PriorityTable
from lightcycle.adapters.tui.design_system import COLOURS, HUB_SHORTCUTS, STATE_GLYPHS
from lightcycle.adapters.tui.footer import ShortcutBar
from lightcycle.adapters.tui.hub import (
    DescriptionPane, EscalationPanel, HierarchyPagingTable, HubTabStrip, NodeHubScreen,
)
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-node-hub.feature")

LC_277_6_REASON = (
    "CI still pending on PR #424 head 7d4d840 (integration and unit-feature jobs in-progress) - "
    "scenario review itself is clean (see feedback), just waiting on CI to conclude before "
    "posting a pass verdict"
)
LC_277_6_REASON_EXTENDED = (
    LC_277_6_REASON
    + " Also, the integration job flaked once and was retried successfully before landing, "
    "and the operator confirmed the fix was genuinely safe to merge once CI turns fully "
    "green again."
)
WRAPPING_HUB_SIZE = (100, 30)


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


def _rendered_line_text(widget, y):
    strip = widget.render_line(y)
    return "".join(segment.text for segment in strip)


def _segment_style_for_substring(widget, y, substring):
    strip = widget.render_line(y)
    for segment in strip:
        if substring in segment.text:
            return segment.style
    return None


def _rendered_panel_text(panel):
    return "\n".join(_rendered_line_text(panel, y) for y in range(panel.size.height))


def _text(screen, selector):
    widget = screen.query_one(selector, Static)
    if not widget.display:
        return None
    return _rendered_text(widget).strip()


def _rendered_icon_style(table, row_id, glyph):
    strip = table.render_line(table.get_row_index(row_id))
    for segment in strip:
        if segment.text.strip() == glyph:
            return segment.style
    return None


def _rendered_cell_text(table, row_id, column_key):
    strip = table.render_line(table.get_row_index(row_id))
    pad = table.cell_padding
    offset = 0
    for column in table.ordered_columns:
        start = offset + pad
        end = start + column.width
        if column.key.value == column_key:
            return "".join(segment.text for segment in strip.crop(start, end))
        offset = end + pad
    raise AssertionError("column %r not found" % column_key)


def _painted_row(session, y):
    return session.app.screen._compositor.render_strips()[y]


def _painted_spans(strip):
    x = 0
    spans = []
    for segment in strip:
        text = segment.text
        if text.strip():
            style = segment.style
            colour = style.color.get_truecolor().hex.lower() if style and style.color else None
            spans.append((x, x + len(text) - 1, colour))
        x += len(text)
    return spans


_HUB_TABS_BY_TYPE = {
    "item": (("description", "Description"), ("hierarchy", "Hierarchy"), ("artifacts", "Artifacts")),
    "step": (("detail", "Detail"), ("log", "Log")),
}


def _hub_tabs(session):
    screen = session.app.screen
    node_type = screen.container.store.get_node(screen._node_id).type
    return _HUB_TABS_BY_TYPE[node_type]


def _assert_tab_strip_rendered(session, active_tab):
    for tab_id, label in _hub_tabs(session):
        widget = session.app.screen.query_one("#hub-tab-%s" % tab_id, Static)
        strip = _painted_row(session, widget.region.y)
        start, end = widget.region.x, widget.region.x + widget.region.width
        text = "".join(segment.text for segment in strip.crop(start, end)).strip()
        assert text == label, "tab %r label not visible in the rendered frame (got %r)" % (label, text)

        spans = _painted_spans(strip)
        colours = {colour for s0, s1, colour in spans if s0 >= start and s1 < end}
        expected = COLOURS["cyan"].lower() if tab_id == active_tab else COLOURS["dim"].lower()
        assert expected in colours, (
            "tab %r not painted in the expected colour %r; painted colours were %r"
            % (label, expected, colours)
        )

    tabs = _hub_tabs(session)
    xs = [
        session.app.screen.query_one("#hub-tab-%s" % tab_id, Static).region.x
        for tab_id, _ in tabs
    ]
    assert xs == sorted(xs), "tabs not rendered left to right as %r; x positions were %r" % (
        [label for _, label in tabs], xs
    )


def _launch(ctx, store, size=None):
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store, fs=ctx.get("fs")), size=size)
    return ctx["session"]


@given("an item, its hub open")
def _item_hub_open(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    ctx["item_id"] = item
    ctx["node_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given("a step, its hub open")
def _step_hub_open(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["node_id"] = step
    session = _launch(ctx, store)
    _push_hub(ctx, session, step)
    ctx["original_screen"] = session.app.screen


@given("the priority list is showing with an item")
def _priority_with_item(ctx):
    store = FakeStore()
    item = store.create_item("an item", "a description")
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    store.claim_ready("agent")
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store)


@given("the priority list is showing with a needs-attention step")
def _priority_with_needs_attention_step(ctx):
    store = FakeStore()
    item = store.create_item("an item", "a description")
    step = store.create_step("await merge", step="await-merge", role="human", parent=item)
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store)


@given("the priority list is showing with a queued step")
def _priority_with_queued_step(ctx):
    store = FakeStore()
    item = store.create_item("an item", "a description")
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store)


@given("an item with a project and a workflow, its hub open")
def _item_full_identity(ctx):
    store = FakeStore()
    item = store.create_item("Full item", "a description", workflow="lightcycle/spec-driven@abc123")
    store.add_artifact(item, "repo", "org/repo")
    store.create_step("write code", step="write-code", role="agent", parent=item)
    ctx["item_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given("an item with no workflow, its hub open")
def _item_no_workflow(ctx):
    store = FakeStore()
    item = store.create_item("No workflow item", "a description")
    store.create_step("write code", step="write-code", role="agent", parent=item)
    ctx["item_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given(parsers.re(r'an item at step "(?P<step>[^"]+)", its hub open'))
def _item_at_step(ctx, step):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    store.create_step("s", step=step, role="agent", parent=item)
    ctx["item_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given(parsers.re(
    r'an item at step "(?P<step>[^"]+)" whose workflow declares the display phrase '
    r'"(?P<phrase>[^"]+)" for that stage, its hub open'
))
def _item_at_step_with_display(ctx, step, phrase):
    ctx["fs"] = FakeFs(metas={
        "write-code": {"model": "sonnet", "step": step, "display": phrase},
    })
    store = FakeStore()
    item = store.create_item("Item", "a description")
    store.create_step("s", step=step, role="agent", parent=item)
    ctx["item_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given(parsers.re(
    r'an item at step "(?P<step>[^"]+)" performed by the role "(?P<role>[^"]+)", its hub open'
))
def _item_at_step_with_role(ctx, step, role):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    store.create_step("s", step=step, role=role, parent=item)
    ctx["item_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given(parsers.parse('an active item at step "{step}" claimed {minutes:d} minutes ago, its hub open'))
def _active_item_claimed_minutes_ago(ctx, step, minutes):
    import datetime

    now = datetime.datetime(2026, 1, 1, 12, 0, 0)
    claimed_at = now - datetime.timedelta(minutes=minutes)

    store = FakeStore(now=lambda: claimed_at.isoformat())
    item = store.create_item("Item", "a description")
    store.create_step("s", step=step, role="agent", parent=item)
    store.claim_ready("agent")

    ctx["item_id"] = item
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store), now=lambda: now)
    _push_hub(ctx, ctx["session"], item)


@given("an item at a human step, with no worker, its hub open")
def _item_human_step_no_worker(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    store.create_step("await-merge", step="await-merge", role="human", parent=item)
    ctx["item_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given("a step is selected, rather than an item")
def _step_selected(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    store.claim_ready("agent")
    ctx["item_id"] = item
    ctx["step_id"] = step
    session = _launch(ctx, store)
    session.press("enter")


def _push_hub(ctx, session, node_id):
    session.run(
        lambda: session.app.push_screen(
            NodeHubScreen(session.app.container, node_id, session.app._now)
        )
    )
    session.pause()
    session.pause()


@given(parsers.parse('an item with the status "{status}", its hub open'))
def _item_with_status(ctx, status):
    store = FakeStore()
    if status == "active":
        item = store.create_item("Item", "a description")
        store.create_step("s", step="build", role="agent", parent=item)
        store.claim_ready("agent")
        node_id = item
    elif status == "needs-attention on a human step":
        item = store.create_item("Item", "a description")
        store.create_step("s", step="await-merge", role="human", parent=item)
        node_id = item
    elif status == "blocked on another item's completion":
        blocker = store.create_item("Blocker", "a description")
        item = store.create_item("Item", "a description")
        store.dep_add(item, blocker)
        node_id = item
    elif status == "queued, not yet run":
        item = store.create_item("Item", "a description")
        store.create_step("s", step="build", role="agent", parent=item)
        node_id = item
    elif status == "done":
        item = store.create_item("Item", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.close(step, "done")
        node_id = item
    else:
        raise AssertionError("unhandled status %r" % status)
    ctx["node_id"] = node_id
    session = _launch(ctx, store)
    _push_hub(ctx, session, node_id)


@given(parsers.parse('a step with the status "{status}", its hub open'))
def _step_with_status(ctx, status):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    if status == "active":
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.claim_ready("agent")
    elif status == "needs-attention, a human step":
        step = store.create_step("s", step="await-merge", role="human", parent=item)
    elif status == "blocked on another item's completion":
        blocker = store.create_item("Blocker", "a description")
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.dep_add(step, blocker)
    elif status == "queued, not yet run":
        step = store.create_step("s", step="build", role="agent", parent=item)
    elif status == "done":
        step = store.create_step("s", step="build", role="agent", parent=item)
        store.close(step, "done")
    else:
        raise AssertionError("unhandled status %r" % status)
    ctx["node_id"] = step
    session = _launch(ctx, store)
    _push_hub(ctx, session, step)


@given(parsers.parse('an item\'s hub is open, on the "{tab}" tab'))
def _item_hub_open_on_tab(ctx, tab):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    store.create_step("s", step="build", role="agent", parent=item)
    ctx["item_id"] = item
    ctx["node_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)
    screen = session.app.screen
    screen._active_tab = tab.lower()
    screen.query_one(HubTabStrip).set_active(screen._active_tab)
    session.run(screen._apply_tab_visibility)
    session.pause()


@given(parsers.parse('a step\'s hub is open, on the "{tab}" tab'))
def _step_hub_open_on_tab(ctx, tab):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["node_id"] = step
    session = _launch(ctx, store)
    _push_hub(ctx, session, step)
    screen = session.app.screen
    screen._active_tab = tab.lower()
    screen.query_one(HubTabStrip).set_active(screen._active_tab)
    session.run(screen._apply_tab_visibility)
    session.pause()


@given("the backlog is showing with a todo item")
def _backlog_todo_item(ctx):
    store = FakeStore()
    item = store.create_item("Todo item", "a description")
    ctx["item_id"] = item
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    ctx["session"].press("tab")


@given("an item blocked on another item's completion, its hub open")
def _item_blocked_on_dependency(ctx):
    store = FakeStore()
    blocker = store.create_item("Blocker item", "a description")
    item = store.create_item("Blocked item", "a description")
    store.dep_add(item, blocker)
    ctx["item_id"] = item
    ctx["node_id"] = item
    ctx["blocker_id"] = blocker
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given("an item blocked on another item's completion, with a step of its own, its hub open")
def _item_blocked_with_step(ctx):
    store = FakeStore()
    blocker = store.create_item("Blocker item", "a description")
    item = store.create_item("Blocked item", "a description")
    store.dep_add(item, blocker)
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    ctx["item_id"] = item
    ctx["node_id"] = item
    ctx["blocker_id"] = blocker
    ctx["step_id"] = step
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given("an item whose current step is escalated, needing rework, its hub open")
def _item_escalated_rework(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    store.update_metadata(step, {"needs": "Resolve the merge conflict manually"})
    store.route_to_human(step, "BLOCKED: Resolve the merge conflict manually")
    ctx["item_id"] = item
    ctx["step_id"] = step
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given("an item whose current step is escalated, needing rework, with a recorded reason, its hub open")
def _item_escalated_rework_with_reason(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    store.update_metadata(
        step,
        {"needs": "Resolve the merge conflict manually", "reason": "CI reported a real conflict"},
    )
    store.route_to_human(step, "BLOCKED: Resolve the merge conflict manually")
    ctx["item_id"] = item
    ctx["step_id"] = step
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given("an item whose current step is escalated, with a reason long enough to wrap, its hub open")
def _item_escalated_long_reason(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    store.update_metadata(
        step, {"needs": "Resolve the merge conflict manually", "reason": LC_277_6_REASON}
    )
    store.route_to_human(step, "BLOCKED: Resolve the merge conflict manually")
    ctx["item_id"] = item
    ctx["step_id"] = step
    session = _launch(ctx, store, size=WRAPPING_HUB_SIZE)
    _push_hub(ctx, session, item)


@given(
    "an item whose current step is escalated, with a reason far longer than the panel's line cap, "
    "its hub open"
)
def _item_escalated_over_cap_reason(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    store.update_metadata(
        step, {"needs": "Resolve the merge conflict manually", "reason": LC_277_6_REASON_EXTENDED}
    )
    store.route_to_human(step, "BLOCKED: Resolve the merge conflict manually")
    ctx["item_id"] = item
    ctx["step_id"] = step
    session = _launch(ctx, store, size=WRAPPING_HUB_SIZE)
    _push_hub(ctx, session, item)


@given(
    "an item whose current step is escalated, with a reason that wraps differently at two widths, "
    "its hub open"
)
def _item_escalated_resizable_reason(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("write code", step="write-code", role="agent", parent=item)
    store.update_metadata(
        step,
        {
            "needs": "Resolve the merge conflict manually",
            "reason": "Investigate the flaky retry logic in the deploy pipeline before "
            "merging further changes",
        },
    )
    store.route_to_human(step, "BLOCKED: Resolve the merge conflict manually")
    ctx["item_id"] = item
    ctx["step_id"] = step
    session = _launch(ctx, store, size=WRAPPING_HUB_SIZE)
    _push_hub(ctx, session, item)


@given(parsers.parse('an item that is "{status}", its hub open'))
def _item_that_is(ctx, status):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    if status == "active":
        store.create_step("s", step="build", role="agent", parent=item)
        store.claim_ready("agent")
    elif status == "queued":
        store.create_step("s", step="build", role="agent", parent=item)
    else:
        raise AssertionError("unhandled status %r" % status)
    ctx["item_id"] = item
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given("an item's hub is open, showing an escalation reason that names a blocking item")
def _hub_open_with_escalation(ctx):
    store = FakeStore()
    blocker = store.create_item("Blocker item", "a description")
    item = store.create_item("Blocked item", "a description")
    store.dep_add(item, blocker)
    ctx["blocker_id"] = blocker
    session = _launch(ctx, store)
    session.run(
        lambda: session.app.push_screen(NodeHubScreen(session.app.container, item, session.app._now))
    )
    session.pause()


@given(
    "an item's hub is open, showing an escalation reason that names a blocking item "
    "whose own current step is active"
)
def _hub_open_with_escalation_active_blocker(ctx):
    store = FakeStore()
    blocker = store.create_item("Blocker item", "a description")
    store.create_step("s", step="build", role="agent", parent=blocker)
    store.claim_ready("agent")
    item = store.create_item("Blocked item", "a description")
    store.dep_add(item, blocker)
    ctx["blocker_id"] = blocker
    session = _launch(ctx, store)
    session.run(
        lambda: session.app.push_screen(NodeHubScreen(session.app.container, item, session.app._now))
    )
    session.pause()


@given(parsers.parse('I cycle to the "{tab}" tab with ]'))
@when(parsers.parse('I cycle to the "{tab}" tab with ]'))
def _cycle_to_tab(ctx, tab):
    screen = ctx["session"].app.screen
    tab_id = tab.lower()
    order = screen._tab_order
    current = order.index(screen._active_tab)
    target = order.index(tab_id)
    for _ in range((target - current) % len(order)):
        ctx["session"].press("]")
    ctx["target_tab"] = tab_id


@given("a blocked item's hub is open, with content on every tab")
def _blocked_items_hub_open_with_content(ctx):
    store = FakeStore()
    blocker = store.create_item("Blocker item", "a description")
    store.create_step("s", step="build", role="agent", parent=blocker)
    item = store.create_item("Blocked item", "a description")
    store.dep_add(item, blocker)
    store.create_step("own step", step="write-code", role="agent", parent=item)
    store.claim_ready("agent")
    store.add_artifact(item, "repo", "org/repo")
    store.edit_node(item, description="A description")
    ctx["item_id"] = item
    ctx["blocker_id"] = blocker
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)
    ctx["original_screen"] = session.app.screen


@given("I jump to its blocking item's hub")
def _jump_to_blocking_item(ctx):
    ctx["session"].press("b")


@given("I opened an item's hub from a specific row in the priority list, with content on every tab")
def _opened_from_priority_row(ctx):
    store = FakeStore()
    other = store.create_item("Other", "a description")
    store.create_step("other", step="build", role="agent", parent=other)
    item = store.create_item("Target", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    store.claim_ready("agent")
    store.add_artifact(item, "repo", "org/repo")
    store.edit_node(item, description="A description")
    ctx["item_id"] = item
    ctx["step_id"] = step
    session = _launch(ctx, store)
    table = session.app.query_one(PriorityTable)
    table.move_cursor(row=list(table.rows).index(item) if item in table.rows else 0)
    ids = [row.key.value for row in table.ordered_rows]
    ctx["cursor_id"] = ids[table.cursor_row]
    session.press("enter")


@given("I opened an item's hub and scrolled or navigated within it")
def _opened_and_navigated(ctx):
    store = FakeStore()
    item = store.create_item("Target", "a description")
    store.create_step("s", step="build", role="agent", parent=item)
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)
    session.press("down")


@given("the backlog is shown with a todo item")
def _backlog_shown_with_todo(ctx):
    store = FakeStore()
    item = store.create_item("Todo item", "a description")
    ctx["item_id"] = item
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    ctx["session"].press("tab")


@given("I opened a backlog item's hub from a specific row in the backlog, with content on every tab")
def _opened_backlog_hub(ctx):
    store = FakeStore()
    store.create_item("Other todo", "a description")
    item = store.create_item("Target todo", "a description")
    store.add_artifact(item, "repo", "org/repo")
    store.edit_node(item, description="A description")
    ctx["item_id"] = item
    session = _launch(ctx, store)
    session.press("tab")
    table = session.app.query_one(BacklogTable)
    ids = [row.key.value for row in table.ordered_rows]
    table.move_cursor(row=ids.index(item))
    ctx["cursor_id"] = item
    session.press("enter")


@given(
    "an item's step was active when the breaker tripped and killed its worker, "
    "and was reclaimed to ready, its hub open"
)
def _step_reclaimed(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    store.claim_ready("agent")
    store.reclaim(step)
    ctx["item_id"] = item
    ctx["step_id"] = step
    session = _launch(ctx, store)
    _push_hub(ctx, session, item)


@given(parsers.parse("{key} is pressed"))
@when(parsers.parse("{key} is pressed"))
def _key_pressed(ctx, key):
    keymap = {
        "Enter": "enter", "→": "right", "Esc": "escape", "←": "left",
        "Tab": "tab", "]": "]", "[": "[", "Down": "down",
    }
    ctx["session"].press(keymap.get(key, key))


@when("I select that item's row")
def _select_item_row(ctx):
    table = ctx["session"].app.query_one(PriorityTable)
    ids = [row.key.value for row in table.ordered_rows]
    table.move_cursor(row=ids.index(ctx["item_id"]))


@when("I select that step's row")
def _select_step_row(ctx):
    table = ctx["session"].app.query_one(PriorityTable)
    ids = [row.key.value for row in table.ordered_rows]
    table.move_cursor(row=ids.index(ctx["item_id"]))


@when(parsers.parse('the "{tab}" tab is active'))
def _tab_is_active(ctx, tab):
    screen = ctx["session"].app.screen
    screen._active_tab = tab.lower()
    screen.query_one(HubTabStrip).set_active(screen._active_tab)
    ctx["session"].run(screen._apply_tab_visibility)
    ctx["session"].pause()


@when("the terminal is resized narrower")
def _terminal_resized_narrower(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    ctx["pre_resize_height"] = panel.size.height
    ctx["pre_resize_line_2"] = _rendered_line_text(panel, 2)
    ctx["session"].resize(50, WRAPPING_HUB_SIZE[1])



@then("the step's own hub opens, replacing the list on screen")
def _hub_opens_replacing_list(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["step_id"]


@then(parsers.parse('the step\'s own hub opens, landing on the "{tab}" tab'))
def _step_hub_opens_landing_on_tab(ctx, tab):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["step_id"]
    tab_id = tab.lower()
    assert screen._active_tab == tab_id
    _assert_tab_strip_rendered(ctx["session"], tab_id)


@then("the header shows its id, its title, its project, and its workflow")
def _header_shows_identity(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-id") == ctx["item_id"]
    assert _text(screen, "#hub-title") == "Full item"
    assert _text(screen, "#hub-project") is not None
    assert "repo" in _text(screen, "#hub-project")
    assert _text(screen, "#hub-workflow") is not None


@then("no workflow line is shown in the header")
def _no_workflow_line(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-workflow") is None


@then(parsers.parse('the header names "{step}" as the current step'))
def _header_names_step(ctx, step):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-step") == "STEP: %s" % step


@then(parsers.parse('the header shows "{role}" as the role'))
def _header_shows_role(ctx, role):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-role") == "ROLE: %s" % role


@then(parsers.parse('the header\'s elapsed time reads "{elapsed}"'))
def _header_elapsed_reads(ctx, elapsed):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-elapsed") == "ELAPSED: %s" % elapsed


@then("no role is shown in the header")
def _no_role_shown(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-role") is None


@then("no elapsed time is shown in the header")
def _no_elapsed_shown(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-elapsed") is None


@then("the header shows its role and its state")
def _header_shows_role_and_state(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-role") == "ROLE: agent"
    assert _text(screen, "#hub-state") is not None


_HEADER_FIELD_SELECTORS = {
    "STEP": "#hub-step", "ROLE": "#hub-role", "ELAPSED": "#hub-elapsed", "STATE": "#hub-state",
}


@then(parsers.parse("the header's \"{key}\" key is shown in the dim colour"))
def _header_key_dim_colour(ctx, key):
    screen = ctx["session"].app.screen
    widget = screen.query_one(_HEADER_FIELD_SELECTORS[key], Static)
    style = _segment_style_for_substring(widget, 0, "%s:" % key)
    assert style is not None
    assert style.color.get_truecolor().hex.lower() == COLOURS["dim"].lower()


@then(parsers.parse("the header's \"{key}\" value is shown in the text colour"))
def _header_value_text_colour(ctx, key):
    screen = ctx["session"].app.screen
    widget = screen.query_one(_HEADER_FIELD_SELECTORS[key], Static)
    full_text = _rendered_text(widget)
    value = full_text.split(": ", 1)[1] if ": " in full_text else full_text
    style = _segment_style_for_substring(widget, 0, value)
    assert style is not None
    assert style.color.get_truecolor().hex.lower() == COLOURS["text"].lower()


@then("no workflow field is shown")
def _no_workflow_field(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-workflow") is None


@then(parsers.parse('it lands on the "{tab}" tab'))
def _lands_on_tab(ctx, tab):
    session = ctx["session"]
    tab_id = tab.lower()
    assert session.app.screen._active_tab == tab_id
    _assert_tab_strip_rendered(session, tab_id)


@then("it lands on the Description tab")
def _lands_on_description_tab(ctx):
    _lands_on_tab(ctx, "Description")


@then(parsers.parse('the "{tab}" tab becomes active'))
def _tab_becomes_active(ctx, tab):
    session = ctx["session"]
    tab_id = tab.lower()
    assert session.app.screen._active_tab == tab_id
    _assert_tab_strip_rendered(session, tab_id)


@then(parsers.parse('its tab strip shows exactly "{a}", "{b}", and "{c}", in that order'))
def _tab_strip_shows_three(ctx, a, b, c):
    tabs = _hub_tabs(ctx["session"])
    assert [label for _, label in tabs] == [a, b, c]


@then(parsers.parse('its tab strip shows exactly "{a}" and "{b}", in that order'))
def _tab_strip_shows_two(ctx, a, b):
    tabs = _hub_tabs(ctx["session"])
    assert [label for _, label in tabs] == [a, b]


@then(parsers.parse('no "{a}" tab and no "{b}" tab is shown'))
def _no_two_tabs_shown(ctx, a, b):
    screen = ctx["session"].app.screen
    for label in (a, b):
        assert len(screen.query("#hub-tab-%s" % label.lower())) == 0


@then(parsers.parse('no "{a}" tab, no "{b}" tab, and no "{c}" tab is shown'))
def _no_three_tabs_shown(ctx, a, b, c):
    screen = ctx["session"].app.screen
    for label in (a, b, c):
        assert len(screen.query("#hub-tab-%s" % label.lower())) == 0


@then("the backlog is shown in place of the hub")
def _backlog_shown_in_place_of_hub(ctx):
    from lightcycle.adapters.tui.app import BacklogView

    session = ctx["session"]
    assert not isinstance(session.app.screen, NodeHubScreen)
    assert session.app.query_one(BacklogView).display


@then("the priority list is shown in place of the hub")
def _priority_shown_in_place_of_hub(ctx):
    session = ctx["session"]
    assert not isinstance(session.app.screen, NodeHubScreen)
    assert session.app._view == "priority"


@then("the escalation reason names the specific blocking item")
def _escalation_names_blocking_item(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.display
    assert ctx["blocker_id"] in _rendered_panel_text(panel)


@then("the escalation reason names what's being asked of the operator")
def _escalation_names_ask(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.display
    assert "Resolve the merge conflict manually" in _rendered_panel_text(panel)


@then("no escalation reason is shown")
def _no_escalation_reason(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert not panel.display


@then(parsers.parse('the escalation panel shows a bold amber tag reading "{tag}" on its own line'))
def _escalation_tag_bold_amber(ctx, tag):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.display
    assert _rendered_line_text(panel, 0).strip() == tag
    style = _segment_style_for_substring(panel, 0, tag)
    assert style is not None
    assert style.bold
    assert style.color.get_truecolor().hex.lower() == COLOURS["amber"].lower()
    assert panel.size.height == 2


@then(parsers.parse('the escalation panel shows no "{tag}" tag and no second line'))
def _escalation_no_tag_one_line(ctx, tag):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.display
    assert tag not in _rendered_panel_text(panel)
    assert panel.size.height == 1


@then("the escalation panel shows no resume command")
def _escalation_no_resume_command(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.display
    assert "resume" not in _rendered_panel_text(panel).lower()


@then("the escalation panel has no third line")
def _escalation_no_third_line(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.size.height == 2


@then("the escalation panel's third line names the recorded reason")
def _escalation_reason_third_line(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.display
    assert "CI reported a real conflict" in _rendered_line_text(panel, 2)


@then("the reason is shown on a second line below the tag, in the text colour")
def _escalation_reason_second_line(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    text_colour = COLOURS["text"].lower()
    cyan = COLOURS["cyan"].lower()
    found_text_colour = False
    for segment in panel.render_line(1):
        if not segment.text.strip():
            continue
        colour = segment.style.color.get_truecolor().hex.lower()
        assert colour in (text_colour, cyan)
        if colour == text_colour:
            found_text_colour = True
    assert found_text_colour


@then("the blocking item's id within the reason is coloured as a link, in the cyan colour")
def _escalation_link_cyan(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    style = _segment_style_for_substring(panel, 0, ctx["blocker_id"])
    assert style is not None
    assert style.color.get_truecolor().hex.lower() == COLOURS["cyan"].lower()


@then("the escalation panel shows the reason's final words")
def _escalation_shows_final_words(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    text = _rendered_panel_text(panel)
    assert "pass verdict" in text


@then("the escalation panel shows no truncation ellipsis")
def _escalation_shows_no_ellipsis(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert "…" not in _rendered_panel_text(panel)


@then("the escalation panel is capped at the configured line count")
def _escalation_capped_line_count(ctx):
    from lightcycle.adapters.tui.hub import ESCALATION_REASON_LINE_CAP

    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.size.height == ESCALATION_REASON_LINE_CAP + 1


@then("the escalation panel's last line ends with an ellipsis")
def _escalation_last_line_ellipsis(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    last_line = _rendered_line_text(panel, panel.size.height - 1)
    assert last_line.rstrip().endswith("…")


@then("text past the cut point does not appear anywhere in the escalation panel")
def _escalation_cut_text_absent(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert "green" not in _rendered_panel_text(panel)


@then("the escalation panel's rendered lines match the new width, not the original")
def _escalation_reflowed_on_resize(ctx):
    screen = ctx["session"].app.screen
    panel = screen.query_one(EscalationPanel)
    assert panel.size.height != ctx["pre_resize_height"]
    assert _rendered_line_text(panel, 2) != ctx["pre_resize_line_2"]


@then("the blocking item's own hub opens")
def _blocking_item_hub_opens(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["blocker_id"]


@then("the blocking item's own hub opens, landing on the Description tab")
def _blocking_item_hub_opens_landing_description(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["blocker_id"]
    assert screen._active_tab == "description"
    _assert_tab_strip_rendered(ctx["session"], "description")


@then("it is not redirected into its running step")
def _not_redirected_into_running_step(ctx):
    screen = ctx["session"].app.screen
    assert screen._node_id == ctx["blocker_id"]


@then("nothing happens, since there is no blocker to jump to")
def _b_no_op(ctx):
    session = ctx["session"]
    assert len(session.app.screen_stack) == 2
    assert session.app.screen._node_id == ctx["item_id"]


@then("the hierarchy table has focus, not the escalation panel")
def _hierarchy_table_focused(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen.focused, HierarchyPagingTable)
    assert not isinstance(screen.focused, EscalationPanel)


@then("the description pane has focus, not the escalation panel")
def _description_pane_focused(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen.focused, DescriptionPane)
    assert not isinstance(screen.focused, EscalationPanel)


@then("the selection has moved to the next node")
def _selection_moved_to_next(ctx):
    table = ctx["session"].app.screen.query_one(HierarchyPagingTable)
    assert table.cursor_row == 1


@then("that step's own hub opens, not the blocking item's")
def _steps_own_hub_opens(ctx):
    screen = ctx["session"].app.screen
    assert screen._node_id == ctx["step_id"]
    assert screen._node_id != ctx["blocker_id"]


@then("the screen stack still has depth 2, unchanged by the confirm")
def _stack_depth_still_2(ctx):
    assert len(ctx["session"].app.screen_stack) == 2


@then("the screen stack still has depth 2, unchanged by the keypress")
def _stack_depth_still_2_keypress(ctx):
    assert len(ctx["session"].app.screen_stack) == 2


@then("the item's own hub opens, on top of the step's, landing on the Description tab")
def _item_hub_opens_on_top_of_step(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["item_id"]
    assert screen._active_tab == "description"
    assert len(ctx["session"].app.screen_stack) == 3
    _assert_tab_strip_rendered(ctx["session"], "description")


@then("the step's own hub reappears")
def _step_hub_reappears(ctx):
    screen = ctx["session"].app.screen
    assert screen is ctx["original_screen"]
    assert screen._node_id == ctx["step_id"]


@then("the original blocked item's hub reappears, at the tab I was on")
def _original_hub_reappears(ctx):
    screen = ctx["session"].app.screen
    assert screen is ctx["original_screen"]
    assert screen._active_tab == ctx["target_tab"]
    _assert_tab_strip_rendered(ctx["session"], ctx["target_tab"])


@then("the priority list reappears with that row still selected, at the same scroll position")
def _priority_reappears_same_row(ctx):
    table = ctx["session"].app.query_one(PriorityTable)
    ids = [row.key.value for row in table.ordered_rows]
    assert ids[table.cursor_row] == ctx["cursor_id"]


@then("the priority list's scroll position is unaffected by anything done inside the hub")
def _priority_list_scroll_unaffected(ctx):
    ctx["session"].press("escape")
    table = ctx["session"].app.query_one(PriorityTable)
    assert not isinstance(ctx["session"].app.screen, NodeHubScreen)
    assert table.cursor_row == 0


@then("its hub opens, landing on the Description tab")
def _hub_opens_landing_description(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._active_tab == "description"
    _assert_tab_strip_rendered(ctx["session"], "description")


@then("the hierarchy shows only that item, with no step children")
def _hierarchy_shows_only_item(ctx):
    screen = ctx["session"].app.screen
    table = screen.query_one(HierarchyPagingTable)
    assert [row.key.value for row in table.ordered_rows] == [ctx["item_id"]]


@then("the backlog reappears at the same scroll/selection position")
def _backlog_reappears_same_position(ctx):
    table = ctx["session"].app.query_one(BacklogTable)
    ids = [row.key.value for row in table.ordered_rows]
    assert ids[table.cursor_row] == ctx["cursor_id"]


@then("the header and the hierarchy show the step as queued, not active")
def _reclaimed_shows_queued(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-role") is not None
    assert "agent" in _text(screen, "#hub-role")
    assert _text(screen, "#hub-elapsed") is None

    if screen._active_tab != "hierarchy":
        ctx["session"].press("]")

    table = screen.query_one(HierarchyPagingTable)
    step_id = ctx["step_id"]
    queued_glyph = STATE_GLYPHS["queued"]
    active_glyph = STATE_GLYPHS["active"]
    icon_text = _rendered_cell_text(table, step_id, "icon")
    assert queued_glyph.glyph in icon_text
    assert active_glyph.glyph not in icon_text
    style = _rendered_icon_style(table, step_id, queued_glyph.glyph)
    assert style.color.get_truecolor().hex.lower() == COLOURS[queued_glyph.colour].lower()


@then("it shows an empty state placeholder")
def _empty_state_placeholder(ctx):
    screen = ctx["session"].app.screen
    selector = "#hub-log-empty" if screen._active_tab == "log" else "#hub-artifacts-empty"
    widget = screen.query_one(selector, Static)
    assert widget.display
    lines = [
        "".join(seg.text for seg in widget.render_line(i)) for i in range(widget.size.height)
    ]
    assert "".join(lines).strip() != ""


@when("I look at it")
def _look_at_it(ctx):
    pass


def test_hub_footer_shortcuts_include_open_blocker():
    store = FakeStore()
    item = store.create_item("an item", "a description")
    store.create_step("write code", step="write-code", role="agent", parent=item)
    store.claim_ready("agent")
    session = launch(make_test_container(store=store))
    try:
        session.run(
            lambda: session.app.push_screen(
                NodeHubScreen(session.app.container, item, session.app._now)
            )
        )
        session.pause()
        assert session.app.screen.query_one(ShortcutBar).shortcuts == HUB_SHORTCUTS
        assert ("b", "open blocker") in HUB_SHORTCUTS
    finally:
        session.close()
