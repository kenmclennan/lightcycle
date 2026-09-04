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

    def item(self, node_id, title, description="a description", **kwargs):
        self._next_id = node_id
        return self.create_item(title, description, **kwargs)

    def step(self, node_id, title, **kwargs):
        self._next_id = node_id
        return self.create_step(title, **kwargs)


REGISTRY_TITLE = "Registry table and identity-based repo resolution"
CLONE_TITLE = "Clone-on-demand: fetch an absent project on resolve"
SCAN_TITLE = "lc project scan: recursive discovery by git remote"
WORKFLOW = "lightcycle/spec-driven@abfb01d"


def _populated_store(claimed_minutes_ago=14):
    store = DemoStore(now=lambda: _at(claimed_minutes_ago))

    scan = store.item("LC-143.3", SCAN_TITLE, workflow=WORKFLOW)
    store.edit_node(
        scan,
        description="Phase 3 of the registry work. lc project scan walks a tree recursively "
        "and lists registration candidates.",
    )
    spec = store.step("LC-143.3.1", "write the spec", step="spec-writer", role="agent",
                      parent=scan)
    store.close(spec, "done")
    coding = store.step("LC-143.3.4", "write the code", step="write-code", role="agent",
                        parent=scan)
    store.step("LC-143.3.5", "open the pr", step="code-open-pr", role="agent", parent=scan)
    store.step("LC-143.3.6", "await merge", step="code-await-merge", role="human", parent=scan)
    store.claim_ready("agent")

    registry = store.item("LC-143.1", REGISTRY_TITLE, workflow=WORKFLOW)
    store.step("LC-143.1.4", "write the code", step="write-code", role="agent", parent=registry)
    store.claim_ready("agent")

    clone = store.item("LC-143.2", CLONE_TITLE, workflow=WORKFLOW)
    store.step("LC-143.2.4", "write the code", step="write-code", role="agent", parent=clone)

    store.add_artifact(scan, "repo", "kenmclennan/lightcycle")
    store.add_artifact(scan, "pr", "https://github.com/kenmclennan/lightcycle/pull/143")

    return store, scan, coding


LONG_DESCRIPTION = (
    "This item exists to fix a header that grows without bound. " * 50
).strip()


def _long_description_store(description=LONG_DESCRIPTION):
    store = DemoStore(now=lambda: _at(2))
    item = store.item("LC-319.1", SCAN_TITLE, workflow=WORKFLOW)
    if description is not None:
        store.edit_node(item, description=description)
    store.step("LC-319.1.4", "write the code", step="write-code", role="agent", parent=item)
    return store, item


def _blocked_store():
    store = DemoStore(now=lambda: _at(3))
    blocker = store.item("LC-143.1", REGISTRY_TITLE, workflow=WORKFLOW)
    blocking_step = store.step("LC-143.1.4", "write the code", step="write-code",
                               role="agent", parent=blocker)
    waiting = store.item("LC-143.2", CLONE_TITLE, workflow=WORKFLOW)
    store.step("LC-143.2.4", "write the code", step="write-code", role="agent",
               parent=waiting, deps=[blocking_step])
    return store, waiting


def _human_step_store():
    store = DemoStore(now=lambda: _at(6))
    item = store.item("LC-143.3", SCAN_TITLE, workflow=WORKFLOW)
    step = store.step("LC-143.3.6", "await merge", step="code-await-merge", role="human",
                      parent=item)
    store.update_metadata(step, {"needs": "Resolve the merge conflict manually"})
    return store, item


LONG_ESCALATION_REASON = (
    "CI still pending on PR #424 head 7d4d840 (integration and unit-feature jobs in-progress) - "
    "scenario review itself is clean (see feedback), just waiting on CI to conclude before "
    "posting a pass verdict. Also, the integration job flaked once and was retried successfully "
    "before landing."
)


