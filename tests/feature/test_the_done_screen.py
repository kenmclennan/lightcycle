import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.adapters.tui.app import (
    DoneFilterInput,
    DoneTable,
    PickerOption,
    ProjectFilterPicker,
    ShortcutBar,
)
from lightcycle.adapters.tui.hub import NodeHubScreen
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-done-screen.feature")


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _launch_and_switch_to_done(ctx, store):
    ctx["store"] = store
    ctx["session"] = launch(make_test_container(store=store))
    ctx["session"].press("tab")
    ctx["session"].press("tab")


def _rendered_text(widget):
    strip = widget.render_line(0)
    return "".join(segment.text for segment in strip)


def _composited_text_at(ctx, widget):
    region = widget.region
    if region.height == 0:
        return ""
    compositor = ctx["session"].app.screen._compositor
    strips = compositor.render_strips()
    start, end = region.x, region.x + region.width
    return "".join(segment.text for segment in strips[region.y].crop(start, end))


def _colour_of(style):
    return style.color.get_truecolor().hex.lower()


def _picker_option_by_label(screen, label):
    from lightcycle.adapters.tui.design_system import CURSOR_GLYPH

    for option in screen.query(PickerOption):
        text = _rendered_text(option.query_one("#picker-option-label"))
        if text.replace(CURSOR_GLYPH.glyph, "").strip() == label:
            return option
    raise AssertionError("no picker option labelled %r" % label)


def _assert_picker_option_count(ctx, label, expected):
    screen = ctx["session"].app.screen
    option = _picker_option_by_label(screen, label)
    count_widget = option.query_one(".picker-option-count")
    assert _rendered_text(count_widget).strip() == str(expected)


@given("the store has a closed item")
def _store_has_closed_item(ctx):
    store = FakeStore()
    item = store.create_item("closed item", "a description")
    store.complete_node(item, "merged")
    ctx["item_id"] = item
    ctx["store"] = store


@given("the store has an open item and a closed item")
def _store_open_and_closed(ctx):
    store = FakeStore()
    closed = store.create_item("closed item", "a description")
    store.complete_node(closed, "merged")
    store.create_item("open item", "a description")
    ctx["item_id"] = closed
    ctx["store"] = store


@given(parsers.parse(
    'the store has two items, closed in this order: "{first}", then "{second}"'
))
def _store_two_items_closed_in_order(ctx, first, second):
    store = FakeStore()
    first_id = store.create_item(first, "a description")
    store.complete_node(first_id, "merged")
    second_id = store.create_item(second, "a description")
    store.complete_node(second_id, "merged")
    ctx["first_id"] = first_id
    ctx["second_id"] = second_id
    ctx["store"] = store


@given("the store has no closed items anywhere")
def _store_no_closed_items(ctx):
    ctx["store"] = FakeStore()


@given(parsers.parse(
    'the store has closed items, all belonging to a project other than "{project}"'
))
def _store_closed_items_other_project(ctx, project):
    store = FakeStore()
    store.add_project("other-project")
    for i in range(2):
        item = store.create_item("item %d" % i, "a description")
        store.add_artifact(item, "repo", "other-project")
        store.complete_node(item, "merged")
    ctx["store"] = store


@given(parsers.parse(
    'the done tab is shown with the registered projects "{project_a}" and "{project_b}", '
    "each with a closed item"
))
def _done_shown_two_projects(ctx, project_a, project_b):
    store = FakeStore()
    store.add_project(project_a)
    store.add_project(project_b)
    item_a = store.create_item("item a", "a description")
    store.add_artifact(item_a, "repo", project_a)
    store.complete_node(item_a, "merged")
    item_b = store.create_item("item b", "a description")
    store.add_artifact(item_b, "repo", project_b)
    store.complete_node(item_b, "merged")
    short_a = project_a.rsplit("/", 1)[-1]
    short_b = project_b.rsplit("/", 1)[-1]
    ctx["expected_counts"] = {short_a: 1, short_b: 1}
    ctx["expected_total"] = 2
    _launch_and_switch_to_done(ctx, store)


