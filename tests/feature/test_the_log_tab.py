import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import Static

from lightcycle.adapters.tui.hub import LogPane, NodeHubScreen
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.tui_harness import launch, make_test_container

scenarios("the-log-tab.feature")

LOG_PATH = "/fake/logs/worker.log"
WORKER_PID = 111
SEEDED_LINES = b"14:02:11 reading files\n14:02:14 writing tests\n14:03:02 running suite\n"


@pytest.fixture
def ctx():
    state = {}
    yield state
    session = state.get("session")
    if session is not None:
        session.close()


def _running_step(lines=b""):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="coder", role="coder", parent=item)
    store.claim_ready("coder")
    workers = FakeWorkers(
        workers=[{"step": step, "role": "coder", "pid": WORKER_PID, "pid_started": None, "log": LOG_PATH}],
        alive_pids={WORKER_PID},
    )
    fs = FakeFs(files={LOG_PATH: lines})
    return store, item, step, fs, workers


def _done_step(lines):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="coder", role="coder", parent=item)
    store.claim_ready("coder")
    store.close(step, "done")
    workers = FakeWorkers(
        workers=[{"step": step, "role": "coder", "pid": WORKER_PID, "pid_started": None, "log": LOG_PATH}],
        alive_pids=set(),
    )
    fs = FakeFs(files={LOG_PATH: lines})
    return store, item, step, fs, workers


def _many_lines(n):
    return "".join("line %02d\n" % i for i in range(n)).encode()


def _prepare(ctx, store, item, step, fs, workers):
    ctx["store"] = store
    ctx["item_id"] = item
    ctx["step_id"] = step
    ctx["fs"] = fs
    ctx["workers"] = workers


def _open(ctx):
    session = launch(
        make_test_container(store=ctx["store"], fs=ctx["fs"], workers=ctx["workers"])
    )
    ctx["session"] = session
    session.run(
        lambda: session.app.push_screen(
            NodeHubScreen(session.app.container, ctx["step_id"], session.app._now)
        )
    )
    session.pause()
    screen = session.app.screen
    tabs_tried = 0
    while screen._active_tab != "log" and tabs_tried < 3:
        session.press("]")
        tabs_tried += 1
    ctx["hub_screen"] = screen
    return session


def _log_pane(ctx):
    return ctx["session"].app.screen.query_one(LogPane)


def _painted_lines(session, widget):
    region = widget.region
    strips = session.app.screen._compositor.render_strips()
    return [
        "".join(seg.text for seg in strips[y].crop(region.x, region.x + region.width))
        for y in range(region.y, region.y + region.height)
    ]


def _log_text(ctx):
    return "\n".join(_painted_lines(ctx["session"], _log_pane(ctx)))


def _empty_text(ctx):
    widget = ctx["session"].app.screen.query_one("#hub-log-empty", Static)
    return "\n".join(_painted_lines(ctx["session"], widget))


def _buffered_text(ctx):
    pane = _log_pane(ctx)
    return "\n".join("".join(seg.text for seg in strip) for strip in pane.lines)


def _tick(ctx):
    ctx["session"].run(lambda: ctx["hub_screen"]._tail_tick())
    ctx["session"].pause()


def _write_line(ctx, text):
    ctx["fs"]._files[LOG_PATH] = ctx["fs"]._files.get(LOG_PATH, b"") + text.encode()


@given("the current step is being performed by a worker and has already written several lines")
def _given_running_with_lines(ctx):
    _prepare(ctx, *_running_step(lines=SEEDED_LINES))


@given("the current step is being performed by a worker")
def _given_running(ctx):
    _prepare(ctx, *_running_step())


@given("the live log is open and following the tail")
def _given_live_open_following(ctx):
    _prepare(ctx, *_running_step(lines=SEEDED_LINES))
    _open(ctx)


@given(parsers.parse("the current step is a human step, with no worker"))
def _given_human_step(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="await-merge", role="human", parent=item)
    _prepare(ctx, store, item, step, FakeFs(), FakeWorkers())


@given(parsers.parse("the current step hasn't started yet, still queued"))
def _given_queued_step(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="coder", role="coder", parent=item)
    _prepare(ctx, store, item, step, FakeFs(), FakeWorkers())


@given("the live log is open")
def _given_live_open(ctx):
    _prepare(ctx, *_running_step(lines=_many_lines(60)))
    _open(ctx)
    ctx["text_before_scroll"] = _log_text(ctx)


@given("the live log is open and I've scrolled up")
def _given_live_open_scrolled_up(ctx):
    _prepare(ctx, *_running_step(lines=_many_lines(60)))
    _open(ctx)
    for _ in range(20):
        ctx["session"].press("up")
    ctx["scroll_before"] = _log_pane(ctx).scroll_y


@given("the live log's buffer is longer than one screen")
def _given_live_long_buffer(ctx):
    _prepare(ctx, *_running_step(lines=_many_lines(60)))
    _open(ctx)
    pane = _log_pane(ctx)
    ctx["session"].run(lambda: pane.scroll_home(animate=False))
    ctx["session"].pause()
    ctx["scroll_before"] = pane.scroll_y


@given("the step has finished while its log was open")
def _given_step_finished_while_open(ctx):
    _prepare(ctx, *_running_step(lines=SEEDED_LINES))
    _open(ctx)
    ctx["workers"]._alive.discard(WORKER_PID)
    _tick(ctx)