def _long_reason_store():
    store = DemoStore(now=lambda: _at(6))
    item = store.item("LC-143.3", SCAN_TITLE, workflow=WORKFLOW)
    step = store.step("LC-143.3.6", "await merge", step="code-await-merge", role="human",
                      parent=item)
    store.update_metadata(
        step,
        {"needs": "Resolve the merge conflict manually", "reason": LONG_ESCALATION_REASON},
    )
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
        "LC-3900.100.100", STACKED_TITLE, step="handle-feedback", role="agent",
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
        "LC-290.1.86", STACKED_TITLE, step="implement-features", role="agent",
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
    item = store.item(
        "LC-290.1", LONG_ITEM_TITLE, workflow="flynns-workflows/blueprint-delivery@0333918"
    )
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
    store, _scan, _coding = _populated_store()
    return _launch(store, size=size)


def _priority_empty(size):
    return _launch(FakeStore(), size=size)


def _priority_claude_unavailable(size):
    store, _scan, _coding = _populated_store()
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
    store, scan, _coding = _populated_store()
    return _open_hub(_launch(store, size=size), scan, tab="hierarchy")


def _hub_hierarchy_stacked(size):
    store, item, _step = _stacked_hierarchy_store()
    return _open_hub(_launch(store, size=size), item, tab="hierarchy")


_LOG_PATH = "/fake/logs/worker-write-code.log"

