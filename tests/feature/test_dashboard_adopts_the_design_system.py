import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable, RichLog, Static

from lightcycle.adapters.tui.app import DashboardFooter, ShortcutBar, StatusBar, TabStrip
from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    FOOTER_GLYPHS,
    GLOBAL_SHORTCUTS,
    STATE_GLYPHS,
)
from lightcycle.adapters.tui.hub import NodeHubScreen
from lightcycle.adapters.tui.row_grid import (
    FLEXIBLE_MINIMUM,
    GLYPH_WIDTHS,
    atomic_column_width,
    column_kind,
    compute_layout,
)
from tests.support.fake_store import FakeStore
from tests.support.screen_render import DEFAULT_SIZE as RENDER_SIZE
from tests.support.screen_render import SCREENS as RENDER_SCREENS
from tests.support.tui_harness import launch, make_test_container

scenarios("dashboard-adopts-the-design-system.feature")

def _rgb(hex_colour):
    return tuple(int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))


def _blend_over(base_hex, overlay_hex, factor):
    base = _rgb(base_hex)
    overlay = _rgb(overlay_hex)
    return "#%02x%02x%02x" % tuple(int(b + (o - b) * factor) for b, o in zip(base, overlay))


_WIREFRAME_MODAL_OVERLAY_ALPHA = 0.72

_TOKEN_BACKGROUNDS = {
    COLOURS["bg"].lower(),
    COLOURS["panel"].lower(),
    COLOURS["selected-bg"].lower(),
}
_TOKEN_BACKGROUNDS |= {
    _blend_over(token, COLOURS["bg"], _WIREFRAME_MODAL_OVERLAY_ALPHA) for token in _TOKEN_BACKGROUNDS
}

_TOKEN_FOREGROUNDS = {
    COLOURS["text"].lower(),
    COLOURS["dim"].lower(),
    COLOURS["cyan"].lower(),
    COLOURS["amber"].lower(),
    COLOURS["red"].lower(),
    COLOURS["border"].lower(),
}
_TOKEN_FOREGROUNDS |= {
    _blend_over(token, COLOURS["bg"], _WIREFRAME_MODAL_OVERLAY_ALPHA) for token in _TOKEN_FOREGROUNDS
}


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _launch(ctx):
    store = ctx.get("store") or FakeStore()
    container = make_test_container(store=store)
    ctx["session"] = launch(container, size=(120, 24))


def _widget_rendered_text(ctx, widget):
    lines = []
    compositor = ctx["session"].app.screen._compositor
    strips = compositor.render_strips()
    start, end = widget.region.x, widget.region.x + widget.region.width
    for y in range(widget.region.y, widget.region.y + widget.region.height):
        lines.append("".join(segment.text for segment in strips[y].crop(start, end)))
    return lines


def _open_priority_list(ctx):
    store = FakeStore()
    long_id = "P" * 48
    store.create_step(long_id, step="build", role="coder", id=long_id)
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    ctx["floor_widget_id"] = "#priority-list-floor"


def _open_backlog(ctx):
    store = FakeStore()
    long_id = "B" * 68
    store.create_item("An item", id=long_id)
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    ctx["session"].press("tab")
    ctx["floor_widget_id"] = "#backlog-floor"


