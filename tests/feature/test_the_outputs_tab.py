import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.hub import (
    OUTPUTS_CONTINUATION_INDENT,
    OutputsTable,
    NodeHubScreen,
    TextArtifactViewerScreen,
)
from lightcycle.adapters.tui.row_grid import (
    FLEXIBLE_MINIMUM, atomic_column_width, scrollbar_reservation_width,
)
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-outputs-tab.feature")


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


def _row_lines(table, row_key):
    y = 0
    target = None
    height = 1
    for r in table.ordered_rows:
        if r.key.value == row_key:
            target = y
            height = r.height
            break
        y += r.height
    assert target is not None
    return [table.render_line(target + i) for i in range(height)]


def _open_hub_on_outputs(ctx, node_id):
    session = ctx["session"]
    screen = NodeHubScreen(session.app.container, node_id, session.app._now, initial_tab="outputs")
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    ctx["node_id"] = node_id
    return session


def _launch_with_item(ctx, artifacts, size=None):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    for atype, value, kind, internal in artifacts:
        store.add_artifact(item, atype, value, internal=internal, kind=kind)
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store), size=size)
    _open_hub_on_outputs(ctx, item)
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
        ("note", "org/repo", "text", False),
    ])


@given("a node has no non-internal artifacts")
def _no_viewable_artifacts(ctx):
    _launch_with_item(ctx, [])