_LOG_EXCERPT = (
    b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_9gmXGiUWuLMEWJM07HdrCHvm","type":"message","role":"assistant","content":[{"type":"text","text":"Now run the tests and linter to verify everything is green."}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":555,"cache_read_input_tokens":34014,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":555},"output_tokens":2,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"00ac1a59-a39e-52be-a577-5f13db9ba373","uuid":"51941f41-2347-f966-5d92-5fcedbfe9322","request_id":"req_pMH4CqBg8N69h5GRqIwnWGjD"}\n'
    b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_9gmXGiUWuLMEWJM07HdrCHvm","type":"message","role":"assistant","content":[{"type":"tool_use","id":"toolu_STYh6S2JGnIaIXZlaDMWMb9E","name":"Bash","input":{"command":"cd /Users/dev/workspace/projects/sample-app/.worktrees/wt1 && bash tests/run.sh 2>&1 | tail -20","description":"Run test suite in worktree","timeout":120000},"caller":{"type":"direct"}}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":555,"cache_read_input_tokens":34014,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":555},"output_tokens":2,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"00ac1a59-a39e-52be-a577-5f13db9ba373","uuid":"21396294-7e2e-cd22-c1d6-1e779a84c898","request_id":"req_pMH4CqBg8N69h5GRqIwnWGjD"}\n'
    b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_09rMu7EmumBuaNlF9E07GlRh","type":"message","role":"assistant","content":[{"type":"tool_use","id":"toolu_ryJZCjW0BPFqbnSaDcM9qI8q","name":"Bash","input":{"command":"cd /Users/dev/workspace/projects/sample-app/.worktrees/wt1 && uv run ruff check .","description":"Run ruff linter in worktree"},"caller":{"type":"direct"}}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":262,"cache_read_input_tokens":34569,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":262},"output_tokens":57,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"00ac1a59-a39e-52be-a577-5f13db9ba373","uuid":"df300c01-62eb-94e0-d8de-887acf423dd5","request_id":"req_9B3HQDq4jWof6jmnzDjGAQH5"}\n'
    b'{"type":"user","message":{"role":"user","content":[{"tool_use_id":"toolu_ryJZCjW0BPFqbnSaDcM9qI8q","type":"tool_result","content":"All checks passed!","is_error":false}]},"parent_tool_use_id":null,"session_id":"00ac1a59-a39e-52be-a577-5f13db9ba373","uuid":"8fdf8e0d-ceaa-77b3-2d6e-ceb3b321b986","timestamp":"2026-07-03T12:42:28.304Z","tool_use_result":{"stdout":"All checks passed!","stderr":"","interrupted":false,"isImage":false,"noOutputExpected":false}}\n'
    b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_eufvys2GV6nPBf3orlLiVsyh","type":"message","role":"assistant","content":[{"type":"text","text":"Ruff is clean. Waiting for tests."}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":222,"cache_read_input_tokens":34831,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":222},"output_tokens":2,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"00ac1a59-a39e-52be-a577-5f13db9ba373","uuid":"9642b52c-ed05-2c55-7f8f-f70c6a8a14f3","request_id":"req_MVuMIm79yNF5BpftMuHGjx5F"}\n'
    b'{"type":"assistant","message":{"model":"claude-sonnet-5","id":"msg_ov1gqhQMuBaHHEuS4KT2yglE","type":"message","role":"assistant","content":[{"type":"text","text":"# User Story Acceptance Criteria Extraction\\n\\n## 18fdcc37-373a-4b2c-a045-18a1c20e0fc3 \\u2014 \\"Open the item detail view\\"\\n- Given the priority list is showing, when I select a row and press Enter or \\u2192, then the item\'s detail view opens, replacing the list on screen.\\n- Given the detail view has just opened, when it renders, then it shows the item\'s identity - id, title, owning project, theme (if it has one), and the workflow it\'s running under (if any).\\n- Given the item has a description, when the detail view renders, then the description is shown in the header, below the identity fields.\\n- Given the item has no description, when the detail view renders, then no description line is shown.\\n\\n## 45d7d629-f736-4875-8470-f928558a88ea \\u2014 \\"See the item\'s current step, role, and elapsed time\\"\\n- Given an item\'s detail view is open, when I look at it, then it names the current step.\\n- Given the current step is performed by a worker, when I look at the detail view, then it names the role (e.g. write-code, review-code).\\n- Given the item is active, when I look at the detail view, then it shows an approximate elapsed time, matching the list\'s format (e.g. \'14m\', \'1h 7m\').\\n- Given the current step is a human step with no worker, when I look at the detail view, then no role or elapsed time is shown for a worker that doesn\'t exist.\\n\\n## 265befe7-7a49-4219-8f4c-8aabee2f201d \\u2014 \\"Return to the list without losing position\\"\\n- Given I opened an item\'s detail view from a specific row, when I close it with Esc or \\u2190, then the priority list reappears with that row still selected and the same scroll position.\\n- Given I scrolled or navigated within the detail view itself, when I return to the list, then the list\'s scroll position is unaffected by anything I did inside the detail view.\\n\\n## 4bee4625-16c6-4f37-a7af-01893eba78ea \\u2014 \\"See why an item is escalated\\"\\n- Given an item is blocked on a dependency, when I open its detail view, then it names the specific blocking dependency.\\n- Given an item\'s current step is escalated (e.g. rejected, needing rework), when I open its detail view, then it names what\'s being asked of me.\\n- Given an item is active or queued, not needs-attention, when I open its detail view, then no escalation reason is shown.\\n- Given an item is blocked on another item\'s completion, when I select the named blocking item with Enter or \\u2192, then I\'m taken straight to that item\'s own detail view.\\n- Given I jumped to a blocking item\'s hub via that link, when I press Esc or \\u2190, then I return to the original, blocked item\'s hub - not the priority list - at the tab I was on.\\n\\n## 74dd1219-8a28-4c16-a293-83a82b4db930 \\u2014 \\"Land on the tab that matches the item\'s status\\"\\n- Given the node is active (a worker is performing its current step), when I open it, then it lands on the Log tab.\\n- Given the node is a needs-attention item on a human step (e.g. await-merge, or rejected/needs rework), when I open it, then it lands on the Artifacts tab.\\n- Given the node is blocked on another item\'s completion, or is still queued/not yet run, when I open it, then it lands on the Hierarchy tab.\\n- Given the node is done, when I open it, then it lands on the Artifacts tab, same as a needs-attention item on a human step.\\n- Given the node is a theme, when I open it, then it lands on the Hierarchy tab, since a theme has no single item-level state of its own to key a different default off.\\n\\n## 3480e340-d1f3-44ac-a0d8-e6ef269f6d13 \\u2014 \\"Cycle tabs with [ and ]\\"\\n- Given a node\'s hub is open, when I press ], then the next tab in the Hierarchy \\u2192 Log \\u2192 Artifacts cycle becomes active.\\n- Given a node\'s hub is open, when I press [, then the previous tab in that cycle becomes active.\\n- Given a node\'s hub is open, on any tab, when I press Tab, then I jump straight to Backlog (or Current work), same as everywhere else - it never gets reinterpreted as a tab-cycle key.\\n- (What field notes cycle order explicitly: ] moves Hierarchy \\u2192 Log \\u2192 Artifacts \\u2192 Hierarchy; [ moves the reverse direction.)\\n\\n## 9c53daa8-4b1a-425e-a3be-4f4a2ba53849 \\u2014 \\"See which nodes have content\\"\\n- Given a node has at least one artifact whose internal flag is false, when it appears in the hierarchy, then it shows a content indicator.\\n- Given a node has only internal-flagged artifacts, or none at all, when it appears in the hierarchy, then no content indicator is shown.\\n- Given the content indicator is shown, when I open that node, then at least one artifact I can actually view is there.\\n\\n## f448a52c-0755-4ded-bea1-7992a79555e4 \\u2014 \\"See the hierarchy from its root node down\\"\\n- Given a node under a theme, when I open the hierarchy from it, then it shows that theme at the top with all its items and their steps below.\\n- Given a themeless item, when I open the hierarchy from it or one of its steps, then it shows that item as the root, with its steps below - no blank or missing theme row.\\n- Given the hierarchy is showing, when I look at any node, then its depth (theme/item/step) is visible by indentation.\\n\\n## 833b6039-ab42-4b6a-b1d7-e757b9dc9233 \\u2014 \\"See each node\'s id, status, and role in the hierarchy\\"\\n- Given a node in the hierarchy, when it renders, then its own real id (e.g. LC-143.3.4) is shown alongside its title, and its current state is shown using the same labels/icons/colours as the priority list.\\n- Given a node\'s state changes while the hierarchy is open, when that happens, then it updates without a manual refresh.\\n- Given a step node has been performed, or is being performed, by a worker, when it renders in the hierarchy, then its role (e.g. write-code, review-code) is shown alongside its state.\\n- Given a step node is a human step, when it renders, then no role is shown for a worker that doesn\'t exist. (Context: for human steps the literal text \\"human\\" is rendered in the role slot - the distinction is worker-role name vs. the \\"human\\" value, not role vs. no role at all.)\\n- Given a node is blocked on another item\'s completion, when it renders in the hierarchy, then a dependency indicator is shown alongside its state, distinct from other blocked reasons.\\n\\n## 92e81697-0e0b-4290-ac26-ba46ca3f680d \\u2014 \\"Scroll the hierarchy with the keyboard\\"\\n- Given the hierarchy has more rows than fit on screen, when I press up/down, then the selection moves to the previous/next node, scrolling as needed.\\n- Given the selection is at the first or last node, when I press past the end, then it stays put rather than wrapping.\\n- Given the hierarchy is longer than one screen, when I press Ctrl+U or Ctrl+D, then the view jumps by roughly a full screen at a time.\\n\\n## ccd1d6ac-5812-43f6-a9bc-4cdfb667fa57 \\u2014 \\"Open a node from the hierarchy\\"\\n- Given any node (theme, item, or step) is selected in the hierarchy, when I confirm the selection with Enter or \\u2192, then it opens into its own tabbed hub, landing on the tab that matches its state.\\n- Given the selected node is a step rather than a theme or item, when its hub opens, then the header shows its role and state in place of the theme/workflow/description fields, which only apply to themes and items.\\n\\n## ded8dbd1-c1ef-45c0-97df-562b72a52e91 \\u2014 \\"Return to the hierarchy tab without losing position\\"\\n- Given I opened a node from the Hierarchy tab, when I close it with Esc or \\u2190, then the Hierarchy tab reappears with that node still selected and scrolled to the same position.\\n\\n## eaa87e0b-0a4f-4c35-b3ff-d372ec1a286f \\u2014 \\"Keep ancestry visible while I scroll\\"\\n- Given I scroll down past a node\'s parent item or theme, when they leave the visible scroll area, then their row stays pinned to the top instead of scrolling away.\\n- Given I scroll back up to where the ancestor\'s actual row is, when it comes back into normal view, then the pinned duplicate is no longer shown.\\n\\n## 8f6e008e-f9d8-4c6d-a061-02da7002bd42 \\u2014 \\"Jump straight to a node\'s artifacts or log from the hierarchy\\"\\n- Given a node is highlighted in the tree, when I press a, then its artifact list opens directly.\\n- Given a node is highlighted in the tree, when I press l, then its log opens directly - live if it\'s the active step, past/historical if it\'s done.\\n- Given the highlighted node is a human step or hasn\'t run yet, when I press l, then the shortcut is a no-op, consistent with there being no log content to show.\\n\\n## 3b552243-e146-426c-b0e1-2c3c0d2b3801 \\u2014 \\"See the current node highlighted in the hierarchy\\"\\n- Given the current node is a root item or theme with no parent, when I view the Hierarchy tab, then it\'s highlighted at the top row.\\n- Given the current node is nested under a theme and/or a parent item, when I view the Hierarchy tab, then it\'s highlighted at its actual depth, not the top row.\\n\\n## 7f92f015-2d19-449f-bb47-f389e6dc9691 \\u2014 \\"Explore a backlog item\'s context in the hierarchy\\"\\n- Given a backlog item is selected, when I open it with Enter or \\u2192, then its hub opens, landing on the Hierarchy tab, showing its place in the tree.\\n\\n## 572ae397-7fb6-453c-832a-80700e1bd483 \\u2014 \\"Return to the backlog without losing position\\"\\n- Given I opened a backlog item\'s hub, when I close it with Esc or \\u2190, then the backlog reappears at the same scroll/selection position.\\n\\n## 02c20dfb-88af-4b91-887b-6c9f1fa660aa \\u2014 \\"See whether Claude is available to process work\\"\\n- Given the circuit breaker is closed, when I view any screen, then the footer\'s status line shows \\"claude available\\" in its default styling, next to the pool status.\\n- Given the circuit breaker is open, when I view any screen, then the footer\'s status line shows \\"claude unavailable\\" plus the time it will next probe for recovery (e.g. \\"resumes 14:32:00\\"), styled as an alert.\\n- Given the breaker opened while a step\'s worker was running and that worker was killed and reclaimed back to ready, when I open that node, then the hub shows its real current state (queued, not active) - the same reclaim behavior the engine already applies to any lost worker, not new behavior this indicator introduces.\\n- Given the breaker closes again, when the next poll runs, then the footer returns to \\"claude available\\" without requiring a restart."}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":2,"cache_creation_input_tokens":26640,"cache_read_input_tokens":11539,"cache_creation":{"ephemeral_5m_input_tokens":26640,"ephemeral_1h_input_tokens":0},"output_tokens":2,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":"toolu_GTXBsMaVjbYXRt8QkkcIvjKH","session_id":"930d5260-0f07-d352-3716-5e61f077461d","uuid":"f5ecb5fd-3346-42c6-7546-4de2860bfd35","timestamp":"2026-08-17T13:42:03.904Z","request_id":"req_je4TjcfGsmzB8x9QrmXpERUM","subagent_type":"general-purpose","task_description":"Summarize WI-005 story acceptance criteria"}\n'
)


