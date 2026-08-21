import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.adapters.tui.app import (
    BacklogTable,
    BacklogView,
    PickerOption,
    ProjectFilterPicker,
    ShortcutBar,
)
from lightcycle.adapters.tui.row_grid import FLEXIBLE_MINIMUM, GLYPH_WIDTHS, atomic_column_width
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-backlog-screen.feature")


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _launch_and_switch(ctx, store, size=None):
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store), size=size)
    ctx["session"].press("tab")


def _rendered_text(widget):
    strip = widget.render_line(0)
    return "".join(segment.text for segment in strip)


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


def _row_lines(table, row_id):
    y = 0
    target = None
    height = 1
    for r in table.ordered_rows:
        if r.key.value == row_id:
            target = y
            height = r.height
            break
        y += r.height
    assert target is not None
    return [table.render_line(target + i) for i in range(height)]


def _colour_of(style):
    return style.color.get_truecolor().hex.lower()


def _picker_option_by_label(screen, label):
    from lightcycle.adapters.tui.design_system import CURSOR_GLYPH

    for option in screen.query(PickerOption):
        text = _rendered_text(option.query_one("#picker-option-label"))
        if text.replace(CURSOR_GLYPH.glyph, "").strip() == label:
            return option
    raise AssertionError("no picker option labelled %r" % label)


@given("the store has a todo item")
def _store_has_todo_item(ctx):
    store = FakeStore()
    ctx["item_id"] = store.create_item("todo item")
    ctx["store"] = store


@given("the backlog is shown with a todo item")
def _backlog_shown_with_item(ctx):
    store = FakeStore()
    ctx["item_id"] = store.create_item("todo item")
    _launch_and_switch(ctx, store)


@given("the backlog is shown with more todo items than fit on one screen")
def _backlog_shown_many(ctx):
    def build_store():
        store = FakeStore()
        for i in range(60):
            store.create_item("todo %d" % i)
        return store

    ctx["build_store"] = build_store
    _launch_and_switch(ctx, build_store())


@given(parsers.parse(
    'the backlog is shown with a todo item whose repo is "{repo}" under the registered project "{project}"'
))
def _backlog_shown_tagged_item(ctx, repo, project):
    store = FakeStore()
    store.add_project(project)
    item = store.create_item("tagged item")
    store.add_artifact(item, "repo", repo)
    ctx["item_id"] = item
    _launch_and_switch(ctx, store)


@given("the backlog is shown with a todo item with no registered project")
def _backlog_shown_unscoped_item(ctx):
    store = FakeStore()
    item = store.create_item("unscoped item")
    ctx["item_id"] = item
    _launch_and_switch(ctx, store)


@given(parsers.parse('the backlog is shown with a todo item with id "{id}" ({source})'))
def _backlog_shown_item_with_id(ctx, id, source):
    store = FakeStore()
    item = store.create_item("todo item", id=id)
    ctx["item_id"] = item
    _launch_and_switch(ctx, store)


@given(parsers.parse('the backlog is shown with two todo items whose ids are "{id_a}" and "{id_b}"'))
def _backlog_shown_two_colliding_ids(ctx, id_a, id_b):
    store = FakeStore()
    ctx["id_a"] = store.create_item("todo a", id=id_a)
    ctx["id_b"] = store.create_item("todo b", id=id_b)
    _launch_and_switch(ctx, store)


_STACK_ID = "LC-1234.10"
_STACK_PROJECT = "lightcycle"
_STACK_TITLE = "A title long enough to need a continuation line for real"
_BACKLOG_NUM_COLUMNS = 4


def _backlog_stack_terminal_width(mode):
    glyph_total = GLYPH_WIDTHS["cursor"]
    atomic_values = {"id": [_STACK_ID], "project": [_STACK_PROJECT]}
    atomic_total = sum(max(1, atomic_column_width(v)) for v in atomic_values.values())
    first_line_width = glyph_total + atomic_total
    floor_width = max(first_line_width, glyph_total + FLEXIBLE_MINIMUM)
    breakpoint_width = first_line_width + FLEXIBLE_MINIMUM
    row_budget = floor_width if mode == "just wide enough to clear the floor" else breakpoint_width - 1
    return row_budget + 2 + 2 * _BACKLOG_NUM_COLUMNS


