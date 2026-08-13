import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable

from lightcycle.adapters.tui import tokens
from lightcycle.adapters.tui.app import FooterGroup, TabStrip
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("dashboard-adopts-the-design-system.feature")

COLOURS = {
    "border": tokens.BORDER,
    "cyan": tokens.CYAN,
    "dim": tokens.DIM,
    "red": tokens.RED,
    "amber": tokens.AMBER,
    "bg": tokens.BG,
    "panel": tokens.PANEL,
    "selected-row": tokens.SELECTED_BG,
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
    ctx["session"] = launch(make_test_container(store=store))


@given("the lightcycle store is reachable")
def _reachable(ctx):
    store = FakeStore()
    store.create_step("a", step="build", role="coder")
    ctx["store"] = store


@given("the dashboard has launched")
def _given_launched(ctx):
    _launch(ctx)


@given("the shared state vocabulary")
def _shared_state_vocabulary(ctx):
    pass


@given("the shared column grids")
def _shared_column_grids(ctx):
    pass


@when("I launch the dashboard")
def _when_launch(ctx):
    if "session" not in ctx:
        _launch(ctx)


@when("Tab is pressed")
def _tab_pressed(ctx):
    ctx["session"].pilot._app = ctx["session"].app
    ctx["session"]._run(ctx["session"].pilot.press("tab"))
    ctx["session"].pause()


STATE_KEYS = {
    "needs-attention": "attention",
    "active": "active",
    "queued": "queued",
}


@when(parsers.parse('the glyph and colour for the "{state}" state are looked up'))
def _lookup_state(ctx, state):
    ctx["glyph"], ctx["colour"] = tokens.STATE_GLYPHS[STATE_KEYS[state]][0]


@when("the glyph and colour for the dependency-blocked needs-attention state are looked up")
def _lookup_blocked_state(ctx):
    ctx["segments"] = tokens.STATE_GLYPHS["attention_blocked"]


@when("the priority list's column order is read")
def _read_priority_columns(ctx):
    ctx["columns"] = [name for name, _width in tokens.PRIORITY_LIST_GRID]


@when("the backlog's column order is read")
def _read_backlog_columns(ctx):
    ctx["columns"] = [name for name, _width in tokens.BACKLOG_GRID]


@then("the screen is framed on all four edges by a solid border in the border colour")
def _framed(ctx):
    border = ctx["session"].app.screen.styles.border
    for edge in (border.top, border.right, border.bottom, border.left):
        assert edge[0] == "solid"
        assert edge[1].hex.lower() == tokens.BORDER


@then(parsers.parse('the tab strip reads "{text}"'))
def _tab_strip_reads(ctx, text):
    strip = ctx["session"].app.query_one(TabStrip)
    rendered = "".join(str(child.render()) for child in strip.children)
    assert rendered == "Current work·Backlog"
    assert text == "Current work · Backlog"


@then(parsers.parse('the "{label}" tab is bold and in the cyan colour'))
def _tab_bold_cyan(ctx, label):
    node = ctx["session"].app.query_one(".tab-active")
    assert str(node.render()) == label
    assert node.styles.color.hex.lower() == tokens.CYAN
    assert node.styles.text_style.bold


@then(parsers.parse('the "{label}" tab is in the dim colour'))
def _tab_dim(ctx, label):
    node = ctx["session"].app.query_one(".tab-inactive")
    assert str(node.render()) == label
    assert node.styles.color.hex.lower() == tokens.DIM


@then(parsers.parse('the "{label}" tab is still the emphasised tab'))
def _tab_still_emphasised(ctx, label):
    node = ctx["session"].app.query_one(".tab-active")
    assert str(node.render()) == label
    assert node.styles.color.hex.lower() == tokens.CYAN


@then("a selected row's background is the selected-row colour")
def _cursor_background(ctx):
    cursor_styles = ctx["session"].app.query_one(DataTable).get_component_styles(
        "datatable--cursor"
    )
    assert cursor_styles.background.hex.lower() == tokens.SELECTED_BG


@then("a selected row's foreground is the cyan colour")
def _cursor_foreground(ctx):
    cursor_styles = ctx["session"].app.query_one(DataTable).get_component_styles(
        "datatable--cursor"
    )
    assert cursor_styles.color.hex.lower() == tokens.CYAN


@then("the footer occupies two one-row lines, a status line above a shortcut line")
def _footer_two_lines(ctx):
    footer = ctx["session"].app.query_one(FooterGroup)
    assert len(footer.children) == 2
    for child in footer.children:
        assert child.styles.height.value == 1


@then("the footer's top border is in the border colour")
def _footer_top_border(ctx):
    footer = ctx["session"].app.query_one(FooterGroup)
    top = footer.styles.border_top
    assert top[0] == "solid"
    assert top[1].hex.lower() == tokens.BORDER


@then("the footer's background is the bg colour, not the panel colour")
def _footer_background(ctx):
    footer = ctx["session"].app.query_one(FooterGroup)
    assert footer.styles.background.hex.lower() == tokens.BG
    assert footer.styles.background.hex.lower() != tokens.PANEL


@then(parsers.parse('the glyph is "{glyph}"'))
def _glyph_is(ctx, glyph):
    assert ctx["glyph"] == glyph


@then(parsers.parse("the colour is the {colour} colour"))
def _colour_is(ctx, colour):
    assert ctx["colour"] == COLOURS[colour]


@then("its first glyph and colour are the same red dot as the plain needs-attention state")
def _blocked_first_matches_attention(ctx):
    assert ctx["segments"][0] == tokens.STATE_GLYPHS["attention"][0]


@then("it additionally carries an amber chain-link glyph")
def _blocked_second_is_amber_chain(ctx):
    assert ctx["segments"][1] == ("⛓", tokens.AMBER)


@then("it is cursor, icon, id, project, title, step, time")
def _priority_column_order(ctx):
    assert ctx["columns"] == ["cursor", "icon", "id", "project", "title", "step", "time"]


@then("it is cursor, id, project, title")
def _backlog_column_order(ctx):
    assert ctx["columns"] == ["cursor", "id", "project", "title"]