def _hub_active_log(size):
    store, _scan, coding = _populated_store()
    fs = FakeFs(files={_LOG_PATH: _LOG_EXCERPT})
    workers = FakeWorkers(
        workers=[{"step": coding, "role": "write-code", "pid": 4242, "pid_started": None,
                  "log": _LOG_PATH}],
        alive_pids={4242},
    )
    return _open_hub(_launch(store, size=size, fs=fs, workers=workers), coding, tab="log")


def _hub_log_finished(size):
    store, _scan, coding = _populated_store()
    fs = FakeFs(files={_LOG_PATH: _LOG_EXCERPT})
    workers = FakeWorkers(
        workers=[{"step": coding, "role": "write-code", "pid": 4242, "pid_started": None,
                  "log": _LOG_PATH}],
        alive_pids=set(),
    )
    return _open_hub(_launch(store, size=size, fs=fs, workers=workers), coding, tab="log")


def _hub_artifacts(size):
    store, scan, _coding = _populated_store()
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
BRIEF_PATH = "/home/dev/workspace/specs/GRID-012-agents-report-tool-friction.md"


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


def _hub_done_item(size):
    store, scan, coding = _populated_store()
    store.close(coding, "done")
    store.close(scan, "done")
    return _open_hub(_launch(store, size=size), scan)


