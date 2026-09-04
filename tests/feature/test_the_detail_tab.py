import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.hub import DetailTable, NodeHubScreen
from lightcycle.application.flow import BlockInput, BlockStepUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeLauncher, launch, make_test_container

scenarios("the-detail-tab.feature")


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


def _field_value(ctx, key):
    table = ctx["session"].app.screen.query_one(DetailTable)
    return _rendered_cell_text(table, key, "value")


def _field_keys(ctx):
    return [key for key, _value in ctx["session"].app.screen._last_detail_fields]


def _field_present(ctx, key):
    return key in _field_keys(ctx)


def _launch_step(ctx, *, step="write-code", role="agent", metas=None, launcher=None):
    fs = FakeFs(metas=metas) if metas else None
    store = FakeStore()
    item = store.create_item("Item", "a description")
    step_id = store.create_step("s", step=step, role=role, parent=item)
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step_id
    ctx["session"] = launch(make_test_container(store=store, fs=fs, launcher=launcher))
    return store, step_id


def _set_phase_run(store, item, step_id, phase, branch=None, pr=None):
    pid = store.open_pass(item)
    store.set_step_pass(step_id, pid)
    rid = store.open_run(item, pid, phase)
    fields = {}
    if branch is not None:
        fields["branch"] = branch
    if pr is not None:
        fields["pr"] = pr
    if fields:
        store.set_run_field(rid, **fields)


def _push_hub(ctx, node_id):
    session = ctx["session"]
    screen = NodeHubScreen(session.app.container, node_id, session.app._now)
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    ctx["node_id"] = node_id
    ctx["hub_screen"] = screen
    return session


@given("a step whose phase run has a branch and a PR")
def _step_with_branch_and_pr(ctx):
    store, step_id = _launch_step(
        ctx, metas={"write-code": {"model": "sonnet", "step": "write-code", "phase": "code"}}
    )
    _set_phase_run(
        store, ctx["item_id"], step_id, "code",
        branch="feat/x", pr="https://github.com/kenmclennan/lightcycle/pull/1",
    )
    _push_hub(ctx, step_id)


@given("a step whose phase run has a PR, its Detail tab open, the PR field selected")
def _step_pr_field_selected(ctx):
    launcher = FakeLauncher(url_succeeds=True)
    ctx["launcher"] = launcher
    ctx["pr_url"] = "https://github.com/kenmclennan/lightcycle/pull/2"
    store, step_id = _launch_step(
        ctx, metas={"write-code": {"model": "sonnet", "step": "write-code", "phase": "code"}},
        launcher=launcher,
    )
    _set_phase_run(store, ctx["item_id"], step_id, "code", pr=ctx["pr_url"])
    _push_hub(ctx, step_id)
    table = ctx["session"].app.screen.query_one(DetailTable)
    table.move_cursor(row=table.get_row_index("pr"))


@given('a step at stage "code-await-merge" whose phase run has a PR')
def _await_merge_step_with_pr(ctx):
    ctx["pr_url"] = "https://github.com/kenmclennan/lightcycle/pull/3"
    store, step_id = _launch_step(
        ctx, step="code-await-merge", role="human",
        metas={"code-await-merge": {"step": "code-await-merge", "phase": "code"}},
    )
    _set_phase_run(store, ctx["item_id"], step_id, "code", pr=ctx["pr_url"])


@given("a step whose phase run has no branch and no PR")
def _step_no_branch_no_pr(ctx):
    _, step_id = _launch_step(ctx)
    _push_hub(ctx, step_id)


@given("a step with a stage, a state, a role, and a model")
def _step_stage_state_role_model(ctx):
    store, step_id = _launch_step(ctx)
    store.set_model(step_id, "sonnet")
    _push_hub(ctx, step_id)


@given("a step with a claimed_by, an outcome, and notes recorded")
def _step_claimed_outcome_notes(ctx):
    store, step_id = _launch_step(ctx)
    store.assign(step_id, "agent-1")
    store.close(step_id, "done")
    store.set_notes(step_id, "reviewed and merged")
    _push_hub(ctx, step_id)


