import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.design_system import (
    ACTIVE_GLYPH_REST_INDEX,
    COLOURS,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    STATE_GLYPHS,
)
from lightcycle.adapters.tui.hub import HierarchyPagingTable, NodeHubScreen
from lightcycle.adapters.tui.row_grid import (
    FLEXIBLE_MINIMUM, GLYPH_WIDTHS, atomic_column_width, scrollbar_reservation_width,
)
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-hierarchy-tab.feature")


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _launch(ctx, store, node_id, size=None):
    ctx["store"] = store
    session = launch(make_test_container(store=store, fs=ctx.get("fs")), size=size)
    ctx["session"] = session
    session.run(
        lambda: session.app.push_screen(NodeHubScreen(session.app.container, node_id, session.app._now))
    )
    session.pause()
    screen = session.app.screen
    screen._active_tab = "hierarchy"
    session.run(screen._apply_tab_visibility)
    if screen._active_glyph_timer is not None:
        screen._active_glyph_timer.stop()
        screen._active_glyph_timer = None
    screen._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX
    screen._focus_active_tab()
    session.pause()
    ctx["hub_screen"] = screen
    ctx["start_row"] = _table(ctx).cursor_row
    return session


def _table(ctx):
    return ctx["session"].app.screen.query_one(HierarchyPagingTable)


def _row_ids(ctx):
    return [row.key.value for row in _table(ctx).ordered_rows]


def _rendered_icon_style(ctx, row_id, glyph):
    table = _table(ctx)
    strip = table.render_line(table.get_row_index(row_id))
    for segment in strip:
        if segment.text.strip() == glyph:
            return segment.style
    return None


def _rendered_cell_text(ctx, row_id, column_key):
    table = _table(ctx)
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


def _rendered_text(widget):
    strip = widget.render_line(0)
    return "".join(segment.text for segment in strip)


def _painted_bg_colours(ctx):
    table = _table(ctx)
    region = table.region
    session = ctx["session"]
    strips = session.run(lambda: session.app.screen._compositor.render_strips())
    colours = []
    for y in range(region.y, region.y + region.height):
        if y >= len(strips):
            continue
        for segment in strips[y].crop(region.x, region.x + region.width):
            bg = segment.style.bgcolor if segment.style else None
            if bg is not None:
                colours.append(bg.get_truecolor().hex.lower())
    return colours


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


def _row_lines(ctx, row_id):
    table = _table(ctx)
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