def _hub_blocked_dependency(size):
    store, waiting = _blocked_store()
    return _open_hub(_launch(store, size=size), waiting)


def _hub_needs_attention_human(size):
    store, item = _human_step_store()
    return _open_hub(_launch(store, size=size), item)


def _hub_escalated_long_reason(size):
    store, item = _long_reason_store()
    return _open_hub(_launch(store, size=size), item)


def _hub_step_node(size):
    store, _scan, coding = _populated_store()
    return _open_hub(_launch(store, size=size), coding)


def _detail_store():
    store = DemoStore(now=lambda: _at(6))
    item = store.item("LC-143.3", SCAN_TITLE, workflow=WORKFLOW)
    step = store.step(
        "LC-143.3.6", "await merge", step="code-await-merge", role="human", parent=item,
    )
    pid = store.open_pass(item)
    store.set_step_pass(step, pid)
    rid = store.open_run(item, pid, "code")
    store.set_run_field(
        rid, branch="feat/LC-143-scan", pr="https://github.com/kenmclennan/lightcycle/pull/143"
    )
    store.set_notes(step, "opened for review")
    return store, step


def _hub_detail(size):
    store, step = _detail_store()
    fs = FakeFs(metas={"code-await-merge": {"step": "code-await-merge", "phase": "code"}})
    return _open_hub(_launch(store, size=size, fs=fs), step)


