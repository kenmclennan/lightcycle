import pytest
from pytest_bdd import given, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.design_system import COLOURS
from lightcycle.adapters.tui.hub import DescriptionPane, NodeHubScreen
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-description-tab.feature")

DESCRIPTION_TEXT = "What this item is about, in a few plain sentences."
LONG_DESCRIPTION = "\n".join("line %02d of the description" % i for i in range(60))


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _painted_lines(session, widget):
    region = widget.region
    strips = session.app.screen._compositor.render_strips()
    return [
        "".join(seg.text for seg in strips[y].crop(region.x, region.x + region.width))
        for y in range(region.y, region.y + region.height)
    ]


def _painted_segments(session, widget):
    region = widget.region
    strips = session.app.screen._compositor.render_strips()
    rows = []
    for y in range(region.y, region.y + region.height):
        row = []
        for seg in strips[y].crop(region.x, region.x + region.width):
            colour = seg.style.color if seg.style else None
            row.append((seg.text, colour.get_truecolor() if colour else None))
        rows.append(row)
    return rows


def _description_pane(ctx):
    return ctx["session"].app.screen.query_one(DescriptionPane)


def _description_text(ctx):
    return "\n".join(_painted_lines(ctx["session"], _description_pane(ctx)))


def _widget_text(session, widget):
    return "\n".join(_painted_lines(session, widget)).strip()


def _open_hub_on_description(ctx, node_id):
    session = ctx["session"]
    screen = NodeHubScreen(session.app.container, node_id, session.app._now, initial_tab="description")
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    ctx["node_id"] = node_id
    return session


def _launch_with_item(ctx, description):
    store = FakeStore()
    item = store.create_item("Item")
    if description is not None:
        store.edit_node(item, description=description)
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    _open_hub_on_description(ctx, item)
    return ctx["session"]


@given("a node has a description")
def _node_has_description(ctx):
    _launch_with_item(ctx, DESCRIPTION_TEXT)


@given("a node has no description")
def _node_has_no_description(ctx):
    _launch_with_item(ctx, None)


@given("a node has a description longer than the pane")
def _node_has_long_description(ctx):
    _launch_with_item(ctx, LONG_DESCRIPTION)


@given("I open its Description tab")
def _given_open_description_tab(ctx):
    pass


@given("the view has scrolled forward")
def _given_view_scrolled_forward(ctx):
    ctx["session"].press("down")


@when("I open its Description tab")
def _open_description_tab(ctx):
    pass


@when("its hub is open")
def _hub_is_open(ctx):
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


@then("the full description text is shown")
def _full_description_shown(ctx):
    assert DESCRIPTION_TEXT in _description_text(ctx)


@then("it renders in the text colour, not the dim colour")
def _renders_in_text_colour(ctx):
    text_rgb = COLOURS["text"].lower()
    dim_rgb = COLOURS["dim"].lower()
    session = ctx["session"]
    found = False
    for row in _painted_segments(session, _description_pane(ctx)):
        for text, colour in row:
            if not text.strip():
                continue
            hexed = colour.hex.lower() if colour else None
            assert hexed != dim_rgb
            if hexed == text_rgb:
                found = True
    assert found


@then("a calm message is shown in place of the text, not a blank area")
def _calm_message_shown(ctx):
    screen = ctx["session"].app.screen
    assert not screen.query_one(DescriptionPane).display
    empty = screen.query_one("#hub-description-empty", Static)
    assert empty.display
    assert _widget_text(ctx["session"], empty) != ""


@then("the Description tab is present, alongside Hierarchy, Log, and Artifacts")
def _description_tab_present(ctx):
    screen = ctx["session"].app.screen
    assert _widget_text(ctx["session"], screen.query_one("#hub-tab-hierarchy", Static)) == "Hierarchy"
    assert _widget_text(ctx["session"], screen.query_one("#hub-tab-log", Static)) == "Log"
    assert _widget_text(ctx["session"], screen.query_one("#hub-tab-artifacts", Static)) == "Artifacts"
    assert _widget_text(ctx["session"], screen.query_one("#hub-tab-description", Static)) == "Description"


@then("the view is scrolled to the top")
def _view_scrolled_to_top(ctx):
    assert _description_pane(ctx).scroll_y == 0


@then("no character of the description is cut off")
def _no_character_cut_off(ctx):
    pane = _description_pane(ctx)
    session = ctx["session"]
    session.run(lambda: pane.scroll_end(animate=False))
    session.pause()
    assert "line 59 of the description" in _description_text(ctx)


@then("the view has scrolled forward")
def _then_view_scrolled_forward(ctx):
    assert _description_pane(ctx).scroll_y > 0


@then("the view has scrolled back")
def _then_view_scrolled_back(ctx):
    assert _description_pane(ctx).scroll_y == 0


@then("the view moves a full screen, not one line")
def _then_moves_full_screen(ctx):
    pane = _description_pane(ctx)
    assert pane.scroll_y > 1
    ctx["scroll_before"] = pane.scroll_y


@then("the view is scrolled back to where it started")
def _then_scrolled_back_to_start(ctx):
    assert _description_pane(ctx).scroll_y == 0
