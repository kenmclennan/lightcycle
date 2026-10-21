import os

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.hub import DetailTable, HubTabStrip, NodeHubScreen
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
    step_id = store.create_step(stage=step, role=role, item=item)
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step_id
    ctx["session"] = launch(make_test_container(store=store, fs=fs, launcher=launcher))
    return store, step_id


def _set_phase_run(store, item, step_id, phase, branch=None, pr=None):
    pid = store.open_pass(item)
    store.set_step_pass(step_id, pid)
    rid = store.open_run(item, pid, phase)
    if branch is not None:
        store.set_branch(rid, branch)
    if pr is not None:
        store.set_pr(rid, pr)


def _push_hub(ctx, node_id, initial_tab="detail"):
    session = ctx["session"]
    screen = NodeHubScreen(session.app.container, node_id, session.app._now, initial_tab=initial_tab)
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


@given("a parked human step whose phase run has no branch and no PR")
def _parked_human_step_bare(ctx):
    store, step_id = _launch_step(ctx, step="triage", role="human")
    store.update_metadata(step_id, {"needs": "Decide the next move", "reason": "Triage found no owner"})


@given("a step whose phase run has no branch and no PR")
def _step_no_branch_no_pr(ctx):
    _, step_id = _launch_step(ctx)
    _push_hub(ctx, step_id)


_WRITE_CODE_METAS = {"write-code": {"model": "sonnet", "step": "write-code", "phase": "code"}}


def _set_up_branch_in_repo(ctx, *, launcher=None, resolvable):
    store, step_id = _launch_step(ctx, metas=_WRITE_CODE_METAS, launcher=launcher)
    if resolvable:
        store.add_artifact(ctx["item_id"], "repo", "/repo")
    _set_phase_run(store, ctx["item_id"], step_id, "code", branch="feat/x")
    worktree_path = os.path.join("/repo", ".worktrees", "%s-code" % ctx["item_id"])
    ctx["worktree_path"] = worktree_path
    if resolvable:
        ctx["session"].app.container.fs._dirs[worktree_path] = []
    return store, step_id


@given("a step whose phase run has a branch, in a resolvable repo")
def _step_branch_resolvable_repo(ctx):
    _, step_id = _set_up_branch_in_repo(ctx, resolvable=True)
    _push_hub(ctx, step_id)


_DECLARED_METAS = {
    "write-code": {
        "model": "sonnet", "step": "write-code", "phase": "code",
        "detail": "[branch, worktree, pr]", "routes": {"done": "gate"},
    }
}


@given("a step with an outcome and a report recorded")
def _step_outcome_and_report(ctx):
    store, step_id = _launch_step(ctx)
    store.complete_node(step_id, "done")
    store.set_report(step_id, "reviewed and merged")
    _push_hub(ctx, step_id)


@given(
    "a step declaring the detail list branch, worktree and pr, whose phase run has a branch "
    "and a PR, in a resolvable repo"
)
def _step_declared_resolvable(ctx):
    store, step_id = _launch_step(ctx, metas=_DECLARED_METAS)
    store.add_artifact(ctx["item_id"], "repo", "/repo")
    _set_declared_run(ctx, store, step_id)
    ctx["session"].app.container.fs._dirs[ctx["worktree_path"]] = []
    _push_hub(ctx, step_id)


@given(
    "a step declaring the detail list branch, worktree and pr, whose phase run has a branch "
    "and a PR, in a resolvable repo, its Detail tab open, the worktree field selected"
)
def _step_declared_worktree_selected(ctx):
    launcher = FakeLauncher()
    ctx["launcher"] = launcher
    store, step_id = _launch_step(ctx, metas=_DECLARED_METAS, launcher=launcher)
    store.add_artifact(ctx["item_id"], "repo", "/repo")
    _set_declared_run(ctx, store, step_id)
    ctx["session"].app.container.fs._dirs[ctx["worktree_path"]] = []
    _push_hub(ctx, step_id)
    table = ctx["session"].app.screen.query_one(DetailTable)
    table.move_cursor(row=table.get_row_index("worktree"))


