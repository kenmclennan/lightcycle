import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.hub import COST_NO_TOOLS_MESSAGE, _TAB_LABELS, CostPane, NodeHubScreen
from lightcycle.domain.pool import ToolUsage
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

scenarios("the-cost-tab.feature")

WIDE_SIZE = (100, 30)


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


def _field_value(ctx, key):
    rows = ctx["session"].app.screen._last_cost_rows
    for row_key, _label, value in rows:
        if row_key == key:
            return value
    raise AssertionError("field %r not found" % key)


def _field_keys(ctx):
    rows = ctx["session"].app.screen._last_cost_rows
    return [row_key for row_key, label, _value in rows if label]


def _breakdown_value(ctx, row_key):
    return _field_value(ctx, row_key)


def _push_hub(ctx, node_id):
    session = ctx["session"]
    screen = NodeHubScreen(session.app.container, node_id, session.app._now)
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    ctx["node_id"] = node_id
    return session


def _open_cost_tab(ctx):
    session = ctx["session"]
    screen = session.app.screen
    order = screen._tab_order
    current = order.index(screen._active_tab)
    target = order.index("cost")
    for _ in range((target - current) % len(order)):
        session.press("tab")


@given("a human step, its hub open")
def _human_step_hub_open(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="await-merge", role="human", parent=item)
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["session"] = launch(make_test_container(store=store))
    _push_hub(ctx, step)


