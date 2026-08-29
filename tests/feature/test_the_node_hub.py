import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.app import BacklogTable, PriorityTable
from lightcycle.adapters.tui.design_system import COLOURS, STATE_GLYPHS
from lightcycle.adapters.tui.hub import EscalationPanel, HierarchyPagingTable, HubTabStrip, NodeHubScreen
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-node-hub.feature")


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


_HUB_TABS = (
    ("description", "Description"), ("hierarchy", "Hierarchy"), ("log", "Log"),
    ("artifacts", "Artifacts"),
)


def _assert_tab_strip_rendered(session, active_tab):
    for tab_id, label in _HUB_TABS:
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

    xs = [
        session.app.screen.query_one("#hub-tab-%s" % tab_id, Static).region.x
        for tab_id, _ in _HUB_TABS
    ]
    assert xs == sorted(xs), "tabs not rendered left to right as %r; x positions were %r" % (
        [label for _, label in _HUB_TABS], xs
    )


def _launch(ctx, store):
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    return ctx["session"]


def _open_with(ctx, key):
    ctx["session"].press(key)


@given("the priority list is showing with an item")
def _priority_with_item(ctx):
    store = FakeStore()
    item = store.create_item("an item")
    step = store.create_step("write code", step="write-code", role="write-code", parent=item)
    store.claim_ready("write-code")
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store)


@given("an item with a project, a theme, and a workflow")
def _item_full_identity(ctx):
    store = FakeStore()
    theme = store.create_theme("A theme", project="org/repo")
    item = store.create_item("Full item", theme=theme, workflow="lightcycle/spec-driven@abc123")
    store.add_artifact(item, "repo", "org/repo")
    store.create_step("write code", step="write-code", role="write-code", parent=item)
    ctx["item_id"] = item
    ctx["theme_id"] = theme
    _launch(ctx, store)


@given("an item with no theme")
def _item_no_theme(ctx):
    store = FakeStore()
    item = store.create_item("Themeless item")
    store.create_step("write code", step="write-code", role="write-code", parent=item)
    ctx["item_id"] = item
    _launch(ctx, store)


@given("an item with no workflow")
def _item_no_workflow(ctx):
    store = FakeStore()
    item = store.create_item("No workflow item")
    store.create_step("write code", step="write-code", role="write-code", parent=item)
    ctx["item_id"] = item
    _launch(ctx, store)


@given(parsers.parse('an item at step "{step}"'))
def _item_at_step(ctx, step):
    store = FakeStore()
    item = store.create_item("Item")
    store.create_step("s", step=step, role="write-code", parent=item)
    ctx["item_id"] = item
    _launch(ctx, store)


@given(parsers.parse('an item at step "{step}" performed by the role "{role}"'))
def _item_at_step_with_role(ctx, step, role):
    store = FakeStore()
    item = store.create_item("Item")
    store.create_step("s", step=step, role=role, parent=item)
    ctx["item_id"] = item
    _launch(ctx, store)


@given(parsers.parse('an active item at step "{step}" claimed {minutes:d} minutes ago'))
def _active_item_claimed_minutes_ago(ctx, step, minutes):
    import datetime

    now = datetime.datetime(2026, 1, 1, 12, 0, 0)
    claimed_at = now - datetime.timedelta(minutes=minutes)

    store = FakeStore(now=lambda: claimed_at.isoformat())
    item = store.create_item("Item")
    store.create_step("s", step=step, role="write-code", parent=item)
    store.claim_ready("write-code")

    ctx["item_id"] = item
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store), now=lambda: now)