@given("a node with an artifact whose internal flag is false")
def _node_with_visible_artifact(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    store.add_artifact(item, "repo", "org/repo")
    ctx["node_id"] = item
    _launch(ctx, store, item)


@given("a node with only internal-flagged artifacts")
def _node_with_only_internal_artifacts(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    store.add_artifact(item, "reflection", "text", internal=True)
    ctx["node_id"] = item
    _launch(ctx, store, item)


@given("a node with no artifacts")
def _node_with_no_artifacts(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    ctx["node_id"] = item
    _launch(ctx, store, item)


@given("a node showing a content indicator")
def _node_showing_content_indicator(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    store.add_artifact(item, "repo", "org/repo")
    ctx["node_id"] = item
    _launch(ctx, store, item)


@given("an item under a theme")
def _item_under_theme(ctx):
    store = FakeStore()
    theme = store.create_theme("Theme")
    item = store.create_item("Item", theme=theme)
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    ctx["theme_id"] = theme
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["node_id"] = item
    _launch(ctx, store, item)


@given("a themeless item")
def _themeless_item(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["node_id"] = item
    _launch(ctx, store, item)


@given("the hierarchy is showing a theme, one of its items, and one of that item's steps")
def _hierarchy_theme_item_step(ctx):
    store = FakeStore()
    theme = store.create_theme("Theme")
    item = store.create_item("Item", theme=theme)
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    ctx["theme_id"] = theme
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store, item)


@given("a node in the hierarchy")
def _a_node_in_the_hierarchy(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    store.claim_ready("write-code")
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store, item)


@given("the hierarchy tab is open")
def _hierarchy_tab_is_open(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="build", role="coder", parent=item)
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store, item)


@given(parsers.parse("a {node_type} whose current step is active, highlighted in the hierarchy"))
def _type_with_active_current_step_highlighted(ctx, node_type):
    store = FakeStore()
    if node_type == "item":
        node_id = store.create_item("Item")
        step = store.create_step("s", step="build", role="coder", parent=node_id)
    elif node_type == "theme":
        node_id = store.create_theme("Theme")
        item = store.create_item("Item", theme=node_id)
        step = store.create_step("s", step="build", role="coder", parent=item)
        ctx["item_id"] = item
    else:
        raise AssertionError("unhandled node type %r" % node_type)
    store.claim_ready("coder")
    ctx["node_id"] = node_id
    ctx["step_id"] = step
    ctx["expected_log_target_id"] = step if node_type == "item" else node_id
    _launch(ctx, store, node_id)


@given(parsers.parse("a {node_type} whose every step is done, highlighted in the hierarchy"))
def _type_with_all_steps_done_highlighted(ctx, node_type):
    store = FakeStore()
    if node_type == "item":
        node_id = store.create_item("Item")
        first = store.create_step("s1", step="build", role="coder", parent=node_id)
        last = store.create_step("s2", step="write-code", role="write-code", parent=node_id)
    elif node_type == "theme":
        node_id = store.create_theme("Theme")
        item = store.create_item("Item", theme=node_id)
        first = store.create_step("s1", step="build", role="coder", parent=item)
        last = store.create_step("s2", step="write-code", role="write-code", parent=item)
        ctx["item_id"] = item
    else:
        raise AssertionError("unhandled node type %r" % node_type)
    store.close(first, "done")
    store.close(last, "done")
    ctx["node_id"] = node_id
    ctx["last_step_id"] = last
    _launch(ctx, store, node_id)


@given("the hierarchy is open, showing a queued step")
def _hierarchy_open_queued_step(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="build", role="coder", parent=item)
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store, item)


@given("the hierarchy is open, showing an active step")
def _hierarchy_open_active_step(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="build", role="coder", parent=item)
    store.claim_ready("coder")
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store, item)


@given(parsers.parse('a step performed by the role "{role}"'))
def _step_performed_by_role(ctx, role):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step=role, role=role, parent=item)
    store.claim_ready(role)
    ctx["step_id"] = step
    _launch(ctx, store, item)


@given("a step whose stored title is the step name followed by a body")
def _step_title_is_step_name_and_body(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step(
        "implement-features: Deliver the operator-monitoring feature",
        step="implement-features", role="coder", parent=item,
    )
    ctx["step_id"] = step
    _launch(ctx, store, item)


@given(parsers.parse(
    'a step at stage "{stage}" whose workflow declares the display phrase "{phrase}" for that stage'
))
def _step_at_stage_with_display(ctx, stage, phrase):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step=stage, role="coder", parent=item)
    ctx["step_id"] = step
    ctx["fs"] = FakeFs(metas={
        "coder": {"model": "sonnet", "step": stage, "display": phrase},
    })
    _launch(ctx, store, item)


@given(parsers.parse('a step whose role is "{role}"'))
def _step_whose_role_is(ctx, role):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="await-merge", role=role, parent=item)
    ctx["step_id"] = step
    _launch(ctx, store, item)


@given(parsers.parse('a node in the hierarchy with id "{node_id}" ({id_source})'))
def _node_with_explicit_id(ctx, node_id, id_source):
    store = FakeStore()
    item = store.create_item("Item", id=node_id)
    ctx["node_id"] = item
    _launch(ctx, store, item)


@given('an item "LIGHTCYCLE-3.1" and its own step "LIGHTCYCLE-3.1.1" both shown in the hierarchy')
def _colliding_ids(ctx):
    store = FakeStore()
    item = store.create_item("Item", id="LIGHTCYCLE-3.1")
    step = store.create_step("Step", step="build", role="coder", parent=item, id="LIGHTCYCLE-3.1.1")
    ctx["item_id"] = item
    ctx["step_id"] = step
    _launch(ctx, store, item)