@given("a step with a reflection and a watched_step recorded")
def _step_reflection_watched(ctx):
    store, step_id = _launch_step(ctx)
    store.update_metadata(step_id, {"reflection": "worked well"})
    store.set_watched_step(step_id, "LC-1.2")
    _push_hub(ctx, step_id)


@given("a step parked with a needs, a reason, and a tried all recorded")
def _step_parked_needs_reason_tried(ctx):
    store, step_id = _launch_step(ctx)
    BlockStepUseCase(store).execute(BlockInput(
        step=step_id, needs="decide the approach", reason="hit an ambiguity", tried="tried X and Y",
    ))
    _push_hub(ctx, step_id)


@given("a step parked with a tried recorded")
def _step_parked_tried(ctx):
    store, step_id = _launch_step(ctx)
    BlockStepUseCase(store).execute(BlockInput(
        step=step_id, needs="decide the approach", reason="hit an ambiguity", tried="tried X and Y",
    ))
    _push_hub(ctx, step_id)


@given("a step with no outcome, no notes, no reflection, and no watched_step recorded")
def _step_missing_optional_fields(ctx):
    _, step_id = _launch_step(ctx)
    _push_hub(ctx, step_id)


@given("a step parked at a stage the workflow declares agent-owned, its hub open")
def _step_parked_agent_owned(ctx):
    store, step_id = _launch_step(
        ctx, metas={"coder": {"model": "sonnet", "step": "write-code"}},
    )
    BlockStepUseCase(store).execute(
        BlockInput(step=step_id, needs="confirm approach", reason="ambiguous")
    )
    _push_hub(ctx, step_id)


@given("a step parked at a stage the workflow declares human-owned, its hub open")
def _step_parked_human_owned(ctx):
    store, step_id = _launch_step(
        ctx, step="code-await-merge", role="agent",
        metas={"pr-watcher": {"step": "code-await-merge"}},
    )
    BlockStepUseCase(store).execute(
        BlockInput(step=step_id, needs="confirm approach", reason="ambiguous")
    )
    _push_hub(ctx, step_id)


@given("an item, its hub open")
def _item_hub_open(ctx):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["session"] = launch(make_test_container(store=store))
    _push_hub(ctx, item)


@given("a step with no park recorded, its hub open")
def _step_no_park(ctx):
    _, step_id = _launch_step(ctx)
    _push_hub(ctx, step_id)


@when("I open its Detail tab")
def _open_detail_tab(ctx):
    pass


@when("I open its hub")
def _open_hub(ctx):
    _push_hub(ctx, ctx["step_id"])


@when(parsers.parse("{key} is pressed"))
def _key_pressed(ctx, key):
    keymap = {"Enter": "enter", "→": "right"}
    ctx["session"].press(keymap.get(key, key))


@then("its PR and branch are shown before stage, state, role, model, claimed_by, "
      "outcome, notes, park, reflection, and watched_step")
def _pr_and_branch_first(ctx):
    keys = _field_keys(ctx)
    assert keys[0] == "pr"
    assert keys[1] == "branch"


@then("the branch and the PR are shown")
def _branch_and_pr_shown(ctx):
    assert _field_present(ctx, "branch")
    assert _field_present(ctx, "pr")


@then('neither the words "phase run" nor "pass" appear anywhere on the tab')
def _no_phase_run_or_pass_words(ctx):
    table = ctx["session"].app.screen.query_one(DetailTable)
    text = _widget_text(table).lower()
    assert "phase run" not in text
    assert "pass" not in text


@then("the PR opens in the browser")
def _pr_opens_in_browser(ctx):
    assert ctx["launcher"].opened_urls == [ctx["pr_url"]]


@then("it lands on the Detail tab")
def _lands_on_detail_tab(ctx):
    screen = ctx["session"].app.screen
    assert isinstance(screen, NodeHubScreen)
    assert screen._active_tab == "detail"


