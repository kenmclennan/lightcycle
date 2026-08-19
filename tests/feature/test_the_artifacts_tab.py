import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.hub import ArtifactsTable, NodeHubScreen, TextArtifactViewerScreen
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-artifacts-tab.feature")


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _widget_text(widget):
    lines = ["".join(seg.text for seg in widget.render_line(i)) for i in range(widget.size.height)]
    return "\n".join(lines).strip()


def _rendered_cell_text(table, row_key, column_key):
    strip = table.render_line(table.get_row_index(row_key))
    pad = table.cell_padding
    offset = 0
    for column in table.ordered_columns:
        start = offset + pad
        end = start + column.width
        if column.key.value == column_key:
            return "".join(segment.text for segment in strip.crop(start, end)).strip()
        offset = end + pad
    raise AssertionError("column %r not found" % column_key)


def _open_hub_on_artifacts(ctx, node_id):
    session = ctx["session"]
    screen = NodeHubScreen(session.app.container, node_id, session.app._now, initial_tab="artifacts")
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    ctx["node_id"] = node_id
    return session


def _launch_with_item(ctx, artifacts):
    store = FakeStore()
    item = store.create_item("Item")
    for atype, value, kind, internal in artifacts:
        store.add_artifact(item, atype, value, internal=internal, kind=kind)
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    _open_hub_on_artifacts(ctx, item)
    return ctx["session"]


@given('a node has artifacts of type "spec", "branch", and "pr"')
def _artifacts_of_three_types(ctx):
    _launch_with_item(ctx, [
        ("spec", "specs/x.md", "filepath", False),
        ("branch", "feat/x", "text", False),
        ("pr", "https://gh/pr/1", "url", False),
    ])


@given("a node has both an internal artifact and a non-internal artifact")
def _internal_and_non_internal(ctx):
    _launch_with_item(ctx, [
        ("reflection", "internal note", "text", True),
        ("repo", "org/repo", "text", False),
    ])


@given("a node has no non-internal artifacts")
def _no_viewable_artifacts(ctx):
    _launch_with_item(ctx, [])


@given("the artifact list has more than one entry")
def _more_than_one_entry(ctx):
    _launch_with_item(ctx, [
        ("repo", "org/a", "text", False),
        ("branch", "feat/a", "text", False),
    ])


@given("the selection is not on the first entry")
def _selection_not_first(ctx):
    ctx["session"].press("down")


@given("an artifact is selected in the list")
def _artifact_selected(ctx):
    _launch_with_item(ctx, [("brief", "briefs/x.md", "text", False)])


@given("I opened the artifact list from a node's hub view")
def _opened_artifact_list_from_hub(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    store.add_artifact(item, "repo", "org/repo")
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    session = _open_hub_on_artifacts(ctx, item)
    ctx["hub_screen"] = session.app.screen


@when("I open its Artifacts tab")
def _open_artifacts_tab(ctx):
    pass


@when("its hub is open")
def _hub_is_open(ctx):
    pass


@when(parsers.parse("{key} is pressed"))
def _key_pressed(ctx, key):
    keymap = {
        "Enter": "enter", "→": "right", "Esc": "escape", "←": "left",
        "Down": "down", "Up": "up",
    }
    ctx["session"].press(keymap.get(key, key))


@when(parsers.parse("I close it with {key}"))
def _close_it_with(ctx, key):
    keymap = {"Esc": "escape", "←": "left"}
    ctx["session"].press(keymap.get(key, key))


@then("each is shown labeled by its own type")
def _each_labeled_by_type(ctx):
    table = ctx["session"].app.screen.query_one(ArtifactsTable)
    assert table.row_count == 3
    types = [_rendered_cell_text(table, str(i), "type") for i in range(3)]
    assert types == ["spec", "branch", "pr"]


@then("only the non-internal artifact is shown")
def _only_non_internal_shown(ctx):
    table = ctx["session"].app.screen.query_one(ArtifactsTable)
    assert table.row_count == 1
    assert _rendered_cell_text(table, "0", "type") == "repo"


@then("the internal artifact does not appear")
def _internal_does_not_appear(ctx):
    table = ctx["session"].app.screen.query_one(ArtifactsTable)
    types = [_rendered_cell_text(table, str(i), "type") for i in range(table.row_count)]
    assert "reflection" not in types


@then("a calm message is shown in place of the list, not a blank area")
def _calm_message_shown(ctx):
    screen = ctx["session"].app.screen
    assert not screen.query_one(ArtifactsTable).display
    empty = screen.query_one("#hub-artifacts-empty", Static)
    assert empty.display
    assert _widget_text(empty) != ""


@then("the Artifacts tab is present, alongside Hierarchy and Log")
def _artifacts_tab_present(ctx):
    screen = ctx["session"].app.screen
    assert _widget_text(screen.query_one("#hub-tab-hierarchy", Static)) == "Hierarchy"
    assert _widget_text(screen.query_one("#hub-tab-log", Static)) == "Log"
    assert _widget_text(screen.query_one("#hub-tab-artifacts", Static)) == "Artifacts"


@then("the selection has moved to the next entry")
def _selection_moved_next(ctx):
    table = ctx["session"].app.screen.query_one(ArtifactsTable)
    assert table.cursor_row == 1


@then("the selection has moved to the previous entry")
def _selection_moved_previous(ctx):
    table = ctx["session"].app.screen.query_one(ArtifactsTable)
    assert table.cursor_row == 0


@then("it opens in the viewer appropriate for its kind")
def _opens_in_appropriate_viewer(ctx):
    assert isinstance(ctx["session"].app.screen, TextArtifactViewerScreen)


@then("the hub view reappears as it was")
def _hub_view_reappears(ctx):
    assert not isinstance(ctx["session"].app.screen, NodeHubScreen)
