import argparse
import datetime
import sys

from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeBreakerPort, FakeLock, launch, make_test_container

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


def _populated_store(claimed_minutes_ago=14):
    store = DemoStore(now=lambda: _at(claimed_minutes_ago))
    theme = store.theme("LC-143", THEME_TITLE, project="lightcycle")

    scan = store.item("LC-143.3", SCAN_TITLE, theme=theme)
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

    registry = store.item("LC-143.1", REGISTRY_TITLE, theme=theme)
    store.step("LC-143.1.4", "write the code", step="write-code", role="write-code", parent=registry)

    clone = store.item("LC-143.2", CLONE_TITLE, theme=theme)
    store.step("LC-143.2.4", "write the code", step="write-code", role="write-code", parent=clone)

    store.add_artifact(scan, "repo", "kenmclennan/lightcycle")
    store.add_artifact(scan, "pr", "https://github.com/kenmclennan/lightcycle/pull/143")

    return store, theme, scan, coding


def _blocked_store():
    store = DemoStore(now=lambda: _at(3))
    theme = store.theme("LC-143", THEME_TITLE, project="lightcycle")
    blocker = store.item("LC-143.1", REGISTRY_TITLE, theme=theme)
    blocking_step = store.step("LC-143.1.4", "write the code", step="write-code",
                               role="write-code", parent=blocker)
    waiting = store.item("LC-143.2", CLONE_TITLE, theme=theme)
    store.step("LC-143.2.4", "write the code", step="write-code", role="write-code",
               parent=waiting, deps=[blocking_step])
    return store, waiting


def _human_step_store():
    store = DemoStore(now=lambda: _at(6))
    theme = store.theme("LC-143", THEME_TITLE, project="lightcycle")
    item = store.item("LC-143.3", SCAN_TITLE, theme=theme)
    store.step("LC-143.3.6", "await merge", step="code-await-merge", role="human", parent=item,
               attention=True)
    return store, item


def _backlog_store():
    store = DemoStore()
    store.item("LC-273", "Row title repeats the step name", project="lightcycle")
    store.item("LC-275", "Active glyph unreadable at terminal size", project="lightcycle")
    store.item("LC-277", "Human-facing step display names", project="saga")
    return store


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
    item = store.item("LC-290.1", LONG_ITEM_TITLE, theme=theme)
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


def _launch(store, *, lock_running=True, breaker_open=False, size=DEFAULT_SIZE):
    container = make_test_container(
        store=store,
        lock=FakeLock(running=lock_running),
        breaker=FakeBreakerPort(
            is_open=breaker_open,
            reset_at=(NOW + datetime.timedelta(minutes=4)).timestamp() if breaker_open else None,
        ),
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


def _backlog_normal(size):
    session = _launch(_backlog_store(), size=size)
    session.press("tab")
    return session


def _backlog_empty(size):
    session = _launch(FakeStore(), size=size)
    session.press("tab")
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


def _hub_active_log(size):
    store, _theme, scan, _coding = _populated_store()
    return _open_hub(_launch(store, size=size), scan, tab="log")


def _hub_artifacts(size):
    store, _theme, scan, _coding = _populated_store()
    return _open_hub(_launch(store, size=size), scan, tab="artifacts")


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


def _hub_hierarchy_scrolled(size):
    store, item = _long_hierarchy_store()
    return _open_hub(_launch(store, size=size), item, tab="hierarchy")


def _hub_claude_unavailable(size):
    store, _theme, scan, _coding = _populated_store()
    return _open_hub(_launch(store, breaker_open=True, size=size), scan)


SCREENS = {
    "priority-list#normal": _priority_normal,
    "priority-list#empty": _priority_empty,
    "priority-list#claude-unavailable": _priority_claude_unavailable,
    "backlog#normal": _backlog_normal,
    "backlog#empty": _backlog_empty,
    "backlog#picker-open": _backlog_picker_open,
    "backlog#claude-unavailable": _backlog_claude_unavailable,
    "hub#hierarchy": _hub_hierarchy,
    "hub#active-log": _hub_active_log,
    "hub#artifacts": _hub_artifacts,
    "hub#theme": _hub_theme,
    "hub#done-item": _hub_done_item,
    "hub#blocked-dependency": _hub_blocked_dependency,
    "hub#needs-attention-human": _hub_needs_attention_human,
    "hub#hierarchy-scrolled": _hub_hierarchy_scrolled,
    "hub#claude-unavailable": _hub_claude_unavailable,
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


def render(state, size=DEFAULT_SIZE, colour=False):
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
        print("\nrender one with: bash tests/render.sh <state> [--size 100x30] [--colour]")
        return 0

    if args.state not in SCREENS:
        print("unknown state %r" % args.state, file=sys.stderr)
        print("known states: %s" % ", ".join(sorted(SCREENS)), file=sys.stderr)
        return 2

    print(render(args.state, _parse_size(args.size), colour=args.colour))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