@given(parsers.parse(
    "a backlog row whose atomic and glyph columns leave less than the flexible minimum for the "
    "title, on a terminal {mode}"
))
def _backlog_row_forces_stacked(ctx, mode):
    store = FakeStore()
    item = store.create_item(_STACK_TITLE, id=_STACK_ID)
    store.add_artifact(item, "repo", _STACK_PROJECT)
    ctx["item_id"] = item
    _launch_and_switch(ctx, store, size=(_backlog_stack_terminal_width(mode), 24))


@given("the dashboard has launched")
def _given_dashboard_launched(ctx):
    ctx["session"] = launch(make_test_container(store=FakeStore()))


@given(parsers.parse(
    'the backlog is shown with the registered projects "{project_a}" and "{project_b}", each with backlogged items'
))
def _backlog_shown_two_projects(ctx, project_a, project_b):
    store = FakeStore()
    store.add_project(project_a)
    store.add_project(project_b)
    item_a = store.create_item("item a")
    store.add_artifact(item_a, "repo", project_a)
    item_b = store.create_item("item b")
    store.add_artifact(item_b, "repo", project_b)
    short_a = project_a.rsplit("/", 1)[-1]
    short_b = project_b.rsplit("/", 1)[-1]
    ctx["expected_counts"] = {short_a: 1, short_b: 1}
    ctx["expected_total"] = 2
    _launch_and_switch(ctx, store)


@given(parsers.re(r'the backlog is shown with the registered project "(?P<project>[^"]+)"$'))
def _backlog_shown_one_project(ctx, project):
    store = FakeStore()
    store.add_project(project)
    item = store.create_item("item")
    store.add_artifact(item, "repo", project)
    short = project.rsplit("/", 1)[-1]
    ctx["expected_counts"] = {short: 1}
    ctx["expected_total"] = 1
    _launch_and_switch(ctx, store)


@given(parsers.re(
    r'the backlog is shown with the registered project "(?P<project>[^"]+)" and '
    r'(?P<total>\d+) todo items in total, (?P<count>\d+) of them under "(?P=project)"'
))
def _backlog_shown_project_with_totals(ctx, project, total, count):
    total, count = int(total), int(count)
    store = FakeStore()
    store.add_project(project)
    for _ in range(count):
        item = store.create_item("under item")
        store.add_artifact(item, "repo", project)
    for i in range(total - count):
        store.create_item("other item %d" % i)
    short = project.rsplit("/", 1)[-1]
    ctx["expected_counts"] = {short: count}
    ctx["expected_total"] = total
    _launch_and_switch(ctx, store)


@given(parsers.parse(
    'the backlog is shown with the registered project "{project}" and no backlogged items under it'
))
def _backlog_shown_project_no_items(ctx, project):
    store = FakeStore()
    store.add_project(project)
    short = project.rsplit("/", 1)[-1]
    ctx["expected_counts"] = {short: 0}
    ctx["expected_total"] = 0
    _launch_and_switch(ctx, store)


@given(parsers.parse("the backlog is shown with {count:d} todo items"))
def _backlog_shown_n_items(ctx, count):
    store = FakeStore()
    for i in range(count):
        store.create_item("todo %d" % i)
    _launch_and_switch(ctx, store)


@given("the store has no todo items anywhere")
def _store_no_todo_items(ctx):
    ctx["store"] = FakeStore()


@given(parsers.parse('the store has todo items, all belonging to a project other than "{project}"'))
def _store_items_other_project(ctx, project):
    store = FakeStore()
    store.add_project("other-project")
    for i in range(2):
        item = store.create_item("item %d" % i)
        store.add_artifact(item, "repo", "other-project")
    ctx["store"] = store


@given(parsers.parse('the backlog is shown, filtered to "{project}", with no items matching that filter'))
def _backlog_shown_filtered_empty(ctx, project):
    store = FakeStore()
    store.add_project(project)
    store.add_project("other-project")
    other = store.create_item("other item")
    store.add_artifact(other, "repo", "other-project")
    ctx["filter_project"] = project
    _launch_and_switch(ctx, store)
    session = ctx["session"]
    session.app._backlog_project_filter = project
    session.run(session.app._refresh)
    session.pause()


@given("I switch to the backlog")
@when("I switch to the backlog")
def _switch_to_backlog(ctx):
    if "session" not in ctx:
        ctx["session"] = launch(make_test_container(store=ctx["store"]))
    ctx["session"].press("tab")


@when("that item is activated")
def _activate_item(ctx):
    ctx["store"].create_step("first step", step="build", role="coder", parent=ctx["item_id"])


@when("one poll interval elapses")
def _poll_interval_elapses(ctx):
    ctx["session"].poll_tick()


