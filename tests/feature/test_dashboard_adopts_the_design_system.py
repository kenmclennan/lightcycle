import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable

from lightcycle.adapters.tui.app import DashboardFooter, ShortcutBar, StatusBar, TabStrip
from lightcycle.adapters.tui.design_system import (
    COLOURS,
    COLUMN_GRIDS,
    DEPENDENCY_BLOCKED_EXTRA_GLYPH,
    GLOBAL_SHORTCUTS,
    STATE_GLYPHS,
)
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("dashboard-adopts-the-design-system.feature")


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
    ctx["session"] = launch(container)


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


@when("the glyph and colour for the dependency-blocked needs-attention state are looked up")
def _lookup_dependency_blocked_glyph(ctx):
    ctx["primary_glyph"] = STATE_GLYPHS["needs-attention"]
    ctx["extra_glyph"] = DEPENDENCY_BLOCKED_EXTRA_GLYPH


@when("the priority list's column order is read")
def _read_priority_list_columns(ctx):
    ctx["columns"] = tuple(name for name, width in COLUMN_GRIDS["priority-list"])


@when("the backlog's column order is read")
def _read_backlog_columns(ctx):
    ctx["columns"] = tuple(name for name, width in COLUMN_GRIDS["backlog"])


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


@then("a selected row's foreground is the cyan colour")
def _selected_row_foreground(ctx):
    table = ctx["session"].app.query_one(DataTable)
    style = table.get_component_styles("datatable--cursor")
    assert style.color.hex.lower() == COLOURS["cyan"].lower()


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