def _open_hierarchy_tab(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    long_id = "H" * 50
    store.create_step("s", step="build", role="coder", parent=item, id=long_id)
    ctx["store"] = store
    session = launch(make_test_container(store=store))
    ctx["session"] = session
    session.run(
        lambda: session.app.push_screen(NodeHubScreen(session.app.container, item, session.app._now))
    )
    session.pause()
    ctx["floor_widget_id"] = "#hierarchy-floor"


def _open_artifacts_tab(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    long_type = "A" * 69
    store.add_artifact(item, long_type, "value")
    ctx["store"] = store
    session = launch(make_test_container(store=store))
    ctx["session"] = session
    session.run(
        lambda: session.app.push_screen(
            NodeHubScreen(session.app.container, item, session.app._now, initial_tab="artifacts")
        )
    )
    session.pause()
    session.pause()
    ctx["floor_widget_id"] = "#artifacts-floor"


_FLOOR_SCREEN_SETUP = {
    "Priority List": _open_priority_list,
    "Backlog": _open_backlog,
    "Hierarchy tab": _open_hierarchy_tab,
    "Artifacts tab": _open_artifacts_tab,
}


@given("the lightcycle store is reachable")
def _reachable(ctx):
    store = FakeStore()
    store.create_step("a", step="build", role="coder")
    store.create_step("b", step="build", role="coder")
    blocker = store.create_step("blocker", step="build", role="coder")
    store.create_step("c", step="build", role="coder", deps=[blocker])
    ctx["store"] = store


@given("the dashboard has launched")
def _given_launched(ctx):
    _launch(ctx)


@given("the shared colour tokens")
def _colour_tokens(ctx):
    pass


@given("the shared state vocabulary")
def _state_vocabulary(ctx):
    pass


@given("the shared column grids")
def _column_grids(ctx):
    pass


@given("the shared footer status vocabulary")
def _footer_status_vocabulary(ctx):
    pass


@given("the shared row-grid sizing rule")
def _row_grid_sizing_rule(ctx):
    pass


@given(parsers.parse("the {screen} is open"))
def _floor_screen_open(ctx, screen):
    _FLOOR_SCREEN_SETUP[screen](ctx)


@given(parsers.parse('the "{state}" screen state is rendered'))
def _screen_state_rendered(ctx, state):
    ctx["state"] = state
    ctx["session"] = RENDER_SCREENS[state](RENDER_SIZE)


@when("I launch the dashboard")
def _when_launch(ctx):
    if "session" not in ctx:
        _launch(ctx)


@when("Tab is pressed")
def _press_tab(ctx):
    ctx["session"].press("tab")


@when(parsers.parse("the shortcut at position {position:d} in the footer's shortcut line is read"))
def _read_shortcut(ctx, position):
    shortcut_bar = ctx["session"].app.query_one(ShortcutBar)
    ctx["shortcut"] = shortcut_bar.shortcuts[position - 1]


@when("the footer's shortcut line is given a different list of shortcuts")
def _replace_shortcuts(ctx):
    ctx["new_shortcuts"] = (("x", "example"),)
    session = ctx["session"]
    shortcut_bar = session.app.query_one(ShortcutBar)
    session.run(lambda: shortcut_bar.set_shortcuts(ctx["new_shortcuts"]))
    session.pause()


@when(parsers.parse('the "{token}" colour token is read'))
def _read_colour_token(ctx, token):
    ctx["token_value"] = COLOURS[token]


@when(parsers.parse('the glyph and colour for the "{state}" state are looked up'))
def _lookup_state_glyph(ctx, state):
    ctx["glyph_result"] = STATE_GLYPHS[state]


@when(parsers.parse('the glyph and colour for the "{token}" footer status are looked up'))
def _lookup_footer_glyph(ctx, token):
    ctx["glyph_result"] = FOOTER_GLYPHS[token]


@when("the glyph and colour for the dependency-blocked needs-attention state are looked up")
def _lookup_dependency_blocked_glyph(ctx):
    ctx["primary_glyph"] = STATE_GLYPHS["needs-attention"]
    ctx["extra_glyph"] = DEPENDENCY_BLOCKED_EXTRA_GLYPH


@when("the priority list's column order is read")
def _read_priority_list_columns(ctx):
    ctx["columns"] = tuple(COLUMN_GRIDS["priority-list"])


@when("the backlog's column order is read")
def _read_backlog_columns(ctx):
    ctx["columns"] = tuple(COLUMN_GRIDS["backlog"])


@when("the terminal is narrower than the grid's floor width")
def _terminal_narrower_than_floor(ctx):
    ctx["session"].resize(72, 24)


@then("the screen is framed on all four edges by a solid border in the border colour")
def _screen_framed(ctx):
    border = ctx["session"].app.screen.styles.border
    expected = ("solid", COLOURS["border"])
    for edge in (border.top, border.right, border.bottom, border.left):
        assert edge[0] == expected[0]
        assert edge[1].hex.lower() == expected[1].lower()


@then(parsers.parse('the tab strip reads "{text}"'))
def _tab_strip_reads(ctx, text):
    tab_strip = ctx["session"].app.query_one(TabStrip)
    rendered = "".join(str(child.content) for child in tab_strip.children)
    assert rendered == text


@then(parsers.parse('the "{label}" tab is bold and in the cyan colour'))
def _tab_bold_cyan(ctx, label):
    widget_id = "#tab-current-work" if label == "Current work" else "#tab-backlog"
    tab = ctx["session"].app.query_one(widget_id)
    assert tab.styles.color.hex.lower() == COLOURS["cyan"].lower()
    assert "bold" in str(tab.styles.text_style)


@then(parsers.parse('the "{label}" tab is in the dim colour'))
def _tab_dim(ctx, label):
    widget_id = "#tab-current-work" if label == "Current work" else "#tab-backlog"
    tab = ctx["session"].app.query_one(widget_id)
    assert tab.styles.color.hex.lower() == COLOURS["dim"].lower()


@then(parsers.parse('the "{label}" tab is still the emphasised tab'))
def _tab_still_emphasised(ctx, label):
    tab = ctx["session"].app.query_one("#tab-current-work")
    assert tab.styles.color.hex.lower() == COLOURS["cyan"].lower()
    assert "bold" in str(tab.styles.text_style)


@then("a selected row's background is the selected-row colour")
def _selected_row_background(ctx):
    table = ctx["session"].app.query_one(DataTable)
    style = table.get_component_styles("datatable--cursor")
    assert style.background.hex.lower() == COLOURS["selected-bg"].lower()


@then("the selection cursor glyph is rendered in the cyan colour")
def _selection_cursor_glyph_cyan(ctx):
    table = ctx["session"].app.query_one(DataTable)
    row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
    glyph = table.get_cell(row_key, "cursor")
    assert glyph.style == COLOURS["cyan"]


def _visible_list_widget(ctx):
    screen = ctx["session"].app.screen
    candidates = [widget for widget in screen.query(DataTable) if widget.display]
    candidates += [widget for widget in screen.query(RichLog) if widget.display]
    assert len(candidates) == 1, (ctx["state"], candidates)
    return candidates[0]


@then(
    "every row in its list area, except the one under the selection cursor, has a "
    "background of the bg colour"
)
def _every_row_paints_bg(ctx):
    session = ctx["session"]
    region = _visible_list_widget(ctx).region
    strips = session.app.screen._compositor.render_strips()
    bg_hex = COLOURS["bg"].lower()
    selected_hex = COLOURS["selected-bg"].lower()
    for y in range(region.y, region.y + region.height):
        strip = strips[y].crop(region.x, region.x + region.width)
        row_colours = {
            segment.style.bgcolor.get_truecolor().hex.lower()
            for segment in strip
            if segment.style and segment.style.bgcolor
        }
        if row_colours == {selected_hex}:
            continue
        assert row_colours == {bg_hex}, (ctx["state"], y, row_colours)


def test_every_registered_screen_state_paints_only_token_backgrounds():
    for state, render in RENDER_SCREENS.items():
        session = render(RENDER_SIZE)
        try:
            strips = session.app.screen._compositor.render_strips()
            for y, strip in enumerate(strips):
                x = 0
                for segment in strip:
                    width = len(segment.text)
                    if segment.style and segment.style.bgcolor:
                        hexv = segment.style.bgcolor.get_truecolor().hex.lower()
                        assert hexv in _TOKEN_BACKGROUNDS, (state, x, y, hexv)
                    x += width
        finally:
            session.close()


def test_every_registered_screen_state_paints_only_token_foregrounds():
    for state, render in RENDER_SCREENS.items():
        session = render(RENDER_SIZE)
        try:
            strips = session.app.screen._compositor.render_strips()
            for y, strip in enumerate(strips):
                x = 0
                for segment in strip:
                    width = len(segment.text)
                    if segment.style and segment.style.color:
                        hexv = segment.style.color.get_truecolor().hex.lower()
                        assert hexv in _TOKEN_FOREGROUNDS, (state, x, y, hexv)
                    x += width
        finally:
            session.close()


@then("the footer occupies two one-row lines, a status line above a shortcut line")
def _footer_two_lines(ctx):
    footer = ctx["session"].app.query_one(DashboardFooter)
    status_bar, shortcut_bar = footer.children
    assert isinstance(status_bar, StatusBar)
    assert isinstance(shortcut_bar, ShortcutBar)
    assert status_bar.styles.height.value == 1
    assert shortcut_bar.styles.height.value == 1
    assert footer.content_region.height == 2
    assert footer.region.contains_region(status_bar.region)
    assert footer.region.contains_region(shortcut_bar.region)
    assert status_bar.region.y < shortcut_bar.region.y


@then("the footer's top border is in the border colour")
def _footer_top_border(ctx):
    footer = ctx["session"].app.query_one(DashboardFooter)
    edge, colour = footer.styles.border_top
    assert edge == "solid"
    assert colour.hex.lower() == COLOURS["border"].lower()


@then("the footer's background is the bg colour, not the panel colour")
def _footer_background(ctx):
    footer = ctx["session"].app.query_one(DashboardFooter)
    assert footer.styles.background.hex.lower() == COLOURS["bg"].lower()
    assert footer.styles.background.hex.lower() != COLOURS["panel"].lower()


@then(parsers.parse('its key is "{key}"'))
def _shortcut_key(ctx, key):
    assert ctx["shortcut"][0] == key


@then(parsers.parse('its action is "{action}"'))
def _shortcut_action(ctx, action):
    assert ctx["shortcut"][1] == action


@then("every key in the footer's shortcut line is bold and in the text colour")
def _every_key_bold_text(ctx):
    footer = ctx["session"].app.query_one(DashboardFooter)
    shortcut_bar = ctx["session"].app.query_one(ShortcutBar)
    keys = shortcut_bar.query(".shortcut-key")
    assert len(keys) == len(GLOBAL_SHORTCUTS)
    for key_widget in keys:
        assert key_widget.styles.color.hex.lower() == COLOURS["text"].lower()
        assert "bold" in str(key_widget.styles.text_style)
        assert footer.region.contains_region(key_widget.region)


@then("every action label in the footer's shortcut line is in the dim colour")
def _every_action_dim(ctx):
    footer = ctx["session"].app.query_one(DashboardFooter)
    shortcut_bar = ctx["session"].app.query_one(ShortcutBar)
    actions = shortcut_bar.query(".shortcut-action")
    assert len(actions) == len(GLOBAL_SHORTCUTS)
    for action_widget in actions:
        assert action_widget.styles.color.hex.lower() == COLOURS["dim"].lower()
        assert footer.region.contains_region(action_widget.region)


@then("the footer's shortcut line renders that new list instead of the global shortcuts")
def _shortcuts_replaced(ctx):
    shortcut_bar = ctx["session"].app.query_one(ShortcutBar)
    assert shortcut_bar.shortcuts == ctx["new_shortcuts"]
    assert shortcut_bar.shortcuts != GLOBAL_SHORTCUTS


@then(parsers.parse('its value is "{hex_value}"'))
def _token_value(ctx, hex_value):
    assert ctx["token_value"] == hex_value


@then(parsers.parse('the glyph is "{glyph}"'))
def _glyph_value(ctx, glyph):
    assert ctx["glyph_result"].glyph == glyph


@then(parsers.parse("the colour is the {colour} colour"))
def _glyph_colour(ctx, colour):
    assert ctx["glyph_result"].colour == colour


@then("its first glyph and colour are the same red dot as the plain needs-attention state")
def _dependency_blocked_primary(ctx):
    assert ctx["primary_glyph"] == STATE_GLYPHS["needs-attention"]
    assert ctx["primary_glyph"].glyph == "●"
    assert ctx["primary_glyph"].colour == "red"


@then("it additionally carries an amber chain-link glyph")
def _dependency_blocked_extra(ctx):
    assert ctx["extra_glyph"].glyph == "⛓"
    assert ctx["extra_glyph"].colour == "amber"


@then("it is cursor, icon, id, project, title, step, time")
def _priority_list_column_order(ctx):
    assert ctx["columns"] == ("cursor", "icon", "id", "project", "title", "step", "time")


@then("it is cursor, id, project, title")
def _backlog_column_order(ctx):
    assert ctx["columns"] == ("cursor", "id", "project", "title")


@when(parsers.parse('the "{column}" column\'s kind is looked up'))
def _lookup_column_kind(ctx, column):
    ctx["kind"] = column_kind(column)


@then(parsers.parse("its kind is {kind}"))
def _kind_is(ctx, kind):
    assert ctx["kind"] == kind


@then(parsers.parse("the {column} column's width is fixed at {width:d} characters"))
def _glyph_width_fixed(ctx, column, width):
    assert GLYPH_WIDTHS[column] == width


@then(
    "an atomic column's width is recomputed from every row in the list, not only the rows "
    "currently visible"
)
def _atomic_width_whole_list(ctx):
    many_values = ["short"] * 50 + ["a-much-longer-value-far-down-the-list"] + ["short"] * 50
    visible_slice = many_values[:20]
    assert atomic_column_width(visible_slice) != atomic_column_width(many_values)
    assert atomic_column_width(many_values) == len("a-much-longer-value-far-down-the-list")


@then("an atomic column has no overflow behaviour that cuts or wraps a value")
def _atomic_never_cuts(ctx):
    long_value = "LIGHTCYCLE-3.1.1" * 3
    layout = compute_layout(10, ["cursor"], {"id": [long_value]}, indent=0)
    assert layout.atomic_widths["id"] == len(long_value)


@then("a flexible column's minimum width is 24 characters")
def _flexible_minimum(ctx):
    assert FLEXIBLE_MINIMUM == 24


@then("a single message, centred and in the dim colour, names the width the grid needs")
def _floor_message_shown(ctx):
    widget = ctx["session"].app.screen.query_one(ctx["floor_widget_id"], Static)
    assert widget.display
    assert widget.styles.color.hex.lower() == COLOURS["dim"].lower()
    assert widget.styles.content_align == ("center", "middle")
    lines = _widget_rendered_text(ctx, widget)
    message_line = next((line for line in lines if line.strip()), "")
    assert "Widen the terminal to at least" in message_line
    assert any(char.isdigit() for char in message_line)
    stripped = message_line.strip()
    leading = message_line.index(stripped)
    trailing = len(message_line) - leading - len(stripped)
    assert leading > 0
    assert trailing > 0


@then("the footer is still shown, so the operator can still quit")
def _floor_footer_still_shown(ctx):
    footer = ctx["session"].app.screen.query_one(DashboardFooter)
    assert footer.display is not False
    status_bar, shortcut_bar = footer.children
    status_lines = _widget_rendered_text(ctx, status_bar)
    shortcut_lines = _widget_rendered_text(ctx, shortcut_bar)
    assert any(line.strip() for line in status_lines)
    assert any(line.strip() for line in shortcut_lines)
