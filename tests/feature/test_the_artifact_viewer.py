import time

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle import __version__
from lightcycle.adapters.tui.app import BacklogView
from lightcycle.adapters.tui.design_system import COLOURS, FOOTER_GLYPHS
from lightcycle.adapters.tui.hub import (
    ArtifactListTable,
    ArtifactsTable,
    ArtifactTextBody,
    ArtifactViewerScreen,
    ListArtifactViewerScreen,
    NodeHubScreen,
    TextArtifactViewerScreen,
)
from lightcycle.application.setup import UpgradeResponse
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeBreakerPort, FakeLauncher, FakeLock, launch, make_test_container

scenarios("the-artifact-viewer.feature")


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


def _painted_lines(session, widget):
    region = widget.region
    strips = session.app.screen._compositor.render_strips()
    return [
        "".join(seg.text for seg in strips[y].crop(region.x, region.x + region.width))
        for y in range(region.y, region.y + region.height)
    ]


def _rendered_segment(session, widget_id):
    widget = session.app.screen.query_one(widget_id, Static)
    strip = widget.render_line(0)
    text = "".join(segment.text for segment in strip)
    style = None
    for segment in strip:
        if segment.text.strip():
            style = segment.style
            break
    return widget, text, style


def _rendered_segments(session, widget_id):
    widget = session.app.screen.query_one(widget_id, Static)
    strip = widget.render_line(0)
    return [(segment.text, segment.style) for segment in strip if segment.text]


def _colour_of(style):
    return style.color.get_truecolor().hex.lower()


def _setup(ctx, artifacts, launcher=None, fs=None, size=None):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    for atype, value, kind in artifacts:
        store.add_artifact(item, atype, value, kind=kind)
    ctx["store"] = store
    ctx["launcher"] = launcher or FakeLauncher()
    ctx["lock"] = ctx.get("lock") or FakeLock()
    ctx["breaker"] = ctx.get("breaker") or FakeBreakerPort()
    container = make_test_container(
        store=store, fs=fs, launcher=ctx["launcher"], lock=ctx["lock"], breaker=ctx["breaker"]
    )
    ctx["session"] = launch(container, size=size, upgrade_check=ctx.get("upgrade_check"))
    session = ctx["session"]
    screen = NodeHubScreen(session.app.container, item, session.app._now, initial_tab="artifacts")
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    ctx["item_id"] = item
    return session


@given('an artifact declares kind "text"')
def _artifact_kind_text(ctx):
    _setup(ctx, [("finding", "some text content", "text")])


@given("a text artifact longer than one page is open")
def _long_text_open(ctx):
    lines = "\n".join("line %02d" % i for i in range(60))
    _setup(ctx, [("finding", lines, "text")], size=(80, 24))
    ctx["session"].press("enter")


@given("an artifact declares a kind the TUI does not recognise")
def _unrecognised_kind(ctx):
    _setup(ctx, [("mystery", "mystery value", "mystery-kind")])


@given('an artifact declares kind "url"')
def _artifact_kind_url(ctx):
    _setup(ctx, [("pr", "https://gh/pr/1", "url")])


@given("a URL artifact opens successfully in the browser")
def _url_opens_successfully(ctx):
    _setup(ctx, [("pr", "https://gh/pr/1", "url")], launcher=FakeLauncher(url_succeeds=True))
    ctx["session"].press("enter")


@given("a URL artifact fails to open, e.g. no browser is available")
def _url_fails(ctx):
    _setup(ctx, [("pr", "https://gh/pr/1", "url")], launcher=FakeLauncher(url_succeeds=False))
    ctx["session"].press("enter")


@given('an artifact declares kind "filepath"')
def _artifact_kind_filepath(ctx):
    _setup(ctx, [("spec", "/specs/x.md", "filepath")], fs=FakeFs(files={"/specs/x.md": b"content"}))


@given("a file-path artifact opens successfully in its application")
def _filepath_opens_successfully(ctx):
    _setup(
        ctx, [("spec", "/specs/x.md", "filepath")],
        fs=FakeFs(files={"/specs/x.md": b"content"}), launcher=FakeLauncher(path_succeeds=True),
    )
    ctx["session"].press("enter")


@given("a file-path artifact whose file no longer exists at that path")
def _filepath_missing(ctx):
    _setup(ctx, [("spec", "/specs/gone.md", "filepath")], fs=FakeFs())


@given('an artifact declares kind "list"')
def _artifact_kind_list(ctx):
    _setup(ctx, [("watched", "a\nb\nc", "list")])