@given(parsers.parse(
    'the done tab is shown with the registered projects "{project_a}" and "{project_b}", '
    'each with a closed item titled "{title}"'
))
def _done_shown_two_projects_shared_title(ctx, project_a, project_b, title):
    store = FakeStore()
    store.add_project(project_a)
    store.add_project(project_b)
    item_a = store.create_item(title, "a description")
    store.add_artifact(item_a, "repo", project_a)
    store.complete_node(item_a, "merged")
    item_b = store.create_item(title, "a description")
    store.add_artifact(item_b, "repo", project_b)
    store.complete_node(item_b, "merged")
    _launch_and_switch_to_done(ctx, store)


@given("the done tab is shown with a closed item")
def _done_shown_with_closed_item(ctx):
    store = FakeStore()
    item = store.create_item("closed item", "a description")
    store.complete_node(item, "merged")
    ctx["item_id"] = item
    _launch_and_switch_to_done(ctx, store)


@given(parsers.parse('the done tab is shown with the closed items "{title_a}" and "{title_b}"'))
def _done_shown_two_titled_items(ctx, title_a, title_b):
    store = FakeStore()
    item_a = store.create_item(title_a, "a description")
    store.complete_node(item_a, "merged")
    item_b = store.create_item(title_b, "a description")
    store.complete_node(item_b, "merged")
    ctx["item_ids"] = {title_a: item_a, title_b: item_b}
    _launch_and_switch_to_done(ctx, store)


@when("I switch to the done tab")
def _switch_to_done(ctx):
    if "session" not in ctx:
        ctx["session"] = launch(make_test_container(store=ctx["store"]))
        ctx["session"].press("tab")
        ctx["session"].press("tab")


@when(parsers.parse('the done tab is filtered to "{project}"'))
def _when_done_filtered(ctx, project):
    if "session" not in ctx:
        _launch_and_switch_to_done(ctx, ctx["store"])
    session = ctx["session"]
    session.app._done_project_filter = project
    session.run(session.app._refresh)
    session.pause()


@when("f is pressed")
def _press_f(ctx):
    ctx["session"].press("f")


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


@when("/ is pressed")
def _press_slash(ctx):
    ctx["session"].press("/")


@when(parsers.parse('"{text}" is typed into the done search box'))
def _type_into_done_search_box(ctx, text):
    session = ctx["session"]
    for char in text:
        session.press(char)
    session.settle_done_filter()


@when("→ is pressed")
def _press_right(ctx):
    ctx["session"].press("right")


@when(parsers.parse("the shortcut at position {position:d} in the footer's shortcut line is read"))
def _read_shortcut(ctx, position):
    shortcut_bar = ctx["session"].app.query_one(ShortcutBar)
    ctx["shortcut"] = shortcut_bar.shortcuts[position - 1]


@then("the closed item is listed as a row")
def _closed_item_listed(ctx):
    table = ctx["session"].app.query_one(DoneTable)
    assert ctx["item_id"] in table.rows


@then("only the closed item is listed")
def _only_closed_item_listed(ctx):
    table = ctx["session"].app.query_one(DoneTable)
    assert [row.key.value for row in table.ordered_rows] == [ctx["item_id"]]


@then(parsers.parse('the rows appear in the order "{first}", "{second}"'))
def _rows_in_order(ctx, first, second):
    table = ctx["session"].app.query_one(DoneTable)
    titles = []
    for row in table.ordered_rows:
        cell = table.get_cell(row.key.value, "title")
        titles.append(cell.plain if hasattr(cell, "plain") else cell)
    assert titles == [first, second]


@then(parsers.parse('the message "{text}" is shown in place of the list'))
def _message_shown_in_place(ctx, text):
    session = ctx["session"]
    table = session.app.query_one(DoneTable)
    assert not table.display
    widget = session.app.query_one("#done-empty-overall")
    assert widget.display
    assert _rendered_text(widget).strip() == text


@then(parsers.parse(
    'the message "{text}" is shown, with "{project}" in the text colour and the rest of the '
    "message in the dim colour"
))
def _filtered_empty_message(ctx, text, project):
    from lightcycle.adapters.tui.design_system import COLOURS

    widget = ctx["session"].app.query_one("#done-empty-filtered-message")
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
    widget = ctx["session"].app.query_one("#done-empty-filtered-hint")
    assert widget.display
    assert _rendered_text(widget).strip() == text


@then(parsers.parse('the picker\'s header reads "{text}"'))
def _picker_header(ctx, text):
    widget = ctx["session"].app.screen.query_one("#picker-head")
    assert _rendered_text(widget).strip() == text


