import json

import pytest

from lightcycle.adapters.log_parser import MAX_LOG_LINE_CHARS, LogLineParser
from lightcycle.adapters.tui.app import BacklogTable, DoneTable, PriorityTable
from lightcycle.adapters.tui.hub import (
    CONTEXT_EMPTY_MESSAGE,
    DETAIL_EMPTY_MESSAGE,
    detail_value_is_block,
)
from tests.support.screen_render import (
    CONTEXT_REFLECTION, CONTEXT_SPEC_REPORT, DEFAULT_SIZE, GATE_DESCRIPTION,
    GATE_FINDINGS_LINES, MERGE_PR, MERGE_REPORT, SCREENS, UNRENDERABLE, _LOG_EXCERPT,
    _hub_gate_merge, _plain_row, render,
)


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


@pytest.mark.parametrize("width", [100, 140])
def test_report_with_slow_steps_paints_the_count_and_the_keyed_step_row_at_each_width(width):
    rows = render("report#with-slow-steps", size=(width, 30)).split("\n")
    count_at = next(i for i, row in enumerate(rows) if "Slow Steps" in row and "1" in row)

    assert "Escalations" in rows[count_at - 1]
    assert "LC-730.12" in rows[count_at + 1]
    assert "review-code - 52m active - waiting" in rows[count_at + 1]
    assert "Starting Backlog Size" in rows[count_at + 2]


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


def test_a_pool_holding_state_renders_the_hold_segment_in_the_footer():
    frame = render("priority-list#pool-holding")

    assert "holding · 2/5 · memory" in frame
    assert "(pool)" not in frame
    assert "(machine)" not in frame


def test_a_config_edited_after_launch_renders_the_restart_hint_in_the_footer():
    frame = render("priority-list#config-changed")

    assert "config changed - restart to apply" in frame
    assert "config changed" not in render("priority-list#normal")


def test_an_unpriced_step_shows_not_recorded_and_unpriced_basis_never_a_dollar_figure():
    frame = render("hub#cost-step-unpriced", size=(100, 30))

    assert "$0.00" not in frame
    assert "not recorded" in frame
    assert "unpriced" in frame


def test_an_item_rollup_including_an_unpriced_step_notes_the_unpriced_count():
    frame = render("hub#cost-item", size=(100, 30))

    assert "(1 unpriced)" in frame


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
    from tests.support.screen_render import _at, _launch, _plain_row, _populated_store

    class BareHubScreen(Screen):
        def compose(self):
            yield HubHeader(id="hub-header")

    narrow = (77, 30)
    store, scan, coding = _populated_store()
    store.record_usage("LC-143.3.1", 1000, 200, 0, 0, 2.91, "list", None)
    store.record_attribution("LC-143.3.1", 20, {})
    store.complete_node(coding, "done")
    store.complete_node(scan, "done")
    store._records[scan]["closed_at"] = _at(-100000)

    session = _launch(store, size=narrow)
    try:
        session.run(lambda: session.app.push_screen(BareHubScreen()))
        header = session.run(lambda: session.app.screen.query_one(HubHeader))
        context = session.run(lambda: header.query_one("#hub-context"))
        assert context.size.width == 0, "widget has not been laid out yet - this is the true first paint"

        flow_service = session.app._container.flow_service()
        node = store.get_node(scan)
        data = build_header(store, node, session.app._now().isoformat(), flow_service, False, True)
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


def test_a_gate_presenting_pr_with_no_pr_yet_opens_on_the_context_not_the_description():
    frame = render("hub#gate-presents-pr", size=(100, 30))

    assert "INPUTS" in frame
    assert "OUTPUTS" in frame
    assert "RECORDS" in frame
    assert GATE_DESCRIPTION in frame


def test_a_gate_presenting_description_opens_on_the_detail_entry_for_it():
    frame = render("hub#gate-presents-description", size=(100, 30))

    assert "IN:DESCRIPTION" in frame
    assert GATE_DESCRIPTION in frame


def test_a_gate_presenting_findings_shows_the_findings_block_under_its_key():
    frame = render("hub#gate-presents-findings", size=(100, 30))

    assert "IN:FINDINGS" in frame
    for line in GATE_FINDINGS_LINES:
        assert line in frame
    assert GATE_DESCRIPTION not in frame


def test_a_gate_declaring_detail_for_findings_shows_the_same_block():
    frame = render("hub#gate-declares-findings-detail", size=(100, 30))

    assert "IN:FINDINGS" in frame
    for line in GATE_FINDINGS_LINES:
        assert line in frame


def test_a_findings_block_sits_on_the_rows_under_its_key():
    rows = render("hub#gate-presents-findings", size=(100, 30)).split("\n")
    key_row = next(i for i, row in enumerate(rows) if "IN:FINDINGS" in row)

    assert GATE_FINDINGS_LINES[0] not in rows[key_row]
    assert GATE_FINDINGS_LINES[0] in rows[key_row + 1]


def test_a_merge_gate_detail_shows_the_pr_and_the_reviews_report():
    frame = render("hub#gate-merge", size=(100, 30))

    assert MERGE_PR in frame
    assert MERGE_REPORT in frame
    assert "IN:REPORT" in frame