@given("a list artifact with more items than fit on one screen is open")
def _long_list_open(ctx):
    items = "\n".join("item %02d" % i for i in range(40))
    _setup(ctx, [("watched", items, "list")], size=(80, 24))
    ctx["session"].press("enter")


@given(parsers.parse('I opened a "{kind}" artifact from the list'))
def _opened_kind_from_list(ctx, kind):
    value = "some text" if kind == "text" else "a\nb\nc"
    _setup(ctx, [("repo", "org/repo", "text"), ("finding", value, kind)])
    table = ctx["session"].app.screen.query_one(ArtifactsTable)
    ctx["session"].run(lambda: table.move_cursor(row=1))
    ctx["session"].pause()
    ctx["selected_index"] = 1
    ctx["session"].press("enter")


@given(parsers.parse("a node has {total:d} non-internal artifacts"))
def _node_has_n_artifacts(ctx, total):
    artifacts = [("finding-%d" % i, "text %d" % i, "text") for i in range(total)]
    _setup(ctx, artifacts)


@given(parsers.parse("I open the text artifact at position {position:d} in that list"))
def _open_text_artifact_at_position(ctx, position):
    table = ctx["session"].app.screen.query_one(ArtifactsTable)
    ctx["session"].run(lambda: table.move_cursor(row=position - 1))
    ctx["session"].pause()
    ctx["session"].press("enter")


@given("the artifact viewer is open, showing a text artifact")
def _viewer_open_text(ctx):
    _setup(ctx, [("finding", "some text", "text")])
    ctx["session"].press("enter")


@given("a newer version is available")
def _newer_version_available(ctx):
    ctx["remote_version"] = "9.9.9"
    ctx["upgrade_check"] = lambda: UpgradeResponse(
        current=__version__, remote=ctx["remote_version"], available=True, applied=False
    )


@when(parsers.parse("I select it with {key}"))
@given(parsers.parse("I select it with {key}"))
def _select_it_with(ctx, key):
    keymap = {"Enter": "enter", "→": "right"}
    ctx["session"].press(keymap.get(key, key))


@when(parsers.parse("I close it with {key}"))
def _close_it_with(ctx, key):
    keymap = {"Esc": "escape", "←": "left"}
    ctx["session"].press(keymap.get(key, key))


@when("that happens")
def _that_happens(ctx):
    pass


@when("it opens")
def _it_opens(ctx):
    pass


@when("I scroll to the end")
def _scroll_to_end(ctx):
    session = ctx["session"]
    screen = session.app.screen
    if isinstance(screen, TextArtifactViewerScreen):
        body = screen.query_one(ArtifactTextBody)
        session.run(lambda: body.scroll_end(animate=False))
        session.pause()
        session.pause()
    else:
        table = screen.query_one(ArtifactListTable)
        session.run(lambda: table.move_cursor(row=table.row_count - 1))
        session.pause()


@when("Tab is pressed")
def _tab_is_pressed(ctx):
    ctx["session"].press("tab")


@when("the pool or breaker state changes")
def _pool_or_breaker_state_changes(ctx):
    ctx["lock"].set_running(True)
    ctx["breaker"].save({"open": True, "reset_at": time.time() + 3600})


@when("one poll interval elapses")
def _one_poll_interval_elapses(ctx):
    session = ctx["session"]
    session.run(session.app.screen.poll_refresh)
    session.pause()


@then("it opens full-screen")
def _opens_full_screen(ctx):
    assert isinstance(ctx["session"].app.screen, TextArtifactViewerScreen)


@then("it is scrollable if longer than one page")
def _scrollable_if_long(ctx):
    body = ctx["session"].app.screen.query_one(ArtifactTextBody)
    assert any(b.key == "down" for b in body.BINDINGS)


@then("the whole artifact can be read without truncation")
def _whole_artifact_readable(ctx):
    session = ctx["session"]
    screen = session.app.screen
    if isinstance(screen, TextArtifactViewerScreen):
        body = screen.query_one(ArtifactTextBody)
        text = "\n".join(_painted_lines(session, body))
        assert "line 59" in text
    else:
        table = screen.query_one(ArtifactListTable)
        text = "\n".join(_painted_lines(session, table))
        assert "item 39" in text


@then("it opens in the text viewer, not an error")
def _opens_text_viewer_not_error(ctx):
    assert isinstance(ctx["session"].app.screen, TextArtifactViewerScreen)


@then("it opens in the system's default browser")
def _opens_in_browser(ctx):
    assert ctx["launcher"].opened_urls == ["https://gh/pr/1"]