@given("the current step is done")
def _given_step_done(ctx):
    _prepare(ctx, *_done_step(SEEDED_LINES))


@given("a done step's log is open")
def _given_done_log_open(ctx):
    _prepare(ctx, *_done_step(SEEDED_LINES))
    _open(ctx)


@given("a done step's log is longer than one screen")
def _given_done_log_long(ctx):
    _prepare(ctx, *_done_step(_many_lines(60)))
    _open(ctx)
    ctx["scroll_before"] = _log_pane(ctx).scroll_y


@when("I open its Log tab")
def _when_open_log_tab(ctx):
    _open(ctx)


@when("the worker writes a new line to the log")
def _when_worker_writes_line(ctx):
    _write_line(ctx, "14:04:19 a new line\n")
    _tick(ctx)


@when("a new line arrives")
def _when_new_line_arrives(ctx):
    _write_line(ctx, "14:04:19 a new line\n")
    _tick(ctx)


@when("I scroll up")
def _when_scroll_up(ctx):
    for _ in range(5):
        ctx["session"].press("up")


@when("Ctrl-D is pressed")
def _when_ctrl_d(ctx):
    ctx["session"].press("ctrl+d")


@when("Ctrl-U is pressed")
def _when_ctrl_u(ctx):
    ctx["session"].press("ctrl+u")


@when("the worker completes")
def _when_worker_completes(ctx):
    ctx["workers"]._alive.discard(WORKER_PID)
    _tick(ctx)


@when("I look at the log")
def _when_look_at_log(ctx):
    pass


@when("I view it")
def _when_view_it(ctx):
    pass


@then("the lines already written are shown")
def _then_lines_already_shown(ctx):
    text = _log_text(ctx)
    assert "reading files" in text
    assert "writing tests" in text
    assert "running suite" in text


@then("the new line appears without a manual refresh")
def _then_new_line_appears(ctx):
    assert "a new line" in _log_text(ctx)


@then("the view auto-scrolls to keep it visible")
def _then_auto_scrolls(ctx):
    pane = _log_pane(ctx)
    assert pane.scroll_y == pane.max_scroll_y


@then("I see a message saying there's nothing live to stream")
def _then_no_stream_message(ctx):
    assert "nothing live to stream" in _empty_text(ctx).lower()


@then("no blank or broken pane is shown")
def _then_no_blank_pane(ctx):
    assert _empty_text(ctx).strip() != ""
    assert not _log_pane(ctx).display


@then("I see earlier lines from the current buffer")
def _then_earlier_lines_visible(ctx):
    text = _log_text(ctx)
    assert text != ctx["text_before_scroll"]
    assert "line 59" not in text


@then("the live tail keeps running")
def _then_live_tail_keeps_running(ctx):
    assert ctx["hub_screen"]._log_timer is not None
    assert not ctx["hub_screen"]._log_finished


@then("it's added to the buffer")
def _then_added_to_buffer(ctx):
    assert "a new line" in _buffered_text(ctx)


@then("my scroll position is unchanged")
def _then_scroll_unchanged(ctx):
    assert _log_pane(ctx).scroll_y == ctx["scroll_before"]


@then("the view moves a full screen, not one line")
def _then_moves_full_screen(ctx):
    pane = _log_pane(ctx)
    assert pane.scroll_y > ctx["scroll_before"] + 1
    ctx["scroll_before"] = pane.scroll_y


@then("the view is scrolled back to where it started")
def _then_scrolled_back_to_start(ctx):
    assert _log_pane(ctx).scroll_y == ctx["scroll_before"]


@then("the view clearly indicates the step has finished")
def _then_indicates_finished(ctx):
    assert "step finished" in _log_text(ctx).lower()


@then("it doesn't just go silent")
def _then_not_silent(ctx):
    assert _log_pane(ctx).live is False


@then("it still shows the output accumulated up to completion")
def _then_still_shows_accumulated(ctx):
    text = _log_text(ctx)
    assert "reading files" in text
    assert "writing tests" in text
    assert "running suite" in text


@then("it shows the complete log output captured from that step's run")
def _then_shows_complete_output(ctx):
    text = _log_text(ctx)
    assert "reading files" in text
    assert "writing tests" in text
    assert "running suite" in text


@then("no live indicator is shown")
def _then_no_live_indicator(ctx):
    assert _log_pane(ctx).live is False


@then("there is no auto-scroll, since nothing new will arrive")
def _then_no_auto_scroll(ctx):
    assert _log_pane(ctx).auto_scroll is False


def test_left_closes_the_hub_from_the_no_log_state(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="await-merge", role="human", parent=item)
    _prepare(ctx, store, item, step, FakeFs(), FakeWorkers())
    session = _open(ctx)
    assert session.app.screen._active_tab == "log"
    assert session.app.focused is None

    session.press("left")

    assert not isinstance(session.app.screen, NodeHubScreen)


def test_escape_closes_the_hub_from_the_no_log_state(ctx):
    store = FakeStore()
    item = store.create_item("Item")
    step = store.create_step("s", step="await-merge", role="human", parent=item)
    _prepare(ctx, store, item, step, FakeFs(), FakeWorkers())
    session = _open(ctx)
    assert session.app.screen._active_tab == "log"
    assert session.app.focused is None

    session.press("escape")

    assert not isinstance(session.app.screen, NodeHubScreen)