@then("the PR is shown on screen")
def _pr_shown_on_screen(ctx):
    assert _field_value(ctx, "pr") == ctx["pr_url"]


@then("no branch field is shown")
def _no_branch_field(ctx):
    assert not _field_present(ctx, "branch")


@then("no PR field is shown")
def _no_pr_field(ctx):
    assert not _field_present(ctx, "pr")


@then("its stage, its state, its role, and its model are all shown")
def _stage_state_role_model_shown(ctx):
    assert _field_value(ctx, "stage") == "write-code"
    assert _field_value(ctx, "state") != ""
    assert _field_value(ctx, "role") == "agent"
    assert _field_value(ctx, "model") == "sonnet"


@then("its claimed_by, its outcome, and its notes are all shown")
def _claimed_outcome_notes_shown(ctx):
    assert _field_value(ctx, "claimed_by") == "agent-1"
    assert _field_value(ctx, "outcome") == "done"
    assert _field_value(ctx, "notes") == "reviewed and merged"


@then("its reflection and its watched_step are both shown")
def _reflection_watched_shown(ctx):
    assert _field_value(ctx, "reflection") == "worked well"
    assert _field_value(ctx, "watched_step") == "LC-1.2"


@then("the park's needs, its reason, and its tried are all shown")
def _park_fields_shown(ctx):
    assert _field_value(ctx, "needs") == "decide the approach"
    assert _field_value(ctx, "reason") == "hit an ambiguity"
    assert _field_value(ctx, "tried") == "tried X and Y"


@then("the recorded tried text is shown")
def _tried_text_shown(ctx):
    assert _field_value(ctx, "tried") == "tried X and Y"


@then("no outcome field is shown")
def _no_outcome_field(ctx):
    assert not _field_present(ctx, "outcome")


@then("no notes field is shown")
def _no_notes_field(ctx):
    assert not _field_present(ctx, "notes")


@then("no reflection field is shown")
def _no_reflection_field(ctx):
    assert not _field_present(ctx, "reflection")


@then("no watched_step field is shown")
def _no_watched_step_field(ctx):
    assert not _field_present(ctx, "watched_step")


@then("a brief confirmation toast is shown")
def _confirmation_toast_shown(ctx):
    screen = ctx["session"].app.screen
    assert screen._toast_active
    toast = screen.query_one("#hub-detail-toast", Static)
    assert toast.display
    assert _widget_text(toast) != ""


@then("the step's role is reassigned to its workflow-declared owner")
def _role_reassigned(ctx):
    node = ctx["store"].get_node(ctx["step_id"])
    assert node.role == "agent"


@then("its park fields are cleared")
def _park_cleared(ctx):
    node = ctx["store"].get_node(ctx["step_id"])
    assert not node.park


@then("a clear message is shown, not a silent failure")
def _clear_failure_message_shown(ctx):
    screen = ctx["session"].app.screen
    assert screen._toast_active
    toast = screen.query_one("#hub-detail-toast", Static)
    assert toast.display
    assert _widget_text(toast) != ""


@then("the step's role and park fields are unchanged")
def _role_and_park_unchanged(ctx):
    node = ctx["store"].get_node(ctx["step_id"])
    assert node.role == "human"
    assert node.park


@then("nothing happens, since there is no step to resume")
def _nothing_happens_no_step_to_resume(ctx):
    assert ctx["session"].app.screen is ctx["hub_screen"]


@then("nothing happens, since there is nothing parked to resume")
def _nothing_happens_nothing_parked(ctx):
    assert ctx["session"].app.screen is ctx["hub_screen"]


@then("no toast is shown")
def _no_toast_shown(ctx):
    screen = ctx["session"].app.screen
    assert not screen._toast_active


@then("no Detail tab is shown")
def _no_detail_tab_shown(ctx):
    screen = ctx["session"].app.screen
    assert len(screen.query("#hub-tab-detail")) == 0