@when("Tab is pressed")
def _press_tab(ctx):
    ctx["session"].press("tab")


@when("Down is pressed")
def _press_down(ctx):
    ctx["session"].press("down")


@when("Up is pressed")
def _press_up(ctx):
    ctx["session"].press("up")


@when("Enter is pressed")
def _press_enter(ctx):
    ctx["session"].press("enter")


@when("Esc is pressed")
def _press_esc(ctx):
    ctx["session"].press("escape")


@when("Ctrl-D is pressed")
def _press_ctrl_d(ctx):
    ctx["session"].press("ctrl+d")


@when("Ctrl-U is pressed")
def _press_ctrl_u(ctx):
    ctx["session"].press("ctrl+u")


@when("f is pressed")
def _press_f(ctx):
    ctx["session"].press("f")


@when(parsers.parse('the backlog is filtered to "{project}"'))
def _when_backlog_filtered(ctx, project):
    if "session" not in ctx:
        ctx["session"] = launch(make_test_container(store=ctx["store"]))
    session = ctx["session"]
    session.press("tab")
    session.app._backlog_project_filter = project
    session.run(session.app._refresh)
    session.pause()


@when(parsers.parse('a todo item under "{project}" is created'))
def _create_item_under_project(ctx, project):
    item = ctx["store"].create_item("new item")
    ctx["store"].add_artifact(item, "repo", project)
    ctx["new_item_id"] = item


@when(parsers.parse("the shortcut at position {position:d} in the footer's shortcut line is read"))
def _read_shortcut(ctx, position):
    shortcut_bar = ctx["session"].app.query_one(ShortcutBar)
    ctx["shortcut"] = shortcut_bar.shortcuts[position - 1]


@then("the todo item is listed as a row")
def _todo_item_listed(ctx):
    table = ctx["session"].app.query_one(BacklogTable)
    assert ctx["item_id"] in table.rows


@then("the item no longer appears in the backlog")
def _item_gone(ctx):
    table = ctx["session"].app.query_one(BacklogTable)
    assert ctx["item_id"] not in table.rows


@then("the selection has moved forward by the same amount Page Down would move it")
def _ctrl_d_matches_page_down(ctx):
    actual = ctx["session"].app.query_one(BacklogTable).cursor_row
    compare = launch(make_test_container(store=ctx["build_store"]()))
    compare.press("tab")
    compare.press("pagedown")
    expected = compare.app.query_one(BacklogTable).cursor_row
    compare.close()
    assert actual == expected
    assert actual > 0


@then("the selection is back on the row it started on")
def _selection_back(ctx):
    table = ctx["session"].app.query_one(BacklogTable)
    assert table.cursor_row == 0


@then(parsers.parse('that item\'s row shows "{label}" as its project, in the cyan colour'))
def _row_shows_project_cyan(ctx, label):
    from lightcycle.adapters.tui.design_system import COLOURS

    table = ctx["session"].app.query_one(BacklogTable)
    cell = table.get_cell(ctx["item_id"], "project")
    assert cell.plain == label
    assert cell.style == COLOURS["cyan"]


@then("that item's row shows a blank project field")
def _row_blank_project(ctx):
    table = ctx["session"].app.query_one(BacklogTable)
    cell = table.get_cell(ctx["item_id"], "project")
    text = cell.plain if hasattr(cell, "plain") else cell
    assert text == ""


@then(parsers.parse('that item\'s row shows "{id}" as its id, in full, on one line'))
def _row_shows_id_in_full(ctx, id):
    table = ctx["session"].app.query_one(BacklogTable)
    row = next(r for r in table.ordered_rows if r.key.value == ctx["item_id"])
    assert row.height == 1
    lines = _row_lines(table, ctx["item_id"])
    text = _rendered_cell_text_at(table, lines[0], "id")
    assert text.strip() == id


@then("both ids are shown in full")
def _both_ids_shown_in_full(ctx):
    table = ctx["session"].app.query_one(BacklogTable)
    for key in ("id_a", "id_b"):
        row_id = ctx[key]
        row = next(r for r in table.ordered_rows if r.key.value == row_id)
        assert row.height == 1
        lines = _row_lines(table, row_id)
        text = _rendered_cell_text_at(table, lines[0], "id")
        assert text.strip() == row_id


