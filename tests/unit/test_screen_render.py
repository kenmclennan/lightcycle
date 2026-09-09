import json

import pytest

from lightcycle.adapters.log_parser import MAX_LOG_LINE_CHARS, LogLineParser
from lightcycle.adapters.tui.app import BacklogTable, DoneTable, PriorityTable
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

    assert "hub#workflow" in str(excinfo.value)


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
    assert "\x1b[48;2;" in coloured
    assert "\x1b[" not in plain


HEADER_FIELDS = ("14m", "code-await-merge", "lightcycle/spec-driven (abfb01d)")


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

    assert header_height("hub#workflow") < header_height("hub#gate")


DELIVERING_WORKFLOW = "lightcycle/spec-driven (abfb01d)"


def test_an_item_header_shows_the_delivering_workflow():
    assert DELIVERING_WORKFLOW in render("hub#done-item")


def test_a_step_header_shows_the_delivering_workflow():
    assert DELIVERING_WORKFLOW in render("hub#step-node")


def test_a_human_gate_step_header_still_shows_the_delivering_workflow():
    assert DELIVERING_WORKFLOW in render("hub#step-waiting")


def test_a_blocked_item_header_still_shows_the_delivering_workflow():
    assert DELIVERING_WORKFLOW in render("hub#blocked-dependency")


def test_a_node_with_no_workflow_renders_nothing_for_it():
    assert "lightcycle/" not in render("hub#no-workflow")


def test_a_narrow_header_drops_the_workflow_rather_than_wrapping_to_a_third_line():
    from lightcycle.adapters.tui.hub import HubHeader, HubTabStrip

    narrow = (77, 30)
    session = SCREENS["hub#done-item"](narrow)
    try:
        header = session.run(lambda: session.app.screen.query_one(HubHeader))
        tab_strip = session.run(lambda: session.app.screen.query_one(HubTabStrip))
        header_bottom = session.run(lambda: header.region.y + header.region.height)
        assert session.run(lambda: tab_strip.region.y) == header_bottom
        assert header.region.height == 2
    finally:
        session.close()

    rows = render("hub#done-item", size=narrow).split("\n")
    assert "recursive discovery by git remote" in rows[1]
    assert "Done · 4 steps" in rows[2]
    assert DELIVERING_WORKFLOW not in rows[1]
    assert DELIVERING_WORKFLOW not in rows[2]


def test_a_narrow_header_holds_the_guard_on_the_true_first_paint():
    from textual.screen import Screen

    from lightcycle.adapters.tui.hub import HubHeader, build_header
    from tests.support.screen_render import _launch, _plain_row, _populated_store

    class BareHubScreen(Screen):
        def compose(self):
            yield HubHeader(id="hub-header")

    narrow = (77, 30)
    store, scan, coding = _populated_store()
    store.record_usage("LC-143.3.1", 1000, 200, 0, 0, 2.91, "list", None)
    store.record_attribution("LC-143.3.1", 20, {})
    store.close(coding, "done")
    store.close(scan, "done")

    session = _launch(store, size=narrow)
    try:
        session.run(lambda: session.app.push_screen(BareHubScreen()))
        header = session.run(lambda: session.app.screen.query_one(HubHeader))
        context = session.run(lambda: header.query_one("#hub-context"))
        assert context.size.width == 0, "widget has not been laid out yet - this is the true first paint"

        flow_service = session.app._container.flow_service()
        node = store.get_node(scan)
        data = build_header(store, node, session.app._now().isoformat(), flow_service, False)
        session.run(lambda: header.update(data))
        session.pause()

        strips = session.run(lambda: session.app.screen._compositor.render_strips())
        frame = "\n".join(_plain_row(strip) for strip in strips)
    finally:
        session.close()

    assert "Done · 4 steps" in frame
    assert "lightcycle/" not in frame


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


@pytest.mark.parametrize("state, table_cls", [
    ("priority-list#stacked", PriorityTable),
    ("backlog#stacked", BacklogTable),
    ("done#stacked", DoneTable),
])
def test_the_stacked_named_states_actually_reach_stacked_mode_at_default_size(state, table_cls):
    session = SCREENS[state](DEFAULT_SIZE)
    try:
        table = session.app.query_one(table_cls)
        assert table._stacked_mode is True
    finally:
        session.close()


@pytest.mark.parametrize("state, project_text", [
    ("priority-list#stacked", "lightcycle-workflows"),
    ("backlog#stacked", "an-extremely-long-project-name-for-testing"),
    ("done#stacked", "an-extremely-long-project-name-for-testing"),
])
def test_the_stacked_named_states_show_a_readable_gap_before_the_project(state, project_text):
    frame = render(state, size=DEFAULT_SIZE)
    row = next(line for line in frame.split("\n") if project_text in line)
    before = row.split(project_text, 1)[0]
    assert before.endswith("  ")