@given(
    "a step declaring the detail list branch and worktree, whose phase run has a branch, "
    "in an unresolvable repo"
)
def _step_declared_unresolvable(ctx):
    metas = {"write-code": dict(_DECLARED_METAS["write-code"], detail="[branch, worktree]")}
    store, step_id = _launch_step(ctx, metas=metas)
    _set_phase_run(store, ctx["item_id"], step_id, "code", branch="feat/x")
    _push_hub(ctx, step_id)


def _set_declared_run(ctx, store, step_id):
    _set_phase_run(
        store, ctx["item_id"], step_id, "code",
        branch="feat/x", pr="https://github.com/kenmclennan/lightcycle/pull/4",
    )
    ctx["worktree_path"] = os.path.join("/repo", ".worktrees", "%s-code" % ctx["item_id"])


@given("a step parked with a needs and a reason recorded")
def _step_parked_needs_reason(ctx):
    store, step_id = _launch_step(ctx)
    BlockStepUseCase(store).execute(BlockInput(
        step=step_id, needs="decide the approach", reason="hit an ambiguity",
    ))
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
    _push_hub(ctx, ctx["step_id"], initial_tab=None)


@when(parsers.parse("{key} is pressed"))
def _key_pressed(ctx, key):
    keymap = {"Enter": "enter", "→": "right"}
    ctx["session"].press(keymap.get(key, key))


@then("its outcome and its report are shown, in that order, at the top")
def _outcome_report_first(ctx):
    keys = _field_keys(ctx)
    assert keys[:2] == ["outcome", "report"]
    assert _field_value(ctx, "outcome") == "done"
    assert _field_value(ctx, "report") == "reviewed and merged"


@then("the run rows lead, followed by the outcome and the report")
def _run_rows_then_outcome_report(ctx):
    assert _field_keys(ctx) == ["pr", "branch", "worktree", "outcome", "report"]


@then("its Detail entries are pr, branch and worktree, in that order")
def _declared_entries_in_order(ctx):
    assert _field_keys(ctx) == ["pr", "branch", "worktree"]


@then("the worktree entry is shown blank")
def _worktree_entry_blank(ctx):
    assert _field_keys(ctx) == ["pr", "branch", "worktree"]
    assert _field_value(ctx, "worktree") == ""


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


@when("I switch to its Detail tab")
def _switch_to_detail_tab(ctx):
    screen = ctx["session"].app.screen
    screen._active_tab = "detail"
    screen.query_one(HubTabStrip).set_active("detail")
    screen._apply_tab_visibility()
    ctx["session"].pause()


@then("the PR is shown on screen")
def _pr_shown_on_screen(ctx):
    assert _field_value(ctx, "pr") == ctx["pr_url"]


@then("a branch field is shown")
def _branch_field(ctx):
    assert _field_present(ctx, "branch")


@then("no PR field is shown")
def _no_pr_field(ctx):
    assert not _field_present(ctx, "pr")


@then("the worktree is shown")
def _worktree_shown(ctx):
    assert _field_value(ctx, "worktree") == ctx["worktree_path"]


@then("the worktree opens in the editor")
def _worktree_opens_in_editor(ctx):
    editor = ctx["session"].app.container.config.editor()
    assert ctx["launcher"].edited_detached == (editor, ctx["worktree_path"])


@then("the park's needs and its reason are shown")
def _park_fields_shown(ctx):
    assert _field_value(ctx, "needs") == "decide the approach"
    assert _field_value(ctx, "reason") == "hit an ambiguity"


@then("no needs field is shown")
def _no_needs_field(ctx):
    assert not _field_present(ctx, "needs")


@then("no reason field is shown")
def _no_reason_field(ctx):
    assert not _field_present(ctx, "reason")


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