_HSTACK_TITLE = "A title long enough to need a continuation line for real"
_HIERARCHY_NUM_COLUMNS = 5


def _hierarchy_stack_terminal_width(mode, ids, roles, max_depth):
    glyph_total = GLYPH_WIDTHS["icon"] + GLYPH_WIDTHS["content"]
    atomic_values = {"id": ids, "role": roles}
    atomic_total = sum(max(1, atomic_column_width(v)) for v in atomic_values.values())
    first_line_width = glyph_total + atomic_total
    indent = glyph_total + max_depth
    floor_width = max(first_line_width, indent + FLEXIBLE_MINIMUM)
    breakpoint_width = first_line_width + FLEXIBLE_MINIMUM
    row_budget = floor_width if mode == "just wide enough to clear the floor" else breakpoint_width - 1
    return row_budget + 2 + 2 * _HIERARCHY_NUM_COLUMNS + scrollbar_reservation_width(HierarchyPagingTable)


@given(parsers.parse(
    "a hierarchy row at depth {depth:d} whose atomic and glyph columns leave less than the "
    "flexible minimum for the title, on a terminal {mode}"
))
def _row_leaves_less_than_flexible_minimum(ctx, depth, mode):
    store = FakeStore()
    if depth == 0:
        item = store.create_item(_HSTACK_TITLE, id="LC-30.100")
        ctx["item_id"] = item
        ctx["target_id"] = item
        width = _hierarchy_stack_terminal_width(mode, ["LC-30.100"], [], 0)
    else:
        theme = store.create_theme("Theme")
        item = store.create_item("Item", theme=theme, id="LC-30.100")
        step = store.create_step(
            "s", step=_HSTACK_TITLE, role="coder", parent=item, id="LC-30.100.100",
        )
        ctx["item_id"] = item
        ctx["target_id"] = step
        width = _hierarchy_stack_terminal_width(
            mode, [theme, "LC-30.100", "LC-30.100.100"], ["coder"], depth
        )
    ctx["target_depth"] = depth
    _launch(ctx, store, item, size=(width, 24))


@given("a step blocked on another item's completion")
def _step_blocked_on_dependency(ctx):
    store = FakeStore()
    blocker = store.create_step("blocker", step="build", role="coder")
    item = store.create_item("Item")
    step = store.create_step("s", step="build", role="coder", parent=item, deps=[blocker])
    ctx["step_id"] = step
    _launch(ctx, store, item)


def _build_long_store(n=30):
    store = FakeStore()
    theme = store.create_theme("Theme")
    item = store.create_item("Item", theme=theme)
    for i in range(n):
        store.create_step("s%d" % i, step="build", role="coder", parent=item)
    return store, theme, item


@given("the hierarchy has more rows than fit on one screen")
def _hierarchy_more_rows_than_fit(ctx):
    store, theme, item = _build_long_store()
    ctx["item_id"] = item
    _launch(ctx, store, item)


@given("the selection is not on the first node")
def _selection_not_on_first(ctx):
    ctx["session"].press("down")
    ctx["session"].press("down")
    ctx["start_row"] = _table(ctx).cursor_row


@given("the selection is on the last node in the hierarchy")
def _selection_on_last(ctx):
    store, theme, item = _build_long_store()
    ctx["item_id"] = item
    _launch(ctx, store, item)
    table = _table(ctx)
    table.move_cursor(row=table.row_count - 1)


@given("the selection is on the first node in the hierarchy")
def _selection_on_first(ctx):
    store, theme, item = _build_long_store()
    ctx["item_id"] = item
    _launch(ctx, store, item)
    table = _table(ctx)
    table.move_cursor(row=0)


@given("the hierarchy is longer than one screen")
def _hierarchy_longer_than_one_screen(ctx):
    store, theme, item = _build_long_store()
    ctx["item_id"] = item
    _launch(ctx, store, item)


@given(parsers.parse('a "{node_type}" is highlighted in the hierarchy'))
def _node_type_highlighted(ctx, node_type):
    store = FakeStore()
    theme = store.create_theme("Theme")
    item = store.create_item("Item", theme=theme)
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    ids = {"theme": theme, "item": item, "step": step}
    ctx["target_id"] = ids[node_type]
    _launch(ctx, store, item)
    table = _table(ctx)
    row_ids = _row_ids(ctx)
    table.move_cursor(row=row_ids.index(ids[node_type]))