@then("the two rows' ids are distinguishable from each other")
def _rows_ids_distinguishable(ctx):
    table = ctx["session"].app.query_one(BacklogTable)
    lines_a = _row_lines(table, ctx["id_a"])
    lines_b = _row_lines(table, ctx["id_b"])
    text_a = _rendered_cell_text_at(table, lines_a[0], "id").strip()
    text_b = _rendered_cell_text_at(table, lines_b[0], "id").strip()
    assert text_a != text_b


def _stacked_cell_text(table, strip):
    pad = table.cell_padding
    column = table.ordered_columns[0]
    start = pad
    end = start + column.width
    return "".join(segment.text for segment in strip.crop(start, end))


@then("the cursor, id and project remain on the row's first line, each padded to its atomic width")
def _backlog_stacked_first_line(ctx):
    table = ctx["session"].app.query_one(BacklogTable)
    lines = _row_lines(table, ctx["item_id"])
    assert len(lines) > 1
    content = _stacked_cell_text(table, lines[0])
    rest = content[GLYPH_WIDTHS["cursor"]:]
    assert rest.startswith(_STACK_ID)
    rest = rest[len(_STACK_ID):]
    assert rest.startswith(_STACK_PROJECT)


@then(parsers.parse(
    "the title appears on a continuation line indented {indent:d} characters - the row's "
    "glyph width, not where the title column starts in the unstacked grid"
))
def _backlog_stacked_continuation(ctx, indent):
    table = ctx["session"].app.query_one(BacklogTable)
    lines = _row_lines(table, ctx["item_id"])
    assert len(lines) > 1
    words = []
    for line in lines[1:]:
        text = _stacked_cell_text(table, line)
        stripped = text.rstrip()
        leading = len(stripped) - len(stripped.lstrip(" "))
        assert leading == indent
        words.extend(stripped.strip().split())
    assert words == _STACK_TITLE.split()
    ctx["_continuation_words"] = words


@then("no fragment of the title's prose is split mid-word")
def _backlog_no_mid_word_split(ctx):
    assert ctx["_continuation_words"] == _STACK_TITLE.split()


@then("the backlog is shown in place of the priority list")
def _backlog_shown_in_place(ctx):
    session = ctx["session"]
    assert session.app.query_one(BacklogView).display


@then("the priority list is shown in place of the backlog")
def _priority_shown_in_place(ctx):
    from lightcycle.adapters.tui.app import PriorityTable

    session = ctx["session"]
    assert not session.app.query_one(BacklogView).display
    priority_visible = (
        session.app.query_one(PriorityTable).display
        or session.app.query_one("#empty-state").display
    )
    assert priority_visible


@then(parsers.parse('the picker\'s header reads "{text}"'))
def _picker_header(ctx, text):
    widget = ctx["session"].app.screen.query_one("#picker-head")
    assert _rendered_text(widget).strip() == text


def _assert_picker_option_count(ctx, label, expected):
    screen = ctx["session"].app.screen
    option = _picker_option_by_label(screen, label)
    count_widget = option.query_one(".picker-option-count")
    assert _rendered_text(count_widget).strip() == str(expected)


@then(parsers.parse('the picker shows "{label}" with the total item count'))
def _picker_shows_all_total(ctx, label):
    _assert_picker_option_count(ctx, label, ctx["expected_total"])


@then(parsers.parse('the picker shows "{label}" with its own item count'))
def _picker_shows_own_count(ctx, label):
    _assert_picker_option_count(ctx, label, ctx["expected_counts"][label])


@then(parsers.parse('the picker shows "{label}" with count {count:d}'))
def _picker_shows_count(ctx, label, count):
    _assert_picker_option_count(ctx, label, count)


def _painted_option_row(ctx, label):
    screen = ctx["session"].app.screen
    option = _picker_option_by_label(screen, label)
    region = option.region
    strips = screen._compositor.render_strips()
    return "".join(
        seg.text for seg in strips[region.y].crop(region.x, region.x + region.width)
    )


def _assert_composited_option_count(ctx, label, expected):
    row = _painted_option_row(ctx, label)
    stripped = row.rstrip()
    assert stripped.endswith(str(expected)), (
        "row %r for %r does not end with its count %r" % (row, label, expected)
    )
    before_count = stripped[: -len(str(expected))]
    assert label in before_count
    assert before_count.rstrip() != before_count, (
        "row %r has no gap between %r's label and its count" % (row, label)
    )


@then(parsers.parse(
    'the picker\'s composited frame shows "{label}" with its total item count, '
    "right-aligned alongside its label"
))
def _picker_composited_total(ctx, label):
    _assert_composited_option_count(ctx, label, ctx["expected_total"])