@then(parsers.parse('the picker shows "{label}" with the total item count'))
def _picker_shows_all_total(ctx, label):
    _assert_picker_option_count(ctx, label, ctx["expected_total"])


@then(parsers.parse('the picker shows "{label}" with its own item count'))
def _picker_shows_own_count(ctx, label):
    _assert_picker_option_count(ctx, label, ctx["expected_counts"][label])


@then("the picker is closed")
def _picker_closed(ctx):
    assert not isinstance(ctx["session"].app.screen, ProjectFilterPicker)


@then(parsers.parse('the done tab is filtered to "{project}"'))
def _done_filtered_to(ctx, project):
    widget = ctx["session"].app.query_one("#done-filter-left")
    assert _rendered_text(widget).strip() == project


@then(parsers.parse('only the done row under "{project}" is shown'))
def _only_done_row_under_project(ctx, project):
    table = ctx["session"].app.query_one(DoneTable)
    assert table.row_count == 1
    row_id = table.ordered_rows[0].key.value
    cell = table.get_cell(row_id, "project")
    text = cell.plain if hasattr(cell, "plain") else cell
    assert text == project


@then("the done search box has focus")
def _done_search_box_has_focus(ctx):
    session = ctx["session"]
    assert session.app.focused is session.app.query_one(DoneFilterInput)


@then("the done table has focus")
def _done_table_has_focus(ctx):
    session = ctx["session"]
    assert session.app.focused is session.app.query_one(DoneTable)


@then("the done search label is shown in the cyan colour")
def _done_search_label_cyan(ctx):
    from lightcycle.adapters.tui.design_system import COLOURS

    widget = ctx["session"].app.query_one("#done-search-label")
    strip = widget.render_line(0)
    style = next(s.style for s in strip if s.text.strip())
    assert _colour_of(style) == COLOURS["cyan"].lower()


@then("the done search label is not shown in the cyan colour")
def _done_search_label_not_cyan(ctx):
    from lightcycle.adapters.tui.design_system import COLOURS

    widget = ctx["session"].app.query_one("#done-search-label")
    strip = widget.render_line(0)
    style = next(s.style for s in strip if s.text.strip())
    assert _colour_of(style) != COLOURS["cyan"].lower()


@then(parsers.parse('only the done row matching "{needle}" is still shown'))
def _only_done_row_matching_still_shown(ctx, needle):
    table = ctx["session"].app.query_one(DoneTable)
    assert table.row_count == 1
    row_id = table.ordered_rows[0].key.value
    cell = table.get_cell(row_id, "title")
    text = cell.plain if hasattr(cell, "plain") else cell
    assert needle.lower() in text.lower()


@then("the done search value and the done project value start at the same column")
def _done_search_and_project_value_aligned(ctx):
    search_input = ctx["session"].app.query_one("#done-filter-text")
    project_value = ctx["session"].app.query_one("#done-filter-left")
    assert search_input.content_region.x == project_value.content_region.x, (
        "done search value starts at column %d but done project value starts at column %d"
        % (search_input.content_region.x, project_value.content_region.x)
    )


@then(parsers.parse('its key is "{key}"'))
def _shortcut_key(ctx, key):
    assert ctx["shortcut"][0] == key


@then(parsers.parse('its action is "{action}"'))
def _shortcut_action(ctx, action):
    assert ctx["shortcut"][1] == action


@then("the footer's composited frame shows each search-focused shortcut, in order")
def _footer_composited_search_shortcuts(ctx):
    from lightcycle.adapters.tui.design_system import DONE_SEARCH_SHORTCUTS

    bar = ctx["session"].app.query_one("#shortcut-bar")
    row = _composited_text_at(ctx, bar)
    last_index = -1
    for key, action in DONE_SEARCH_SHORTCUTS:
        key_index = row.index(key, last_index + 1)
        last_index = row.index(action, key_index + len(key))


@then("its hub opens for the closed item")
def _hub_opens_for_closed_item(ctx):
    session = ctx["session"]
    screen = session.app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._node_id == ctx["item_id"]


@then(parsers.parse('its hub opens for the done item matching "{needle}"'))
def _hub_opens_for_done_item_matching(ctx, needle):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    expected_id = next(
        item_id for title, item_id in ctx["item_ids"].items() if needle.lower() in title.lower()
    )
    assert screen._node_id == expected_id