@then("a brief confirmation toast is shown")
def _toast_shown(ctx):
    screen = ctx["session"].app.screen
    toast = screen.query_one("#hub-artifacts-toast", Static)
    assert toast.display
    assert "Opened" in _widget_text(toast)


@then("the artifact list reappears")
def _artifact_list_reappears(ctx):
    session = ctx["session"]
    screen = session.app.screen
    session.run(screen._dismiss_toast)
    session.pause()
    assert isinstance(screen, NodeHubScreen)
    assert screen.query_one(ArtifactsTable).display


@then("a clear message is shown, not a silent failure")
def _clear_failure_message(ctx):
    toast = ctx["session"].app.screen.query_one("#hub-artifacts-toast", Static)
    assert toast.display
    assert "Could not open" in _widget_text(toast)
    assert ctx["launcher"].opened_urls == ["https://gh/pr/1"]


@then("it opens via the OS's default handler for that file type")
def _opens_via_os_handler(ctx):
    assert ctx["launcher"].opened_paths == ["/specs/x.md"]


@then("a clear message is shown, not a silent failure or crash")
def _clear_failure_message_crash(ctx):
    toast = ctx["session"].app.screen.query_one("#hub-artifacts-toast", Static)
    assert toast.display
    assert "no longer exists" in _widget_text(toast)
    assert ctx["launcher"].opened_paths == []


@then("the header's type segment is shown in the cyan colour")
def _header_type_cyan(ctx):
    text, style = _rendered_segments(ctx["session"], "#artifact-viewer-kind")[0]
    assert _colour_of(style) == COLOURS["cyan"].lower()


@then("the header's id segment is shown in the dim colour, not cyan")
def _header_id_dim(ctx):
    text, style = _rendered_segments(ctx["session"], "#artifact-viewer-kind")[-1]
    assert _colour_of(style) == COLOURS["dim"].lower()
    assert _colour_of(style) != COLOURS["cyan"].lower()


@then(parsers.parse('the header\'s right-aligned segment reads "{expected}"'))
def _header_right_aligned_reads(ctx, expected):
    _, text, _ = _rendered_segment(ctx["session"], "#artifact-viewer-count")
    assert text.strip() == expected


@then("it displays as its own scrollable list, not as raw text")
def _displays_as_list(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, ListArtifactViewerScreen)
    table = screen.query_one(ArtifactListTable)
    assert table.row_count == 3


@then("every item can be reached")
def _every_item_reachable(ctx):
    session = ctx["session"]
    screen = session.app.screen
    table = screen.query_one(ArtifactListTable)
    text = "\n".join(_painted_lines(session, table))
    assert "item 39" in text


@then("the artifact list reappears with that artifact still selected")
def _artifact_list_reappears_selected(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    table = screen.query_one(ArtifactsTable)
    assert table.cursor_row == ctx["selected_index"]


@then("the backlog is shown in place of the viewer")
def _backlog_shown_in_place_of_viewer(ctx):
    session = ctx["session"]
    assert not isinstance(session.app.screen, (NodeHubScreen, ArtifactViewerScreen))
    assert session.app.query_one(BacklogView).display


@then(
    "the status bar is not blank, showing the pool status, the Claude-availability status, "
    "and the installed version"
)
def _status_bar_not_blank(ctx):
    session = ctx["session"]
    assert isinstance(session.app.screen, ArtifactViewerScreen)
    _, pool_text, _ = _rendered_segment(session, "#status-pool")
    _, claude_text, _ = _rendered_segment(session, "#status-claude")
    _, version_text, _ = _rendered_segment(session, "#status-version")
    assert pool_text.strip() != ""
    assert claude_text.strip() != ""
    assert version_text.strip() == "v%s" % __version__


@then("the status bar shows the upgrade indicator with that version")
def _shows_upgrade_indicator(ctx):
    widget, text, style = _rendered_segment(ctx["session"], "#status-upgrade")
    assert widget.display
    assert text == "%s v%s available" % (
        FOOTER_GLYPHS["upgrade-available"].glyph, ctx["remote_version"]
    )
    assert _colour_of(style) == COLOURS["amber"].lower()


@then("the status bar reflects the changed state")
def _status_bar_reflects_changed_state(ctx):
    session = ctx["session"]
    _, pool_text, _ = _rendered_segment(session, "#status-pool")
    _, claude_text, _ = _rendered_segment(session, "#status-claude")
    assert pool_text == "%s pool running" % FOOTER_GLYPHS["pool-running"].glyph
    assert "claude unavailable" in claude_text