@then(parsers.parse(
    'the picker\'s composited frame shows "{label}" with its own item count, '
    "right-aligned alongside its label"
))
def _picker_composited_own_count(ctx, label):
    _assert_composited_option_count(ctx, label, ctx["expected_counts"][label])


@then(parsers.parse('the picker\'s highlighted option is "{label}"'))
def _picker_highlighted_is(ctx, label):
    from lightcycle.adapters.tui.design_system import CURSOR_GLYPH

    screen = ctx["session"].app.screen
    highlighted = []
    for option in screen.query(PickerOption):
        text = _rendered_text(option.query_one("#picker-option-label"))
        if CURSOR_GLYPH.glyph in text:
            highlighted.append(text.replace(CURSOR_GLYPH.glyph, "").strip())
    assert highlighted == [label]


@then("the picker is closed")
def _picker_closed(ctx):
    assert not isinstance(ctx["session"].app.screen, ProjectFilterPicker)


@then(parsers.parse('the backlog is filtered to "{project}" without a poll interval elapsing'))
def _backlog_filtered_immediately(ctx, project):
    widget = ctx["session"].app.query_one("#backlog-filter-left")
    assert _rendered_text(widget).strip() == "PROJECT: %s" % project


@then('the backlog is still filtered to "All"')
def _backlog_still_all(ctx):
    widget = ctx["session"].app.query_one("#backlog-filter-left")
    assert _rendered_text(widget).strip() == "PROJECT: All"


@then(parsers.parse('the filter bar\'s left label reads "{text}"'))
def _filter_bar_left(ctx, text):
    widget = ctx["session"].app.query_one("#backlog-filter-left")
    assert _rendered_text(widget).strip() == text


@then(parsers.parse('the filter bar\'s right label reads "{text}"'))
def _filter_bar_right(ctx, text):
    widget = ctx["session"].app.query_one("#backlog-filter-right")
    assert _rendered_text(widget).strip() == text


@then("the filter bar does not show proj-b's own count")
def _filter_bar_no_breakdown(ctx):
    widget = ctx["session"].app.query_one("#backlog-filter-right")
    assert "proj-b" not in _rendered_text(widget)


@then(parsers.parse('the message "{text}" is shown in place of the list'))
def _message_shown_in_place(ctx, text):
    session = ctx["session"]
    table = session.app.query_one(BacklogTable)
    assert not table.display
    widget = session.app.query_one("#backlog-empty-overall")
    assert widget.display
    assert _rendered_text(widget).strip() == text


@then(parsers.parse(
    'the message "{text}" is shown, with "{project}" in the text colour and the rest of the message in the dim colour'
))
def _filtered_empty_message(ctx, text, project):
    from lightcycle.adapters.tui.design_system import COLOURS

    widget = ctx["session"].app.query_one("#backlog-empty-filtered-message")
    assert widget.display
    strip = widget.render_line(0)
    rendered = "".join(segment.text for segment in strip)
    assert rendered.strip() == text
    project_style = next(s.style for s in strip if project in s.text)
    other_style = next(s.style for s in strip if s.text.strip() and project not in s.text)
    assert _colour_of(project_style) == COLOURS["text"].lower()
    assert _colour_of(other_style) == COLOURS["dim"].lower()


@then(parsers.parse('the hint "{text}" is shown below the message'))
def _hint_shown(ctx, text):
    widget = ctx["session"].app.query_one("#backlog-empty-filtered-hint")
    assert widget.display
    assert _rendered_text(widget).strip() == text


@then("the list is shown in place of the message, with a row for the new item")
def _list_shown_with_new_item(ctx):
    session = ctx["session"]
    assert not session.app.query_one("#backlog-empty-filtered-message").display
    assert not session.app.query_one("#backlog-empty-filtered-hint").display
    table = session.app.query_one(BacklogTable)
    assert table.display
    assert ctx["new_item_id"] in table.rows


@then(parsers.parse('its key is "{key}"'))
def _shortcut_key(ctx, key):
    assert ctx["shortcut"][0] == key


@then(parsers.parse('its action is "{action}"'))
def _shortcut_action(ctx, action):
    assert ctx["shortcut"][1] == action


@then(parsers.parse('the picker\'s footer reads "{text}"'))
def _picker_footer_reads(ctx, text):
    widget = ctx["session"].app.screen.query_one("#picker-foot")
    assert _rendered_text(widget).strip() == text