@given("an item at a human step, with no worker")
def _item_human_step_no_worker(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    store.create_step("await-merge", step="await-merge", role="human", parent=item)
    ctx["item_id"] = item
    _launch(ctx, store)


@given("a step is selected, rather than an item or theme")
def _step_selected(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("write code", step="write-code", role="write-code", parent=item)
    store.claim_ready("write-code")
    ctx["step_id"] = step
    session = _launch(ctx, store)
    session.press("enter")
    screen = session.app.screen
    session.run(lambda: screen.open_at(step))
    session.pause()


@given("a theme with 4 items underneath")
def _theme_with_4_items(ctx):
    store = FakeStore()
    theme = store.create_theme("Theme")
    for i in range(4):
        store.create_item("Item %d" % i, theme=theme)
    ctx["node_id"] = theme
    _launch(ctx, store)


@given("a theme whose items belong to different projects")
def _theme_items_different_projects(ctx):
    store = FakeStore()
    theme = store.create_theme("Theme")
    first = store.create_item("First", theme=theme)
    store.add_artifact(first, "repo", "org/repo-a")
    second = store.create_item("Second", theme=theme)
    store.add_artifact(second, "repo", "org/repo-b")
    ctx["node_id"] = theme
    _launch(ctx, store)


@given(parsers.parse('a node with the status "{status}"'))
def _node_with_status(ctx, status):
    store = FakeStore()
    if status == "active":
        item = store.create_item("Item")
        store.create_step("s", step="build", role="coder", parent=item)
        store.claim_ready("coder")
        node_id = item
    elif status == "needs-attention on a human step":
        item = store.create_item("Item")
        store.create_step("s", step="await-merge", role="human", parent=item)
        node_id = item
    elif status == "blocked on another item's completion":
        blocker = store.create_item("Blocker")
        item = store.create_item("Item")
        store.dep_add(item, blocker)
        node_id = item
    elif status == "queued, not yet run":
        item = store.create_item("Item")
        store.create_step("s", step="build", role="coder", parent=item)
        node_id = item
    elif status == "done":
        item = store.create_item("Item")
        step = store.create_step("s", step="build", role="coder", parent=item)
        store.close(step, "done")
        node_id = item
    elif status == "a theme":
        node_id = store.create_theme("Theme")
    else:
        raise AssertionError("unhandled status %r" % status)
    ctx["node_id"] = node_id
    _launch(ctx, store)


@given("a node's hub is open, on the Log tab")
def _hub_open_on_log_tab(ctx):
    _open_hub_on_tab(ctx, "log")


@given("a node's hub is open, on the Artifacts tab")
def _hub_open_on_artifacts_tab(ctx):
    _open_hub_on_tab(ctx, "artifacts")


def _open_hub_on_tab(ctx, tab):
    store = FakeStore()
    item = store.create_item("Item")
    store.create_step("s", step="build", role="coder", parent=item)
    session = _launch(ctx, store)
    session.press("enter")
    screen = session.app.screen
    screen._active_tab = tab
    screen.query_one(HubTabStrip).set_active(screen._active_tab)
    screen._apply_tab_visibility()
    session.pause()


@given(parsers.parse('a node\'s hub is open, on the "{tab}" tab'))
def _hub_open_on_tab(ctx, tab):
    store = FakeStore()
    item = store.create_item("Item")
    store.create_step("s", step="build", role="coder", parent=item)
    session = _launch(ctx, store)
    session.press("enter")
    screen = session.app.screen
    screen._active_tab = tab.lower()
    screen.query_one(HubTabStrip).set_active(screen._active_tab)
    screen._apply_tab_visibility()
    session.pause()


@given("the backlog is showing with a todo item")
def _backlog_todo_item(ctx):
    store = FakeStore()
    item = store.create_item("Todo item")
    ctx["item_id"] = item
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    ctx["session"].press("tab")


@given("an item blocked on another item's completion")
def _item_blocked_on_dependency(ctx):
    store = FakeStore()
    blocker = store.create_item("Blocker item")
    item = store.create_item("Blocked item")
    store.dep_add(item, blocker)
    ctx["item_id"] = item
    ctx["node_id"] = item
    ctx["blocker_id"] = blocker
    _launch(ctx, store)


@given("an item whose current step is escalated, needing rework")
def _item_escalated_rework(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("write code", step="write-code", role="write-code", parent=item)
    store.update_metadata(step, {"needs": "Resolve the merge conflict manually"})
    store.route_to_human(step, "BLOCKED: Resolve the merge conflict manually")
    ctx["item_id"] = item
    _launch(ctx, store)


@given(parsers.parse('an item that is "{status}"'))
def _item_that_is(ctx, status):
    store = FakeStore()
    item = store.create_item("Item")
    if status == "active":
        store.create_step("s", step="build", role="coder", parent=item)
        store.claim_ready("coder")
    elif status == "queued":
        store.create_step("s", step="build", role="coder", parent=item)
    else:
        raise AssertionError("unhandled status %r" % status)
    ctx["item_id"] = item
    _launch(ctx, store)


@given("an item's hub is open, showing an escalation reason that names a blocking item")
def _hub_open_with_escalation(ctx):
    store = FakeStore()
    blocker = store.create_item("Blocker item")
    item = store.create_item("Blocked item")
    store.dep_add(item, blocker)
    ctx["blocker_id"] = blocker
    session = _launch(ctx, store)
    session.run(
        lambda: session.app.push_screen(NodeHubScreen(session.app.container, item, session.app._now))
    )
    session.pause()


@given(
    "I jumped from a blocked item's hub to its blocking item's hub, from a particular tab"
)
def _jumped_to_blocking_item(ctx):
    store = FakeStore()
    blocker = store.create_item("Blocker item")
    store.create_step("s", step="build", role="coder", parent=blocker)
    item = store.create_item("Blocked item")
    store.dep_add(item, blocker)
    session = _launch(ctx, store)
    session.press("enter")
    screen = session.app.screen
    screen._active_tab = "artifacts"
    screen.query_one(HubTabStrip).set_active(screen._active_tab)
    screen._apply_tab_visibility()
    ctx["original_screen"] = screen
    session.run(lambda: screen.open_at(blocker))
    session.pause()


@given("I opened an item's hub from a specific row in the priority list")
def _opened_from_priority_row(ctx):
    store = FakeStore()
    other = store.create_item("Other")
    store.create_step("other", step="build", role="coder", parent=other)
    item = store.create_item("Target")
    store.create_step("s", step="build", role="coder", parent=item)
    ctx["item_id"] = item
    session = _launch(ctx, store)
    table = session.app.query_one(PriorityTable)
    table.move_cursor(row=list(table.rows).index(item) if item in table.rows else 0)
    ids = [row.key.value for row in table.ordered_rows]
    ctx["cursor_id"] = ids[table.cursor_row]
    session.press("enter")


@given("I opened an item's hub and scrolled or navigated within it")
def _opened_and_navigated(ctx):
    store = FakeStore()
    item = store.create_item("Target")
    theme = store.create_theme("Theme")
    store.edit_node(item, parent=theme)
    store.create_step("s", step="build", role="coder", parent=item)
    session = _launch(ctx, store)
    session.press("enter")
    screen = session.app.screen
    screen._active_tab = "hierarchy"
    screen._apply_tab_visibility()
    session.press("down")


@given("the backlog is shown with a todo item")
def _backlog_shown_with_todo(ctx):
    store = FakeStore()
    item = store.create_item("Todo item")
    ctx["item_id"] = item
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    ctx["session"].press("tab")


@given("I opened a backlog item's hub from a specific row in the backlog")
def _opened_backlog_hub(ctx):
    store = FakeStore()
    store.create_item("Other todo")
    item = store.create_item("Target todo")
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
    "and was reclaimed to ready"
)
def _step_reclaimed(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    store.claim_ready("write-code")
    store.reclaim(step)
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store)


@when(parsers.parse("{key} is pressed"))
def _key_pressed(ctx, key):
    keymap = {
        "Enter": "enter", "→": "right", "Esc": "escape", "←": "left",
        "Tab": "tab", "]": "]", "[": "[",
    }
    ctx["session"].press(keymap.get(key, key))


@when("I select that item's row")
def _select_item_row(ctx):
    table = ctx["session"].app.query_one(PriorityTable)
    ids = [row.key.value for row in table.ordered_rows]
    table.move_cursor(row=ids.index(ctx["step_id"]))


@when(parsers.parse("I open it with Enter or {arrow}"))
def _open_it(ctx, arrow):
    if "node_id" in ctx:
        session = ctx["session"]
        session.run(
            lambda: session.app.push_screen(
                NodeHubScreen(session.app.container, ctx["node_id"], session.app._now)
            )
        )
        session.pause()
    else:
        _open_with(ctx, "enter")


@when(parsers.parse('the "{tab}" tab is active'))
def _tab_is_active(ctx, tab):
    screen = ctx["session"].app.screen
    screen._active_tab = tab.lower()
    screen.query_one(HubTabStrip).set_active(screen._active_tab)
    screen._apply_tab_visibility()
    ctx["session"].pause()


@when("I select the blocking item and press Enter or →")
def _select_blocking_and_open(ctx):
    ctx["session"].press("enter")


@when("I close it with Esc or ←")
def _close_with_esc(ctx):
    ctx["session"].press("escape")


@then("the item's hub opens, replacing the list on screen")
def _hub_opens_replacing_list(ctx):
    assert isinstance(ctx["session"].app.screen, NodeHubScreen)


@then("the header shows its id, its title, its project, its theme, and its workflow")
def _header_shows_identity(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-id") == ctx["item_id"]
    assert _text(screen, "#hub-title") == "Full item"
    assert _text(screen, "#hub-project") is not None
    assert "repo" in _text(screen, "#hub-project")
    theme_text = _text(screen, "#hub-theme")
    assert theme_text is not None and ctx["theme_id"] in theme_text
    assert _text(screen, "#hub-workflow") is not None


@then("no theme line is shown in the header")
def _no_theme_line(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-theme") is None


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
    assert _text(screen, "#hub-role") == "ROLE: write-code"
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


@then(parsers.parse('the header shows "{text}"'))
def _header_shows_text(ctx, text):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-item-count") == text


@then("no project, theme, or workflow line is shown in the header")
def _no_project_theme_workflow(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-project") is None
    assert _text(screen, "#hub-theme") is None
    assert _text(screen, "#hub-workflow") is None


@then("no project line is shown in the header")
def _no_project_line(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-project") is None


@then("no theme or workflow fields are shown")
def _no_theme_workflow(ctx):
    screen = ctx["session"].app.screen
    assert _text(screen, "#hub-theme") is None
    assert _text(screen, "#hub-workflow") is None


@then(parsers.parse('it lands on the "{tab}" tab'))
def _lands_on_tab(ctx, tab):
    session = ctx["session"]
    tab_id = tab.lower()
    assert session.app.screen._active_tab == tab_id
    _assert_tab_strip_rendered(session, tab_id)


@then(parsers.parse('the "{tab}" tab becomes active'))
def _tab_becomes_active(ctx, tab):
    session = ctx["session"]
    tab_id = tab.lower()
    assert session.app.screen._active_tab == tab_id
    _assert_tab_strip_rendered(session, tab_id)


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
    style = _segment_style_for_substring(panel, 1, ctx["blocker_id"])
    assert style is not None
    assert style.color.get_truecolor().hex.lower() == COLOURS["cyan"].lower()


@then("the blocking item's own hub opens")
def _blocking_item_hub_opens(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["blocker_id"]


@then("the original blocked item's hub reappears, at the tab I was on")
def _original_hub_reappears(ctx):
    ctx["session"].press("escape")
    screen = ctx["session"].app.screen
    assert screen is ctx["original_screen"]
    assert screen._active_tab == "artifacts"
    _assert_tab_strip_rendered(ctx["session"], "artifacts")


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


@then("its hub opens, landing on the Hierarchy tab")
def _hub_opens_landing_hierarchy(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._active_tab == "hierarchy"
    _assert_tab_strip_rendered(ctx["session"], "hierarchy")


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
    assert "write-code" in _text(screen, "#hub-role")
    assert _text(screen, "#hub-elapsed") is None

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