@given("I opened a node from the Hierarchy tab")
def _opened_node_from_hierarchy(ctx):
    store = FakeStore()
    theme = store.create_theme("Theme")
    item = store.create_item("Item", theme=theme)
    other = store.create_item("Other", theme=theme)
    store.create_step("s", step="write-code", role="write-code", parent=other)
    ctx["item_id"] = item
    ctx["other_id"] = other
    _launch(ctx, store, item)
    table = _table(ctx)
    row_ids = _row_ids(ctx)
    table.move_cursor(row=row_ids.index(other))
    ctx["session"].press("enter")


@given("the hierarchy is scrolled past a node's parent item or theme")
def _hierarchy_scrolled_past_ancestor(ctx):
    store, theme, item = _build_long_store(40)
    ctx["item_id"] = item
    ctx["theme_id"] = theme
    _launch(ctx, store, item)


@given("an ancestor's row is pinned to the top because it scrolled out of view")
def _ancestor_pinned(ctx):
    store, theme, item = _build_long_store(40)
    ctx["item_id"] = item
    ctx["theme_id"] = theme
    _launch(ctx, store, item)
    for _ in range(30):
        ctx["session"].press("down")
    banner = ctx["hub_screen"].query_one("#pinned-ancestor", Static)
    assert banner.display