def test_a_merge_gate_listing_an_input_it_lacks_shows_it_blank_beside_the_valued_ones():
    rows = render("hub#gate-merge-missing-input", size=(100, 30)).split("\n")

    assert any("PR" in r and MERGE_PR in r for r in rows)
    assert any("IN:REPORT" in r and MERGE_REPORT in r for r in rows)
    findings = next(r for r in rows if "IN:FINDINGS" in r)
    assert findings.strip("│ ") == "IN:FINDINGS"


def test_a_parked_script_stage_with_declared_detail_shows_its_reason_not_the_empty_message():
    frame = render("hub#script-parked", size=(140, 30))

    assert "check exited 1: 2 source files failed validation" in frame
    assert DETAIL_EMPTY_MESSAGE not in frame


def test_a_closed_step_without_frozen_inputs_shows_the_reconstructed_header_and_the_table():
    frame = render("hub#step-done-context-reconstructed", size=(140, 30))

    assert "Reconstructed from the item's current state" in frame
    assert "this step closed before inputs were frozen at claim." in frame
    assert "INPUTS" in frame
    assert "Audit found one issue." in frame
    assert CONTEXT_EMPTY_MESSAGE not in frame


def test_a_frozen_closed_step_shows_no_reconstructed_header():
    frame = render("hub#step-done-context", size=(140, 30))

    assert "Reconstructed from" not in frame


def test_a_done_agent_step_opens_on_context_with_inputs_outputs_and_records():
    frame = render("hub#step-done-context", size=(100, 45))

    for header in ("INPUTS", "OUTPUTS", "RECORDS"):
        assert header in frame
    assert "INPUTS (live" not in frame
    inputs_row = next(r for r in frame.split("\n") if CONTEXT_SPEC_REPORT in r)
    assert "report (p1)" in inputs_row
    assert "Audit found one issue." in frame
    assert "The scan skips symlinked checkouts." in frame
    assert "- tests: no symlink case" in frame
    assert "See the scan spec or https://example.test/scan." in frame
    assert CONTEXT_REFLECTION in frame
    assert "guidance-delivered" in frame


def test_a_value_of_80_characters_is_a_line_and_81_is_a_block():
    assert not detail_value_is_block("x" * 80)
    assert detail_value_is_block("x" * 81)
    assert detail_value_is_block("one\ntwo")
    assert not detail_value_is_block("")


def test_an_80_character_report_renders_on_its_keys_row_and_81_under_it():
    for length, same_row in ((80, True), (81, False)):
        report = "r" * length
        session = _hub_gate_merge((100, 30), report=report)
        try:
            strips = session.run(lambda: session.app.screen._compositor.render_strips())
            rows = [_plain_row(strip) for strip in strips]
        finally:
            session.close()
        key_row = next(i for i, row in enumerate(rows) if "IN:REPORT" in row)
        assert (report in rows[key_row]) is same_row, length


def test_a_block_body_wraps_wider_on_a_wider_terminal():
    report = " ".join("word%d" % n for n in range(60))
    widths = {}
    for width in (100, 140):
        session = _hub_gate_merge((width, 30), report=report)
        try:
            strips = session.run(lambda: session.app.screen._compositor.render_strips())
            rows = [_plain_row(strip) for strip in strips]
        finally:
            session.close()
        body = next(row for row in rows if "word0" in row)
        widths[width] = len(body.strip("│ "))
    assert widths[140] > widths[100]


def test_a_narrow_terminal_stacks_the_context_table():
    frame = render("hub#step-done-context", size=(56, 40))
    rows = frame.split("\n")

    assert any("INPUTS" in row for row in rows)
    key_row = next(i for i, row in enumerate(rows) if row.startswith("│ findings"))
    assert "The scan skips" not in rows[key_row]
    assert any("The scan skips" in row for row in rows[key_row + 1:key_row + 4])
    assert any("report (p1)" in row for row in rows)


@pytest.mark.parametrize("state", sorted(name for name in SCREENS if name.startswith("hub#")))
def test_no_step_tab_is_blank_on_first_open(state):
    rows = render(state, size=(100, 30)).split("\n")
    separators = [i for i, row in enumerate(rows) if row.startswith("│─")]
    body = rows[separators[1] + 1:separators[2]]

    assert any(row.strip("│ ") for row in body), state


def test_a_running_agent_opens_on_its_log():
    frame = render("hub#active-log", size=(100, 30))

    assert "Nothing live to stream." not in frame


def test_a_known_budget_above_the_reserve_renders_the_dim_remaining_segment():
    frame = render("priority-list#github-budget")

    assert "github 4261/5000 · resets " in frame
    assert "budget low" not in frame


def test_a_low_budget_renders_the_amber_hold_segment_in_the_footer():
    frame = render("priority-list#github-budget-low")

    assert "github budget low · 312 left · resets " in frame
    assert "github 312/5000" not in frame


def test_the_low_budget_segment_is_painted_in_the_hold_colour_not_dim():
    from lightcycle.adapters.tui.design_system import COLOURS

    coloured = render("priority-list#github-budget-low", colour=True)
    plain = render("priority-list#github-budget")
    rgb = COLOURS["amber"].lstrip("#")
    amber = "\x1b[38;2;%d;%d;%d" % tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4))

    assert amber in coloured.split("github budget low")[0].rsplit("\n", 1)[-1]
    assert "github budget low" not in plain


def test_no_reading_hides_the_github_segment():
    frame = render("priority-list#normal")

    assert "github " not in frame.split("\n")[-3]