@given("an item has no non-internal artifacts")
def _item_has_no_non_internal_artifacts(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["session"] = launch(make_test_container(store=store))


@given(parsers.parse('a node has an artifact of type "{atype}"'))
def _artifact_of_type(ctx, atype):
    ctx["artifact_type"] = atype
    _launch_with_item(ctx, [(atype, "some value", "text", False)])


_ARTIFACTS_TYPE = "code-review-findings"
_ARTIFACTS_VALUE = "A value long enough to need a continuation line for real"
_ARTIFACTS_NUM_COLUMNS = 4


def _artifacts_stack_terminal_width(mode):
    atomic_total = (
        atomic_column_width([_ARTIFACTS_TYPE + "  "]) + atomic_column_width(["  "])
        + max(1, atomic_column_width([""]))
    )
    floor_width = max(atomic_total, OUTPUTS_CONTINUATION_INDENT + FLEXIBLE_MINIMUM)
    breakpoint_width = atomic_total + FLEXIBLE_MINIMUM
    row_budget = floor_width if mode == "just wide enough to clear the floor" else breakpoint_width - 1
    return row_budget + 2 + 2 * _ARTIFACTS_NUM_COLUMNS + scrollbar_reservation_width(OutputsTable)


@given(parsers.parse(
    "an artifact row whose type and the flexible minimum for value together exceed the row "
    "budget, on a terminal {mode}"
))
def _artifact_row_forces_stacking(ctx, mode):
    ctx["artifact_type"] = _ARTIFACTS_TYPE
    ctx["artifact_value"] = _ARTIFACTS_VALUE
    _launch_with_item(
        ctx, [(_ARTIFACTS_TYPE, _ARTIFACTS_VALUE, "text", False)],
        size=(_artifacts_stack_terminal_width(mode), 24),
    )


@given("the artifact list has more than one entry")
def _more_than_one_entry(ctx):
    _launch_with_item(ctx, [
        ("note", "org/a", "text", False),
        ("branch", "feat/a", "text", False),
    ])


@given("the selection is not on the first entry")
def _selection_not_first(ctx):
    ctx["session"].press("down")


@given("an artifact is selected in the list")
def _artifact_selected(ctx):
    _launch_with_item(ctx, [("design", "designs/x.md", "text", False)])


@given("I opened the artifact list from a node's hub view")
def _opened_artifact_list_from_hub(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    store.add_artifact(item, "spec", "specs/x.md")
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    session = _open_hub_on_outputs(ctx, item)
    ctx["hub_screen"] = session.app.screen


@when("I open its Outputs tab")
def _open_artifacts_tab(ctx):
    pass


@when("its hub is open")
def _hub_is_open(ctx):
    session = ctx["session"]
    screen = NodeHubScreen(session.app.container, ctx["item_id"], session.app._now)
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    ctx["node_id"] = ctx["item_id"]


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
    table = ctx["session"].app.screen.query_one(OutputsTable)
    assert table.row_count == 3
    types = [_rendered_cell_text(table, str(i), "name") for i in range(3)]
    assert types == ["spec", "branch", "pr"]


@then(parsers.parse('that artifact is shown labeled by its full type "{atype}"'))
def _artifact_labeled_full_type(ctx, atype):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    lines = _row_lines(table, "0")
    assert len(lines) == 1
    text = _rendered_cell_text(table, "0", "name")
    assert text == atype


@then("the type remains alone on the row's first line")
def _type_alone_on_first_line(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    lines = _row_lines(table, "0")
    assert len(lines) > 1
    first_line_text = "".join(segment.text for segment in lines[0])
    assert ctx["artifact_type"] in first_line_text
    assert ctx["artifact_value"] not in first_line_text


def _artifacts_stacked_cell_text(table, strip):
    pad = table.cell_padding
    column = table.ordered_columns[0]
    start = pad
    end = start + column.width
    return "".join(segment.text for segment in strip.crop(start, end))


@then(parsers.parse("the value appears on a continuation line indented {indent:d} characters"))
def _value_continuation_indented(ctx, indent):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    lines = _row_lines(table, "0")
    assert len(lines) > 1
    words = []
    for line in lines[1:]:
        text = _artifacts_stacked_cell_text(table, line)
        stripped = text.rstrip()
        leading = len(stripped) - len(stripped.lstrip(" "))
        assert leading == indent
        words.extend(stripped.strip().split())
    assert words == ctx["artifact_value"].split()
    ctx["_continuation_words"] = words


@then("no fragment of the value's prose is split mid-word")
def _no_mid_word_split_artifacts(ctx):
    assert ctx["_continuation_words"] == ctx["artifact_value"].split()


@then("only the non-internal artifact is shown")
def _only_non_internal_shown(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    assert table.row_count == 1
    assert _rendered_cell_text(table, "0", "name") == "note"


@then("the internal artifact does not appear")
def _internal_does_not_appear(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    types = [_rendered_cell_text(table, str(i), "name") for i in range(table.row_count)]
    assert "reflection" not in types


@then("a calm message is shown in place of the list, not a blank area")
def _calm_message_shown(ctx):
    screen = ctx["session"].app.screen
    assert not screen.query_one(OutputsTable).display
    empty = screen.query_one("#hub-outputs-empty", Static)
    assert empty.display
    assert _widget_text(empty) != ""


@then("the Outputs tab is present, alongside Description and Workflow")
def _artifacts_tab_present(ctx):
    screen = ctx["session"].app.screen
    assert _widget_text(screen.query_one("#hub-tab-description", Static)) == "Description"
    assert _widget_text(screen.query_one("#hub-tab-workflow", Static)) == "Workflow"
    assert _widget_text(screen.query_one("#hub-tab-outputs", Static)) == "Outputs"


@then("the selection has moved to the next entry")
def _selection_moved_next(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    assert table.cursor_row == 1


@then("the selection has moved to the previous entry")
def _selection_moved_previous(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    assert table.cursor_row == 0


@then("it opens in the viewer appropriate for its kind")
def _opens_in_appropriate_viewer(ctx):
    assert isinstance(ctx["session"].app.screen, TextArtifactViewerScreen)


@then("the hub view reappears as it was")
def _hub_view_reappears(ctx):
    assert not isinstance(ctx["session"].app.screen, NodeHubScreen)


_DECLARING_METAS = {
    "spec-writer": {"model": "sonnet", "step": "spec", "produces": {"spec": "optional"}},
    "auditor": {"model": "sonnet", "step": "audit", "produces": {"findings": "optional"}},
}


def _launch_declaring(ctx, store):
    from tests.support.fake_fs import FakeFs

    ctx["store"] = store
    ctx["session"] = launch(
        make_test_container(store=store, workflow_bundle=FakeFs(metas=_DECLARING_METAS))
    )
    return ctx["session"]


def _row_text(table, index):
    return "".join(segment.text for segment in table.render_line(index))


@given("an item with a spec, a spec-phase PR, a code-phase PR and a spec reworked in a second pass")
def _item_with_spec_prs_and_rework(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description", workflow="o/w@abc")
    first_pass = store.open_pass(item)
    spec_1 = store.create_step(stage="spec", role="agent", item=item)
    store.set_step_pass(spec_1, first_pass)
    store.add_artifact(spec_1, "spec", "specs/v1.md")
    store.add_artifact(spec_1, "reflection", "private note", internal=True)
    store.add_artifact(spec_1, "session-id", "abc")
    spec_run = store.open_run(item, first_pass, "spec")
    store.set_pr(spec_run, "https://gh/pr/10")
    second_pass = store.open_pass(item)
    spec_2 = store.create_step(stage="spec", role="agent", item=item)
    store.set_step_pass(spec_2, second_pass)
    store.add_artifact(spec_2, "spec", "specs/v2.md")
    code_run = store.open_run(item, second_pass, "code")
    store.set_pr(code_run, "https://gh/pr/11")
    ctx["item"] = item
    session = _launch_declaring(ctx, store)
    _open_hub_on_outputs(ctx, item)
    return session


@given("a scheduled item with a findings output on its step")
def _scheduled_item_with_findings(ctx):
    store = FakeStore()
    item = store.create_item("Audit", "a description", workflow="o/w@abc")
    pid = store.open_pass(item)
    step = store.create_step(stage="audit", role="agent", item=item)
    store.set_step_pass(step, pid)
    store.add_artifact(step, "findings", "the audit digest")
    ctx["item"] = item
    ctx["step"] = step
    ctx["pass_id"] = pid
    _launch_declaring(ctx, store)
    _open_hub_on_outputs(ctx, item)


@then('the rows are the spec showing its newest value with "+1", then "pr (spec)", then "pr (code)"')
def _rows_are_spec_and_prs(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    assert table.row_count == 3
    names = [_rendered_cell_text(table, str(i), "name") for i in range(3)]
    assert names == ["spec +1", "pr (spec)", "pr (code)"]
    assert _rendered_cell_text(table, "0", "value") == "specs/v2.md"
    assert _rendered_cell_text(table, "1", "value") == "https://gh/pr/10"
    assert _rendered_cell_text(table, "2", "value") == "https://gh/pr/11"


@then("no reflection, session or guidance row appears")
def _no_bookkeeping_rows(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    text = " ".join(_row_text(table, i) for i in range(table.row_count))
    for banned in ("reflection", "session", "guidance", "abc", "private note"):
        assert banned not in text


@when("space is pressed on the spec row")
def _space_on_spec_row(ctx):
    ctx["session"].press("space")


@then("the older spec version appears directly under the spec row, indented")
def _older_version_under_row(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    assert table.row_count == 4
    assert _rendered_cell_text(table, "0", "value") == "specs/v2.md"
    assert _rendered_cell_text(table, "1", "name") == "spec"
    assert _rendered_cell_text_at(table, table.render_line(1), "name").startswith("  spec")
    assert _rendered_cell_text(table, "1", "value") == "specs/v1.md"
    assert _rendered_cell_text(table, "1", "pass") == "p1"
    assert _rendered_cell_text(table, "0", "pass") == "p2"


@then('there is one "findings" row showing its producing step and pass')
def _one_findings_row(ctx):
    table = ctx["session"].app.screen.query_one(OutputsTable)
    assert table.row_count == 1
    assert _rendered_cell_text(table, "0", "name") == "findings"
    assert _rendered_cell_text(table, "0", "step") == ctx["step"]
    assert _rendered_cell_text(table, "0", "pass") == "p1"
    assert _rendered_cell_text(table, "0", "value") == "the audit digest"
