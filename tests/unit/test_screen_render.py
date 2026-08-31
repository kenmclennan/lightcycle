import json

import pytest

from lightcycle.adapters.log_parser import MAX_LOG_LINE_CHARS, LogLineParser
from tests.support.screen_render import DEFAULT_SIZE, SCREENS, UNRENDERABLE, _LOG_EXCERPT, render


@pytest.mark.parametrize("state", sorted(SCREENS))
def test_every_registered_state_renders_a_full_frame(state):
    frame = render(state, size=(100, 30))
    rows = frame.split("\n")

    assert len(rows) == 30
    assert rows[0].startswith("┌") and rows[0].endswith("┐")
    assert rows[-1].startswith("└") and rows[-1].endswith("┘")
    assert any(row.strip("│ ") for row in rows[1:-1])


@pytest.mark.parametrize("state", sorted(SCREENS))
def test_every_registered_screen_fits_the_viewport_without_scrolling(state):
    session = SCREENS[state](DEFAULT_SIZE)
    try:
        virtual_height = session.run(lambda: session.app.screen.virtual_size.height)
        viewport_height = session.run(lambda: session.app.screen.size.height)
        assert virtual_height <= viewport_height
    finally:
        session.close()


def test_a_state_the_codebase_cannot_render_names_the_ones_it_can():
    with pytest.raises(KeyError) as excinfo:
        render("hub#not-a-state")

    assert "hub#hierarchy" in str(excinfo.value)


def test_a_state_the_design_names_but_the_code_cannot_render_says_why():
    for state, reason in UNRENDERABLE.items():
        assert state not in SCREENS
        assert reason.strip()

    if not UNRENDERABLE:
        return

    state, reason = sorted(UNRENDERABLE.items())[0]
    with pytest.raises(KeyError) as excinfo:
        render(state)

    assert reason in str(excinfo.value)


def test_colour_carries_the_state_tokens_the_plain_frame_drops():
    plain = render("priority-list#normal")
    coloured = render("priority-list#normal", colour=True)

    assert "\x1b[38;2;" in coloured
    assert "\x1b[" not in plain


HEADER_FIELDS = ("project:", "theme:", "workflow:", "STEP:", "ROLE:", "ELAPSED:", "STATE:")


def test_the_demo_fixtures_exercise_every_header_field_the_hub_can_render():
    hub_frames = "\n".join(render(s) for s in sorted(SCREENS) if s.startswith("hub#"))
    missing = [f for f in HEADER_FIELDS if f not in hub_frames]

    assert not missing, (
        "no demo fixture populates %s, so no rendered frame can ever show it "
        "and every comparison against the design silently omits it" % missing
    )


def test_the_artifact_viewer_header_shows_its_kind_id_and_count():
    text_frame = render("artifact-viewer#text")
    list_frame = render("artifact-viewer#list")

    assert "findings · LC-45" in text_frame
    assert "watched-prs · LC-45" in list_frame
    assert "3 items" in list_frame


def test_a_long_description_never_grows_the_header():
    from lightcycle.adapters.tui.hub import HubHeader
    from tests.support.screen_render import LONG_DESCRIPTION, _launch, _long_description_store, _open_hub

    def header_height(description):
        store, item = _long_description_store(description=description)
        session = _open_hub(_launch(store, size=DEFAULT_SIZE), item, tab="description")
        try:
            return session.run(lambda: session.app.screen.query_one(HubHeader).region.height)
        finally:
            session.close()

    assert header_height(None) == header_height(LONG_DESCRIPTION)

    frame = render("hub#long-description")
    assert "Description" in frame


def test_header_height_reflects_the_fields_a_node_shows():
    from lightcycle.adapters.tui.hub import HubHeader, HubTabStrip

    def header_height(state):
        session = SCREENS[state](DEFAULT_SIZE)
        try:
            header = session.run(lambda: session.app.screen.query_one(HubHeader))
            tab_strip = session.run(lambda: session.app.screen.query_one(HubTabStrip))
            header_bottom = session.run(lambda: header.region.y + header.region.height)
            assert session.run(lambda: tab_strip.region.y) == header_bottom
            return header.region.height
        finally:
            session.close()

    assert header_height("hub#done-item") < header_height("hub#hierarchy")


def test_the_log_excerpt_fixture_is_real_captured_stream_json_past_the_bound():
    lines = _LOG_EXCERPT.split(b"\n")
    assert lines[-1] == b""
    for line in lines[:-1]:
        json.loads(line)

    parsed = LogLineParser().feed(_LOG_EXCERPT)
    assert any(len(entry.text) > MAX_LOG_LINE_CHARS for entry in parsed)


def test_the_log_pane_wraps_a_long_entry_instead_of_clipping_it():
    frame = render("hub#active-log")
    assert "resumes 14:32:00" in frame