@given("a node is highlighted in the hierarchy, not yet opened")
def _node_highlighted_not_opened(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    store.add_artifact(item, "repo", "org/repo")
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    ctx["step_id"] = step
    _launch(ctx, store, item)
    table = _table(ctx)
    table.move_cursor(row=_row_ids(ctx).index(step))


@given("an active step is highlighted in the hierarchy")
def _active_step_highlighted(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    store.claim_ready("write-code")
    ctx["step_id"] = step
    _launch(ctx, store, item)
    table = _table(ctx)
    table.move_cursor(row=_row_ids(ctx).index(step))


@given("a done step is highlighted in the hierarchy")
def _done_step_highlighted(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    store.create_step("o", step="review-code", role="review-code", parent=item)
    store.close(step, "done")
    ctx["step_id"] = step
    _launch(ctx, store, item)
    table = _table(ctx)
    table.move_cursor(row=_row_ids(ctx).index(step))


@given("a human step is highlighted in the hierarchy")
def _human_step_highlighted(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="await-merge", role="human", parent=item)
    store.close(step, "done")
    ctx["step_id"] = step
    _launch(ctx, store, item)
    table = _table(ctx)
    table.move_cursor(row=_row_ids(ctx).index(step))


@given("a queued step is highlighted in the hierarchy")
def _queued_step_highlighted(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="build", role="coder", parent=item)
    ctx["step_id"] = step
    _launch(ctx, store, item)
    table = _table(ctx)
    table.move_cursor(row=_row_ids(ctx).index(step))


@given("the current node is a themeless root item")
def _current_node_themeless_root(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    ctx["item_id"] = item
    _launch(ctx, store, item)


@given("the current node is a step nested under an item under a theme")
def _current_node_nested_step(ctx):
    store = FakeStore()
    theme = store.create_theme("Theme")
    item = store.create_item("Item", theme=theme)
    step = store.create_step("s", step="write-code", role="write-code", parent=item)
    ctx["step_id"] = step
    _launch(ctx, store, step)


@given("an item with one completed step and one queued step after it")
def _item_one_done_one_queued(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    done_step = store.create_step("s1", step="build", role="coder", parent=item)
    queued_step = store.create_step("s2", step="write-code", role="write-code", parent=item)
    store.close(done_step, "done")
    ctx["item_id"] = item
    ctx["step_id"] = queued_step
    _launch(ctx, store, item)


@given("an item with 40 completed steps and one queued step after them")
def _item_forty_done_one_queued(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    for i in range(40):
        step = store.create_step("s%d" % i, step="build", role="coder", parent=item)
        store.close(step, "done")
    queued_step = store.create_step("s-last", step="write-code", role="write-code", parent=item)
    ctx["item_id"] = item
    ctx["step_id"] = queued_step
    _launch(ctx, store, item)


@given("an item whose every step is done")
def _item_every_step_done(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    for i in range(3):
        step = store.create_step("s%d" % i, step="build", role="coder", parent=item)
        store.close(step, "done")
    ctx["item_id"] = item
    _launch(ctx, store, item)


@when("it appears in the hierarchy")
def _it_appears(ctx):
    pass


@when("I open that node")
def _open_that_node(ctx):
    ctx["session"].press("enter")


@when(parsers.parse('I open the hierarchy from it or one of its steps'))
def _open_hierarchy_from_it(ctx):
    pass


@when("I look at each node")
def _look_at_each_node(ctx):
    pass


@when("it renders")
def _it_renders(ctx):
    pass


@when("that step is claimed and becomes active")
def _step_claimed_becomes_active(ctx):
    ctx["store"].claim_ready("coder")


@when("one poll interval elapses")
def _one_poll_interval(ctx):
    session = ctx["session"]
    session.run(session.app.screen.poll_refresh)
    session.pause()


@when("it renders in the hierarchy")
def _it_renders_in_hierarchy(ctx):
    pass


@when("they render")
def _they_render(ctx):
    pass


@when("Down is pressed")
def _down_pressed(ctx):
    ctx["session"].press("down")


@when("Up is pressed")
def _up_pressed(ctx):
    ctx["session"].press("up")


@when("Ctrl-D is pressed")
def _ctrl_d_pressed(ctx):
    ctx["session"].press("ctrl+d")


@when("Ctrl-U is pressed")
def _ctrl_u_pressed(ctx):
    ctx["session"].press("ctrl+u")


@when(parsers.parse("Enter or {arrow} is pressed"))
def _enter_or_arrow_pressed(ctx, arrow):
    ctx["session"].press("enter")


@when("Enter or → is pressed, without moving the selection")
def _enter_pressed_without_moving_selection(ctx):
    ctx["session"].press("enter")


@when("I close it with Esc or ←")
def _close_with_esc(ctx):
    ctx["session"].press("escape")


@when("that ancestor leaves the visible scroll area")
def _ancestor_leaves_view(ctx):
    for _ in range(30):
        ctx["session"].press("down")


@when("I scroll back up to where its actual row is")
def _scroll_back_to_ancestor(ctx):
    table = _table(ctx)
    banner = ctx["hub_screen"].query_one("#pinned-ancestor", Static)
    for _ in range(table.row_count):
        if not banner.display:
            break
        ctx["session"].press("up")


@when("a is pressed")
def _a_pressed(ctx):
    ctx["session"].press("a")


@when("l is pressed")
def _l_pressed(ctx):
    ctx["session"].press("l")


@when("I view the Hierarchy tab")
def _view_hierarchy_tab(ctx):
    pass


@then("it shows a content indicator")
def _shows_content_indicator(ctx):
    text = _rendered_cell_text(ctx, ctx["node_id"], "content")
    assert text.strip() != ""


@then("no content indicator is shown")
def _no_content_indicator(ctx):
    text = _rendered_cell_text(ctx, ctx["node_id"], "content")
    assert text.strip() == ""


@then("at least one artifact I can actually view is there")
def _artifact_viewable(ctx):
    store = ctx["store"]
    artifacts = store.item_artifacts(ctx["node_id"])
    assert any(not a.internal for a in artifacts)


@then("the theme is shown at the top, with all its items and their steps below")
def _theme_at_top(ctx):
    ids = _row_ids(ctx)
    assert ids[0] == ctx["theme_id"]
    assert ctx["item_id"] in ids
    assert ctx["step_id"] in ids
    assert ids.index(ctx["theme_id"]) < ids.index(ctx["item_id"]) < ids.index(ctx["step_id"])


@then("that item is shown as the root, with its steps below, and no blank or missing theme row")
def _item_is_root(ctx):
    ids = _row_ids(ctx)
    assert ids[0] == ctx["item_id"]
    assert ctx["step_id"] in ids
    assert None not in ids
    assert "" not in ids


@then("its depth - theme, item, or step - is visible by indentation")
def _depth_visible_by_indentation(ctx):
    theme_title = _rendered_cell_text(ctx, ctx["theme_id"], "title")
    item_title = _rendered_cell_text(ctx, ctx["item_id"], "title")
    step_title = _rendered_cell_text(ctx, ctx["step_id"], "title")
    theme_indent = len(theme_title) - len(theme_title.lstrip(" "))
    item_indent = len(item_title) - len(item_title.lstrip(" "))
    step_indent = len(step_title) - len(step_title.lstrip(" "))
    assert theme_indent < item_indent < step_indent


@then("its own real id is shown alongside its title")
def _own_real_id_shown(ctx):
    ids = _row_ids(ctx)
    assert ctx["item_id"] in ids


@then("its current state is shown using the same icon and colour as the priority list")
def _state_shown_same_icon(ctx):
    glyph = STATE_GLYPHS["active"]
    icon_text = _rendered_cell_text(ctx, ctx["item_id"], "icon")
    assert glyph.glyph in icon_text
    style = _rendered_icon_style(ctx, ctx["item_id"], glyph.glyph)
    assert style.color.get_truecolor().hex.lower() == COLOURS[glyph.colour].lower()


@then("the row area's background matches the same bg colour as the rest of the frame")
def _row_area_bg_matches_frame(ctx):
    colours = _painted_bg_colours(ctx)
    assert colours, "expected some painted cells in the hierarchy row area"
    bg = COLOURS["bg"].lower()
    selected = COLOURS["selected-bg"].lower()
    assert all(c in (bg, selected) for c in colours)
    assert bg in colours


@then("the step's row shows the active state, without a manual refresh")
def _step_row_shows_active(ctx):
    glyph = STATE_GLYPHS["active"]
    icon_text = _rendered_cell_text(ctx, ctx["step_id"], "icon")
    assert glyph.glyph in icon_text


@then("the step's icon rests on the black diamond")
def _icon_rests_on_black_diamond(ctx):
    icon_text = _rendered_cell_text(ctx, ctx["step_id"], "icon")
    assert "◆" in icon_text


@when("the active-glyph animation ticks four times")
def _tick_active_glyph_four_times(ctx):
    screen = ctx["hub_screen"]
    session = ctx["session"]
    frames = []
    for _ in range(4):
        session.run(screen._tick_active_glyph)
        frames.append(_rendered_cell_text(ctx, ctx["step_id"], "icon").strip())
    ctx["frames"] = frames


@then("the step's icon cycles through the diamond pulse frames and returns to the black diamond")
def _icon_cycles_through_pulse_frames(ctx):
    assert ctx["frames"] == ["◈", "◇", "◈", "◆"]


@then(parsers.parse('its role "{role}" is shown alongside its state'))
def _role_shown_alongside_state(ctx, role):
    role_text = _rendered_cell_text(ctx, ctx["step_id"], "role")
    assert role_text.strip() == role


@then(parsers.parse('"{role}" is shown as its role'))
def _role_shown_as(ctx, role):
    role_text = _rendered_cell_text(ctx, ctx["step_id"], "role")
    assert role_text.strip() == role


@then("the step's row label is exactly its step name, with no title body and no repetition of the role")
def _step_row_label_is_step_name(ctx):
    title_text = _rendered_cell_text(ctx, ctx["step_id"], "title").strip()
    role_text = _rendered_cell_text(ctx, ctx["step_id"], "role").strip()
    assert title_text == "implement-features"
    assert role_text == "coder"
    assert "Deliver the operator-monitoring feature" not in title_text


@then(parsers.parse('the step\'s row label reads "{phrase}", not "{stage}"'))
def _step_row_label_reads_phrase(ctx, phrase, stage):
    title_text = _rendered_cell_text(ctx, ctx["step_id"], "title").strip()
    assert title_text == phrase
    assert stage not in title_text


@then("its id is shown in full, on one line")
def _id_shown_in_full_one_line(ctx):
    node_id = ctx["node_id"]
    lines = _row_lines(ctx, node_id)
    assert len(lines) == 1
    text = _rendered_cell_text(ctx, node_id, "id")
    assert text.strip() == node_id


@then("both ids are shown in full")
def _both_ids_shown_in_full(ctx):
    for node_id in (ctx["item_id"], ctx["step_id"]):
        text = _rendered_cell_text(ctx, node_id, "id")
        assert text.strip() == node_id


@then("the item's row and the step's row are distinguishable from each other")
def _rows_distinguishable(ctx):
    item_text = _rendered_cell_text(ctx, ctx["item_id"], "id").strip()
    step_text = _rendered_cell_text(ctx, ctx["step_id"], "id").strip()
    assert item_text != step_text


@then(parsers.parse('its role "{role}" is shown in full, on one line'))
def _role_shown_in_full_one_line(ctx, role):
    step_id = ctx["step_id"]
    lines = _row_lines(ctx, step_id)
    assert len(lines) == 1
    text = _rendered_cell_text(ctx, step_id, "role")
    assert text.strip() == role


def _hierarchy_stacked_cell_text(table, strip):
    pad = table.cell_padding
    column = table.ordered_columns[0]
    start = pad
    end = start + column.width
    return "".join(segment.text for segment in strip.crop(start, end))


@then(
    "the icon, content indicator, id and role remain on the row's first line, each padded to "
    "its atomic width, with the role right-aligned"
)
def _first_line_role_right_aligned(ctx):
    table = _table(ctx)
    lines = _row_lines(ctx, ctx["target_id"])
    assert len(lines) > 1
    content = _hierarchy_stacked_cell_text(table, lines[0])
    rest = content[GLYPH_WIDTHS["icon"] + GLYPH_WIDTHS["content"]:]
    assert rest.startswith(ctx["target_id"])
    if ctx["target_depth"] != 0:
        assert content.rstrip().endswith("coder")


@then(parsers.parse(
    "the title appears on a continuation line indented {indent:d} characters plus the row's "
    "own depth indent of {depth:d}"
))
def _title_continuation_indented(ctx, indent, depth):
    table = _table(ctx)
    lines = _row_lines(ctx, ctx["target_id"])
    assert len(lines) > 1
    total_indent = indent + depth
    words = []
    for line in lines[1:]:
        text = _hierarchy_stacked_cell_text(table, line)
        stripped = text.rstrip()
        leading = len(stripped) - len(stripped.lstrip(" "))
        assert leading == total_indent
        words.extend(stripped.strip().split())
    assert words == _HSTACK_TITLE.split()
    ctx["_continuation_words"] = words


@then("no fragment of the title's prose is split mid-word")
def _no_mid_word_split_hierarchy(ctx):
    assert ctx["_continuation_words"] == _HSTACK_TITLE.split()


@then("a dependency indicator is shown alongside its state")
def _dependency_indicator_shown(ctx):
    icon_text = _rendered_cell_text(ctx, ctx["step_id"], "icon")
    assert DEPENDENCY_BLOCKED_EXTRA_GLYPH.glyph in icon_text


@then("that state is the queued glyph, not the needs-attention glyph")
def _indicator_distinct(ctx):
    icon_text = _rendered_cell_text(ctx, ctx["step_id"], "icon")
    assert STATE_GLYPHS["queued"].glyph in icon_text
    assert STATE_GLYPHS["needs-attention"].glyph not in icon_text


@then("the selection has moved to the next node, scrolling as needed")
def _selection_moved_next(ctx):
    table = _table(ctx)
    assert table.cursor_row == ctx["start_row"] + 1


@then("the selection has moved to the previous node")
def _selection_moved_previous(ctx):
    table = _table(ctx)
    assert table.cursor_row == ctx["start_row"] - 1


@then("the selection has not moved past the last node")
def _selection_not_past_last(ctx):
    table = _table(ctx)
    assert table.cursor_row == table.row_count - 1


@then("the selection has not moved past the first node")
def _selection_not_past_first(ctx):
    table = _table(ctx)
    assert table.cursor_row == 0


@then("the view has jumped forward by roughly a full screen")
def _view_jumped_forward(ctx):
    table = _table(ctx)
    assert table.cursor_row > ctx["start_row"] + 1


@then("the selection is back on the row it started on")
def _selection_back_on_start(ctx):
    table = _table(ctx)
    assert table.cursor_row == ctx["start_row"]


@then("it opens into its own tabbed hub, landing on the tab that matches its state")
def _opens_into_own_hub(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["target_id"]


@then("the Hierarchy tab reappears with that node still selected, scrolled to the same position")
def _hierarchy_reappears_same_position(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._active_tab == "hierarchy"
    table = _table(ctx)
    ids = [row.key.value for row in table.ordered_rows]
    assert ids[table.cursor_row] == ctx["other_id"]


@then("its row stays pinned to the top instead of scrolling away")
def _row_pinned_to_top(ctx):
    banner = ctx["hub_screen"].query_one("#pinned-ancestor", Static)
    assert banner.display
    assert ctx["item_id"] in _rendered_text(banner)


@then("the pinned duplicate is no longer shown")
def _pinned_duplicate_gone(ctx):
    banner = ctx["hub_screen"].query_one("#pinned-ancestor", Static)
    assert not banner.display


@then("its row shows its own state icon, using the same icon and colour vocabulary as every other row")
def _pinned_ancestor_shows_state_icon(ctx):
    banner = ctx["hub_screen"].query_one("#pinned-ancestor", Static)
    assert banner.display
    assert ctx["item_id"] in _rendered_text(banner)
    glyph = STATE_GLYPHS["queued"]
    strip = banner.render_line(0)
    found = None
    for segment in strip:
        if glyph.glyph in segment.text:
            found = segment
            break
    assert found is not None
    assert found.style.color.get_truecolor().hex.lower() == COLOURS[glyph.colour].lower()


@then("its Artifacts tab opens directly, skipping its own contextual default")
def _artifacts_tab_opens_directly(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._active_tab == "artifacts"


@then("its Log tab opens directly, showing the live tail")
def _log_tab_opens_live(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._active_tab == "log"


@then("its Log tab opens directly, showing its past log")
def _log_tab_opens_past(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._active_tab == "log"


@then("nothing happens, since there is no log to show")
def _nothing_happens_no_log(ctx):
    assert ctx["session"].app.screen is ctx["hub_screen"]


@then("its current step's Log tab opens directly, showing the live tail")
def _current_step_log_tab_opens_live(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["expected_log_target_id"]
    assert screen._active_tab == "log"


@then("its Log tab opens directly, showing its last completed step's log in historical mode")
def _log_tab_opens_last_completed_historical(ctx):
    from lightcycle.adapters.tui.hub import log_tab_mode

    screen = ctx["session"].app.screen
    store = ctx["store"]
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["node_id"]
    assert screen._active_tab == "log"
    assert screen._log_target == ctx["last_step_id"]
    assert log_tab_mode(store.get_node(ctx["last_step_id"])) == "historical"


@then("it is highlighted at the top row")
def _highlighted_at_top_row(ctx):
    table = _table(ctx)
    assert table.cursor_row == 0


@then("it is highlighted at its actual depth, not the top row")
def _highlighted_at_actual_depth(ctx):
    table = _table(ctx)
    ids = [row.key.value for row in table.ordered_rows]
    assert ids[table.cursor_row] == ctx["step_id"]
    assert table.cursor_row > 0


@then("the queued step's row is highlighted, not the item's own row")
def _queued_step_highlighted_not_item(ctx):
    table = _table(ctx)
    ids = _row_ids(ctx)
    assert ids[table.cursor_row] == ctx["step_id"]
    assert ids[table.cursor_row] != ctx["item_id"]


@then("it is scrolled into view")
def _scrolled_into_view(ctx):
    table = _table(ctx)
    assert table.cursor_row >= table.scroll_y
    assert table.cursor_row < table.scroll_y + table.size.height


@then("that step's own hub opens")
def _steps_own_hub_opens_plain(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["step_id"]
    assert screen._node_id != ctx["item_id"]