@given("a step, its hub open")
def _step_hub_open(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["session"] = launch(make_test_container(store=store))
    _push_hub(ctx, step)


@given("an item, its hub open")
def _item_hub_open(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["session"] = launch(make_test_container(store=store))
    _push_hub(ctx, item)


@given("an agent step with a recorded cost, its hub open")
def _agent_step_with_cost(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    store.record_usage(step, 204_321, 2, 21_685_338, 555, 5.70, "list", None)
    store.record_attribution(step, 42, {})
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["session"] = launch(make_test_container(store=store), size=WIDE_SIZE)
    _push_hub(ctx, step)


@given("an agent step with a recorded cost and tool usage, its hub open")
def _agent_step_with_cost_and_tools(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    store.record_usage(step, 1000, 200, 0, 0, 1.5, "list", None)
    store.record_attribution(
        step, 10, {"Read": ToolUsage(calls=12, bytes=4300), "Bash": ToolUsage(calls=3, bytes=512)},
    )
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["session"] = launch(make_test_container(store=store), size=WIDE_SIZE)
    _push_hub(ctx, step)


@given("an agent step with a recorded cost and no tool usage, its hub open")
def _agent_step_with_cost_and_no_tools(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    store.record_usage(step, 1000, 200, 0, 0, 1.5, "list", None)
    store.record_attribution(step, 10, {})
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["session"] = launch(make_test_container(store=store), size=WIDE_SIZE)
    _push_hub(ctx, step)


@given("an agent step with turns but no recorded cost, its hub open")
def _agent_step_turns_no_cost(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="handle-feedback", role="agent", parent=item)
    store.record_attribution(step, 246, {})
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["session"] = launch(make_test_container(store=store), size=WIDE_SIZE)
    _push_hub(ctx, step)


@given("an agent step that never ran, its hub open")
def _agent_step_never_ran(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["session"] = launch(make_test_container(store=store))
    _push_hub(ctx, step)


@given("an item whose steps span two passes with recorded costs at different stages, its hub open")
def _item_two_passes(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    pass_1 = store.open_pass(item)
    spec_1 = store.create_step("spec1", step="spec-writer", role="agent", parent=item)
    store.set_step_pass(spec_1, pass_1)
    store.record_usage(spec_1, 1000, 200, 0, 0, 2.0, "list", None)
    store.record_attribution(spec_1, 10, {})
    code_1 = store.create_step("code1", step="write-code", role="agent", parent=item)
    store.set_step_pass(code_1, pass_1)
    store.record_usage(code_1, 500, 100, 0, 0, 0.5, "list", None)
    store.record_attribution(code_1, 5, {})
    store.close_pass(pass_1)

    pass_2 = store.open_pass(item)
    spec_2 = store.create_step("spec2", step="spec-writer", role="agent", parent=item)
    store.set_step_pass(spec_2, pass_2)
    store.record_usage(spec_2, 800, 150, 0, 0, 1.5, "list", None)
    store.record_attribution(spec_2, 8, {})

    ctx["store"] = store
    ctx["item_id"] = item
    ctx["session"] = launch(make_test_container(store=store), size=WIDE_SIZE)
    _push_hub(ctx, item)


@given("an item with an agent step that ran but has no recorded cost, its hub open")
def _item_with_no_cost_stage(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step = store.create_step("s", step="review-code", role="agent", parent=item)
    store.record_attribution(step, 60, {})
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["session"] = launch(make_test_container(store=store), size=WIDE_SIZE)
    _push_hub(ctx, item)


@given("an item with a human gate step and an agent step with a recorded cost, its hub open")
def _item_with_human_gate_and_agent_step(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    store.create_step("gate", step="await-merge", role="human", parent=item)
    step = store.create_step("s", step="write-code", role="agent", parent=item)
    store.record_usage(step, 1000, 200, 0, 0, 1.0, "list", None)
    store.record_attribution(step, 10, {})
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["session"] = launch(make_test_container(store=store), size=WIDE_SIZE)
    _push_hub(ctx, item)


@given("an item with no steps that have run, its hub open")
def _item_no_steps_run(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["session"] = launch(make_test_container(store=store))
    _push_hub(ctx, item)


@when("I open its Cost tab")
def _open_its_cost_tab(ctx):
    _open_cost_tab(ctx)


@then("no cost stats table is shown")
def _no_cost_stats_table_shown(ctx):
    assert not ctx["session"].app.screen.query_one(CostPane).display


@then("a message says this step has no cost to show")
def _step_empty_message_shown(ctx):
    widget = ctx["session"].app.screen.query_one("#hub-cost-empty", Static)
    assert widget.display
    assert "no cost to show" in _widget_text(widget).lower()


@then("a message says this step hasn't run yet")
def _step_not_run_message_shown(ctx):
    widget = ctx["session"].app.screen.query_one("#hub-cost-empty", Static)
    assert widget.display
    assert "hasn't run yet" in _widget_text(widget).lower()


@then("a message says no tool calls were recorded for this step")
def _no_tools_message_shown(ctx):
    pane = ctx["session"].app.screen.query_one(CostPane)
    assert pane.display
    assert COST_NO_TOOLS_MESSAGE in _widget_text(pane)
    assert "turns" in _field_keys(ctx)


@then("its turns are shown")
def _turns_shown(ctx):
    assert "turns" in _field_keys(ctx)
    assert _field_value(ctx, "turns") != ""


@then("its input, output, cache-read, and cache-creation tokens are all shown")
def _tokens_shown(ctx):
    for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"):
        assert key in _field_keys(ctx)


@then("its cache hit rate is shown, stated as cache-read over cache-read plus cache-creation plus input")
def _cache_hit_rate_shown(ctx):
    value = _field_value(ctx, "cache_hit_rate")
    assert "%" in value
    assert "cache-read" in value
    assert "cache-creation" in value
    assert "input" in value


@then("its cost is shown")
def _cost_shown(ctx):
    assert _field_value(ctx, "cost").startswith("$")


@then("its cost basis is shown")
def _cost_basis_shown(ctx):
    assert _field_value(ctx, "cost_basis") == "list"


@then("each tool's calls and bytes are shown")
def _tool_rows_shown(ctx):
    read_value = _breakdown_value(ctx, "tool:Read")
    assert "12 calls" in read_value and "4,300 bytes" in read_value
    bash_value = _breakdown_value(ctx, "tool:Bash")
    assert "3 calls" in bash_value and "512 bytes" in bash_value


@then(parsers.parse('its cost reads "{text}"'))
def _cost_reads(ctx, text):
    assert _field_value(ctx, "cost") == text


@then('no "$0.00" is shown anywhere on the tab')
def _no_zero_dollar_shown(ctx):
    pane = ctx["session"].app.screen.query_one(CostPane)
    assert "$0.00" not in _widget_text(pane)


@then("its total turns and cost sum every step across both passes")
def _total_sums_across_passes(ctx):
    assert _field_value(ctx, "turns") == "23"
    assert _field_value(ctx, "cost") == "$4.00"


@then("the per-stage subtotals are ordered with the highest-spend stage first")
def _per_stage_ordered_by_spend(ctx):
    rows = ctx["session"].app.screen._last_cost_rows
    stages = [row_key[len("stage:"):] for row_key, _label, _value in rows if row_key.startswith("stage:")]
    assert stages[0] == "spec-writer"
    assert "$3.50" in _breakdown_value(ctx, "stage:spec-writer")


@then("that stage's row reads \"not recorded\"")
def _stage_row_not_recorded(ctx):
    assert "not recorded" in _breakdown_value(ctx, "stage:review-code")


@then("its total turns equal the agent step's turns alone")
def _total_turns_exclude_human_gate(ctx):
    assert _field_value(ctx, "turns") == "10"


@then("a message says this item has no usage to show yet")
def _item_empty_message_shown(ctx):
    widget = ctx["session"].app.screen.query_one("#hub-cost-empty", Static)
    assert widget.display
    assert "no usage to show" in _widget_text(widget).lower()


@then(parsers.parse('its tab strip\'s last tab is "{label}"'))
def _last_tab_is(ctx, label):
    screen = ctx["session"].app.screen
    last_tab_id = screen._tab_order[-1]
    assert _TAB_LABELS[last_tab_id] == label
