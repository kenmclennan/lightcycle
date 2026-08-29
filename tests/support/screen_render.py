import argparse
import datetime
import sys

from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.fake_workers import FakeWorkers
from tests.support.tui_harness import FakeBreakerPort, FakeLauncher, FakeLock, launch, make_test_container

NOW = datetime.datetime(2026, 1, 1, 14, 16, 0)
DEFAULT_SIZE = (100, 30)


def _at(minutes):
    return (NOW - datetime.timedelta(minutes=minutes)).isoformat()


class DemoStore(FakeStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._next_id = None

    def _new_record(self, **fields):
        record = super()._new_record(**fields)
        if self._next_id is not None:
            record["id"] = self._next_id
            self._next_id = None
        return record

    def theme(self, node_id, title, **kwargs):
        self._next_id = node_id
        return self.create_theme(title, **kwargs)

    def item(self, node_id, title, **kwargs):
        self._next_id = node_id
        return self.create_item(title, **kwargs)

    def step(self, node_id, title, **kwargs):
        self._next_id = node_id
        return self.create_step(title, **kwargs)


THEME_TITLE = "Project model: github-identity registry"
REGISTRY_TITLE = "Registry table and identity-based repo resolution"
CLONE_TITLE = "Clone-on-demand: fetch an absent project on resolve"
SCAN_TITLE = "lc project scan: recursive discovery by git remote"
WORKFLOW = "lightcycle/spec-driven@abfb01d"


def _populated_store(claimed_minutes_ago=14):
    store = DemoStore(now=lambda: _at(claimed_minutes_ago))
    theme = store.theme("LC-143", THEME_TITLE, project="lightcycle")

    scan = store.item("LC-143.3", SCAN_TITLE, theme=theme, workflow=WORKFLOW)
    store.edit_node(
        scan,
        description="Phase 3 of the registry work. lc project scan walks a tree recursively "
        "and lists registration candidates.",
    )
    spec = store.step("LC-143.3.1", "write the spec", step="spec-writer", role="spec-writer",
                      parent=scan)
    store.close(spec, "done")
    coding = store.step("LC-143.3.4", "write the code", step="write-code", role="write-code",
                        parent=scan)
    store.step("LC-143.3.5", "open the pr", step="code-open-pr", role="open-pr", parent=scan)
    store.step("LC-143.3.6", "await merge", step="code-await-merge", role="human", parent=scan)
    store.claim_ready("write-code")

    registry = store.item("LC-143.1", REGISTRY_TITLE, theme=theme, workflow=WORKFLOW)
    store.step("LC-143.1.4", "write the code", step="write-code", role="write-code", parent=registry)
    store.claim_ready("write-code")

    clone = store.item("LC-143.2", CLONE_TITLE, theme=theme, workflow=WORKFLOW)
    store.step("LC-143.2.4", "write the code", step="write-code", role="write-code", parent=clone)

    store.add_artifact(scan, "repo", "kenmclennan/lightcycle")
    store.add_artifact(scan, "pr", "https://github.com/kenmclennan/lightcycle/pull/143")

    return store, theme, scan, coding


LONG_DESCRIPTION = (
    "This item exists to fix a header that grows without bound. " * 50
).strip()


def _long_description_store(description=LONG_DESCRIPTION):
    store = DemoStore(now=lambda: _at(2))
    theme = store.theme("LC-319", THEME_TITLE, project="lightcycle")
    item = store.item("LC-319.1", SCAN_TITLE, theme=theme, workflow=WORKFLOW)
    if description is not None:
        store.edit_node(item, description=description)
    store.step("LC-319.1.4", "write the code", step="write-code", role="write-code", parent=item)
    return store, item


def _blocked_store():
    store = DemoStore(now=lambda: _at(3))
    theme = store.theme("LC-143", THEME_TITLE, project="lightcycle")
    blocker = store.item("LC-143.1", REGISTRY_TITLE, theme=theme, workflow=WORKFLOW)
    blocking_step = store.step("LC-143.1.4", "write the code", step="write-code",
                               role="write-code", parent=blocker)
    waiting = store.item("LC-143.2", CLONE_TITLE, theme=theme, workflow=WORKFLOW)
    store.step("LC-143.2.4", "write the code", step="write-code", role="write-code",
               parent=waiting, deps=[blocking_step])
    return store, waiting


def _human_step_store():
    store = DemoStore(now=lambda: _at(6))
    theme = store.theme("LC-143", THEME_TITLE, project="lightcycle")
    item = store.item("LC-143.3", SCAN_TITLE, theme=theme, workflow=WORKFLOW)
    step = store.step("LC-143.3.6", "await merge", step="code-await-merge", role="human",
                      parent=item, attention=True)
    store.update_metadata(step, {"needs": "Resolve the merge conflict manually"})
    return store, item


def _backlog_store():
    store = DemoStore()
    lc273 = store.item("LC-273", "Row title repeats the step name", project="lightcycle")
    store.item("LC-275", "Active glyph unreadable at terminal size", project="lightcycle")
    store.item("LC-277", "Human-facing step display names", project="saga")
    store.add_project("kenmclennan/lightcycle")
    store.add_artifact(lc273, "repo", "kenmclennan/lightcycle")
    return store


STACKED_TITLE = "A title long enough to need a continuation line for real"


def _stacked_priority_store():
    from lightcycle.domain.work import State

    store = DemoStore(now=lambda: _at(14))
    step = store.step(
        "LC-3900.100.100", STACKED_TITLE, step="handle-feedback", role="handle-feedback",
    )
    store.assign(step, "worker-1")
    store.update_state(step, State.IN_PROGRESS)
    return store


def _stacked_backlog_store():
    store = DemoStore()
    store.item("LIGHTCYCLE-3900.100.100.100", STACKED_TITLE, project="lightcycle")
    return store


def _stacked_hierarchy_store():
    store = DemoStore(now=lambda: _at(6))
    item = store.item("LC-290.1", LONG_ITEM_TITLE, project="lightcycle")
    step = store.step(
        "LC-290.1.86", STACKED_TITLE, step="implement-features", role="implement-features",
        parent=item,
    )
    return store, item, step


def _stacked_artifacts_store():
    store = DemoStore()
    item = store.item("LC-45", "Lightcycle trend audit", project="lightcycle")
    store.add_artifact(
        item, "code-review-findings-and-remediation-plan-notes",
        "feat/LC-290.1-code-3-deliver-the-operator",
    )
    return store, item


LONG_ITEM_TITLE = "Deliver the operator-monitors-the-pipeline Blueprint"
LONG_THEME_TITLE = "Operator monitors the pipeline - deliver the node hub and tabs"

_LOOP = [
    ("plan-next", "plan-next"),
    ("feature-writer", "feature-writer"),
    ("feature-open-pr", "open-pr"),
    ("feature-watch-ci", "watch-ci"),
    ("review-features", "review-features"),
    ("implement-features", "implement-features"),
    ("code-open-pr", "open-pr"),
    ("code-watch-ci", "watch-ci"),
    ("review-code", "review-code"),
    ("code-await-merge", "human"),
    ("handle-feedback", "handle-feedback"),
]


def _long_hierarchy_store(passes=4):
    store = DemoStore(now=lambda: _at(2))
    theme = store.theme("LC-290", LONG_THEME_TITLE, project="lightcycle")
    item = store.item("LC-290.1", LONG_ITEM_TITLE, theme=theme, workflow="flynns-workflows/blueprint-delivery@0333918")
    n = 0
    for _ in range(passes):
        for step, role in _LOOP:
            n += 1
            store.step(
                "LC-290.1.%d" % n,
                "%s: %s" % (step, LONG_ITEM_TITLE),
                step=step,
                role=role,
                parent=item,
            )
    return store, item


def _launch(store, *, lock_running=True, breaker_open=False, size=DEFAULT_SIZE, fs=None, workers=None,
            launcher=None):
    container = make_test_container(
        store=store,
        lock=FakeLock(running=lock_running),
        breaker=FakeBreakerPort(
            is_open=breaker_open,
            reset_at=(NOW + datetime.timedelta(minutes=4)).timestamp() if breaker_open else None,
        ),
        fs=fs,
        workers=workers,
        launcher=launcher,
    )
    return launch(container, now=lambda: NOW, size=size)


def _open_hub(session, node_id, tab=None):
    from lightcycle.adapters.tui.hub import HubTabStrip, NodeHubScreen

    screen = NodeHubScreen(session.app._container, node_id, lambda: NOW, initial_tab=tab)
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    if tab:
        session.run(lambda: screen.query_one(HubTabStrip).set_active(tab))
        session.run(screen._apply_tab_visibility)
        session.pause()
    return session


def _priority_normal(size):
    store, _theme, _scan, _coding = _populated_store()
    return _launch(store, size=size)


def _priority_empty(size):
    return _launch(FakeStore(), size=size)


def _priority_claude_unavailable(size):
    store, _theme, _scan, _coding = _populated_store()
    return _launch(store, breaker_open=True, size=size)


def _priority_stacked(size):
    return _launch(_stacked_priority_store(), size=size)


def _backlog_normal(size):
    session = _launch(_backlog_store(), size=size)
    session.press("tab")
    return session


def _backlog_stacked(size):
    session = _launch(_stacked_backlog_store(), size=size)
    session.press("tab")
    return session


def _backlog_empty(size):
    session = _launch(FakeStore(), size=size)
    session.press("tab")
    return session


def _backlog_empty_filtered(size):
    store = _backlog_store()
    store.item("LC-999", "An item in another project", project="horde")
    session = _launch(store, size=size)
    session.press("tab")
    session.app._backlog_project_filter = "horde"
    session.run(session.app._refresh)
    session.pause()
    return session


def _backlog_picker_open(size):
    session = _backlog_normal(size)
    session.press("f")
    return session


def _backlog_claude_unavailable(size):
    session = _launch(_backlog_store(), breaker_open=True, size=size)
    session.press("tab")
    return session


def _hub_hierarchy(size):
    store, _theme, scan, _coding = _populated_store()
    return _open_hub(_launch(store, size=size), scan, tab="hierarchy")


def _hub_hierarchy_stacked(size):
    store, item, _step = _stacked_hierarchy_store()
    return _open_hub(_launch(store, size=size), item, tab="hierarchy")


_LOG_PATH = "/fake/logs/worker-write-code.log"

_LOG_EXCERPT = (
    b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_01Qj4aibXup6tHb3JkcPWr4E","type":"message","role":"assistant","content":[{"type":"text","text":"Now run the tests and linter to verify everything is green."}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":555,"cache_read_input_tokens":34014,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":555},"output_tokens":2,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"ba202d44-0f04-4e6c-a8f0-536b907d42e9","request_id":"req_011Ccf94gxhJzNgDfMYpLAuR"}\n'
    b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_01Qj4aibXup6tHb3JkcPWr4E","type":"message","role":"assistant","content":[{"type":"tool_use","id":"toolu_01WBJE3FNg6fpx4XKdjRLTiP","name":"Bash","input":{"command":"cd /Users/kenmclennan/workspace/projects/the-grid/.worktrees/afo && bash tests/run.sh 2>&1 | tail -20","description":"Run test suite in worktree","timeout":120000},"caller":{"type":"direct"}}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":555,"cache_read_input_tokens":34014,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":555},"output_tokens":2,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"4e145aef-de3b-4a9a-b43e-88eff6dfca80","request_id":"req_011Ccf94gxhJzNgDfMYpLAuR"}\n'
    b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_01PLhTvEyW3xgFPsEELBUPzK","type":"message","role":"assistant","content":[{"type":"tool_use","id":"toolu_014aTzb2UxU8LkwrHZhR67ox","name":"Bash","input":{"command":"cd /Users/kenmclennan/workspace/projects/the-grid/.worktrees/afo && uv run ruff check .","description":"Run ruff linter in worktree"},"caller":{"type":"direct"}}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":262,"cache_read_input_tokens":34569,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":262},"output_tokens":57,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"aef1e6e9-82da-4a73-b538-2eaca5200c17","request_id":"req_011Ccf9DmpPneFwYFJ9f2obk"}\n'
    b'{"type":"user","message":{"role":"user","content":[{"tool_use_id":"toolu_014aTzb2UxU8LkwrHZhR67ox","type":"tool_result","content":"All checks passed!","is_error":false}]},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"06ed7763-87b4-47b7-bc24-745197cd8616","timestamp":"2026-07-03T12:42:28.304Z","tool_use_result":{"stdout":"All checks passed!","stderr":"","interrupted":false,"isImage":false,"noOutputExpected":false}}\n'
    b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_01GcoPBSgqJs23gjNYtPeu8E","type":"message","role":"assistant","content":[{"type":"text","text":"Ruff is clean. Waiting for tests."}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":222,"cache_read_input_tokens":34831,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":222},"output_tokens":2,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"06bf67cc-fc86-48aa-a3e7-3f1742e878ca","request_id":"req_011Ccf9E3mbAc3N22qfPTSyR"}\n'
)


def _hub_active_log(size):
    store, _theme, scan, coding = _populated_store()
    fs = FakeFs(files={_LOG_PATH: _LOG_EXCERPT})
    workers = FakeWorkers(
        workers=[{"step": coding, "role": "write-code", "pid": 4242, "pid_started": None,
                  "log": _LOG_PATH}],
        alive_pids={4242},
    )
    return _open_hub(_launch(store, size=size, fs=fs, workers=workers), scan, tab="log")


def _hub_log_finished(size):
    store, _theme, scan, coding = _populated_store()
    fs = FakeFs(files={_LOG_PATH: _LOG_EXCERPT})
    workers = FakeWorkers(
        workers=[{"step": coding, "role": "write-code", "pid": 4242, "pid_started": None,
                  "log": _LOG_PATH}],
        alive_pids=set(),
    )
    return _open_hub(_launch(store, size=size, fs=fs, workers=workers), scan, tab="log")


def _hub_artifacts(size):
    store, _theme, scan, _coding = _populated_store()
    return _open_hub(_launch(store, size=size), scan, tab="artifacts")


def _hub_artifacts_stacked(size):
    store, item = _stacked_artifacts_store()
    return _open_hub(_launch(store, size=size), item, tab="artifacts")


FINDINGS_TEXT = (
    "Lightcycle trend audit - N=93 closed items, batch: 1nu, 33j, tg-2, tg-18, tg-20,\n"
    "LC-4.1, LC-8.1, LC-3.1, LC-10, LC-5.1, LC-7.1, LC-7.2, LC-18, LC-19, LC-13.1, LC-20, LC-13.4, LC-21.\n"
    "\n"
    "FINDING 1: Recurring missed version bump causes avoidable review-reject/rework cycles.\n"
    "The version-bump CI gate was missed by build/implementation steps at least twice independently."
)
BRIEF_PATH = "/Users/kenmclennan/workspace/specs/GRID-012-agents-report-tool-friction.md"


def _artifact_viewer_store():
    store = DemoStore(now=lambda: _at(2))
    item = store.item("LC-45", "Lightcycle trend audit", project="lightcycle")
    store.add_artifact(item, "findings", FINDINGS_TEXT, kind="text")
    store.add_artifact(
        item, "watched-prs",
        "lightcycle/pull/277\nlightcycle/pull/281\nlightcycle-specs/pull/61",
        kind="list",
    )
    store.add_artifact(item, "pr", "https://github.com/kenmclennan/lightcycle/pull/277", kind="url")
    store.add_artifact(item, "brief", BRIEF_PATH, kind="filepath")
    return store, item


def _open_artifact_at(session, item, tab_row):
    from lightcycle.adapters.tui.hub import ArtifactsTable

    session = _open_hub(session, item, tab="artifacts")
    table = session.app.screen.query_one(ArtifactsTable)
    session.run(lambda: table.move_cursor(row=tab_row))
    session.press("enter")
    session.pause()
    session.pause()
    session.pause()
    session.pause()
    return session


def _artifact_viewer_text(size):
    store, item = _artifact_viewer_store()
    return _open_artifact_at(_launch(store, size=size), item, 0)


def _artifact_viewer_list(size):
    store, item = _artifact_viewer_store()
    return _open_artifact_at(_launch(store, size=size), item, 1)


def _artifact_viewer_url_toast(size):
    store, item = _artifact_viewer_store()
    launcher = FakeLauncher(url_succeeds=True)
    return _open_artifact_at(_launch(store, size=size, launcher=launcher), item, 2)


def _artifact_viewer_filepath_toast(size):
    store, item = _artifact_viewer_store()
    fs = FakeFs(files={BRIEF_PATH: b"content"})
    launcher = FakeLauncher(path_succeeds=True)
    return _open_artifact_at(_launch(store, size=size, fs=fs, launcher=launcher), item, 3)


def _hub_theme(size):
    store, theme, _scan, _coding = _populated_store()
    return _open_hub(_launch(store, size=size), theme)


def _hub_done_item(size):
    store, _theme, scan, coding = _populated_store()
    store.close(coding, "done")
    store.close(scan, "done")
    return _open_hub(_launch(store, size=size), scan)


def _hub_blocked_dependency(size):
    store, waiting = _blocked_store()
    return _open_hub(_launch(store, size=size), waiting)


def _hub_needs_attention_human(size):
    store, item = _human_step_store()
    return _open_hub(_launch(store, size=size), item)


def _hub_step_node(size):
    store, _theme, _scan, coding = _populated_store()
    return _open_hub(_launch(store, size=size), coding)


def _hub_hierarchy_scrolled(size):
    store, item = _long_hierarchy_store()
    return _open_hub(_launch(store, size=size), item, tab="hierarchy")


def _hub_claude_unavailable(size):
    store, _theme, scan, _coding = _populated_store()
    return _open_hub(_launch(store, breaker_open=True, size=size), scan)


def _hub_long_description(size):
    store, item = _long_description_store()
    return _open_hub(_launch(store, size=size), item, tab="description")


SCREENS = {
    "priority-list#normal": _priority_normal,
    "priority-list#empty": _priority_empty,
    "priority-list#claude-unavailable": _priority_claude_unavailable,
    "priority-list#stacked": _priority_stacked,
    "backlog#normal": _backlog_normal,
    "backlog#empty": _backlog_empty,
    "backlog#empty-filtered": _backlog_empty_filtered,
    "backlog#picker-open": _backlog_picker_open,
    "backlog#claude-unavailable": _backlog_claude_unavailable,
    "backlog#stacked": _backlog_stacked,
    "hub#hierarchy": _hub_hierarchy,
    "hub#hierarchy-stacked": _hub_hierarchy_stacked,
    "hub#active-log": _hub_active_log,
    "hub#log-finished": _hub_log_finished,
    "hub#artifacts": _hub_artifacts,
    "hub#artifacts-stacked": _hub_artifacts_stacked,
    "artifact-viewer#text": _artifact_viewer_text,
    "artifact-viewer#list": _artifact_viewer_list,
    "artifact-viewer#url-toast": _artifact_viewer_url_toast,
    "artifact-viewer#filepath-toast": _artifact_viewer_filepath_toast,
    "hub#theme": _hub_theme,
    "hub#done-item": _hub_done_item,
    "hub#blocked-dependency": _hub_blocked_dependency,
    "hub#needs-attention-human": _hub_needs_attention_human,
    "hub#step-node": _hub_step_node,
    "hub#hierarchy-scrolled": _hub_hierarchy_scrolled,
    "hub#claude-unavailable": _hub_claude_unavailable,
    "hub#long-description": _hub_long_description,
}


def _plain_row(strip):
    return "".join(segment.text for segment in strip).rstrip()


def _coloured_row(strip):
    out = []
    for segment in strip:
        colour = segment.style.color if segment.style else None
        rgb = colour.get_truecolor() if colour else None
        if rgb is None:
            out.append(segment.text)
        else:
            out.append("\x1b[38;2;%d;%d;%dm%s\x1b[0m" % (rgb.red, rgb.green, rgb.blue, segment.text))
    return "".join(out).rstrip()


UNRENDERABLE = {}


def render(state, size=DEFAULT_SIZE, colour=False):
    if state in UNRENDERABLE:
        raise KeyError("%s cannot be rendered yet: %s" % (state, UNRENDERABLE[state]))
    if state not in SCREENS:
        raise KeyError(
            "unknown state %r; known states: %s" % (state, ", ".join(sorted(SCREENS)))
        )
    session = SCREENS[state](size)
    row = _coloured_row if colour else _plain_row
    try:
        strips = session.run(lambda: session.app.screen._compositor.render_strips())
        return "\n".join(row(strip) for strip in strips)
    finally:
        session.close()


def _parse_size(text):
    width, _, height = text.partition("x")
    return int(width), int(height)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tests/render.sh")
    parser.add_argument("state", nargs="?")
    parser.add_argument("--size", default="%dx%d" % DEFAULT_SIZE)
    parser.add_argument("--colour", action="store_true")
    args = parser.parse_args(argv)

    if not args.state:
        print("states this codebase can render:")
        for name in sorted(SCREENS):
            print("  %s" % name)
        print("\nstates the design names that this codebase cannot render yet:")
        for name in sorted(UNRENDERABLE):
            print("  %s - %s" % (name, UNRENDERABLE[name]))
        print("\nrender one with: bash tests/render.sh <state> [--size 100x30] [--colour]")
        return 0

    if args.state in UNRENDERABLE:
        print("%s cannot be rendered yet: %s" % (args.state, UNRENDERABLE[args.state]),
              file=sys.stderr)
        return 2

    if args.state not in SCREENS:
        print("unknown state %r" % args.state, file=sys.stderr)
        print("known states: %s" % ", ".join(sorted(SCREENS)), file=sys.stderr)
        return 2

    print(render(args.state, _parse_size(args.size), colour=args.colour))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