def _hub_hierarchy_scrolled(size):
    store, item = _long_hierarchy_store()
    return _open_hub(_launch(store, size=size), item, tab="hierarchy")


def _hub_claude_unavailable(size):
    store, scan, _coding = _populated_store()
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
    "hub#done-item": _hub_done_item,
    "hub#blocked-dependency": _hub_blocked_dependency,
    "hub#needs-attention-human": _hub_needs_attention_human,
    "hub#escalated-long-reason": _hub_escalated_long_reason,
    "hub#step-node": _hub_step_node,
    "hub#detail": _hub_detail,
    "hub#hierarchy-scrolled": _hub_hierarchy_scrolled,
    "hub#claude-unavailable": _hub_claude_unavailable,
    "hub#long-description": _hub_long_description,
}


def _plain_row(strip):
    return "".join(segment.text for segment in strip).rstrip()


def _coloured_row(strip):
    out = []
    for segment in strip:
        fg = segment.style.color if segment.style else None
        bg = segment.style.bgcolor if segment.style else None
        codes = []
        if fg is not None:
            rgb = fg.get_truecolor()
            codes.append("38;2;%d;%d;%d" % (rgb.red, rgb.green, rgb.blue))
        if bg is not None:
            rgb = bg.get_truecolor()
            codes.append("48;2;%d;%d;%d" % (rgb.red, rgb.green, rgb.blue))
        if codes:
            out.append("\x1b[%sm%s\x1b[0m" % (";".join(codes), segment.text))
        else:
            out.append(segment.text)
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
