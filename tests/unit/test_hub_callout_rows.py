from types import SimpleNamespace

from lightcycle.adapters.tui.hub import DetailTable, HierarchyPagingTable, NodeHubScreen
from lightcycle.domain.work import State
from lightcycle.domain.work.callout_runs import CALLOUT_RUNS, dump_runs
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container


def _record(status, wait=False, started=0, finished=None, artifacts=None):
    record = {"status": status, "wait": wait, "started": started, "artifacts": artifacts or []}
    if finished is not None:
        record["finished"] = finished
    if status == "failed":
        record["message"] = "boom"
    return record


def _store_with(runs, human=True):
    store = FakeStore()
    item = store.create_item("Item", "a description")
    gate = store.create_step(stage="gate", role="human" if human else "agent", item=item)
    store.update_state(gate, State.WAITING)
    store.replace_artifact(gate, CALLOUT_RUNS, dump_runs(runs), internal=True)
    return store, item, gate


def _open(store, node, **kwargs):
    session = launch(make_test_container(store=store))
    session.run(
        lambda: session.app.push_screen(
            NodeHubScreen(session.app.container, node, session.app._now, **kwargs)
        )
    )
    session.pause()
    session.pause()
    return session, session.app.screen


def _table_keys(screen):
    table = screen.query_one(HierarchyPagingTable)
    return [row.key.value for row in table.ordered_rows]


def _select(session, screen, row_key):
    calls = []
    screen.switch_at = lambda *a, **k: calls.append((a, k))
    event = SimpleNamespace(
        data_table=screen.query_one(HierarchyPagingTable),
        row_key=SimpleNamespace(value=row_key),
        stop=lambda: None,
    )
    session.run(lambda: screen.on_data_table_row_selected(event))
    return calls


def test_the_table_holds_one_row_per_step_and_callout_with_unique_keys():
    store, item, gate = _store_with({"a": _record("ok", finished=5), "b": _record("running", True)})
    session, screen = _open(store, item)
    try:
        keys = _table_keys(screen)

        assert keys == [item, gate, "callout:%s:a" % gate, "callout:%s:b" % gate]
        assert len(set(keys)) == len(keys)
    finally:
        session.close()


def test_a_callout_finishing_between_polls_rebuilds_and_keeps_the_step_key():
    store, item, gate = _store_with({"a": _record("running", True)})
    session, screen = _open(store, item)
    try:
        before = screen._last_hierarchy_shape
        assert gate in _table_keys(screen)

        store.replace_artifact(
            gate, CALLOUT_RUNS, dump_runs({"a": _record("ok", finished=9)}), internal=True)
        session.run(screen.poll_refresh)
        session.pause()

        assert screen._last_hierarchy_shape != before
        assert gate in _table_keys(screen)
        assert "callout:%s:a" % gate in _table_keys(screen)
    finally:
        session.close()


def test_the_active_glyph_timer_ignores_callout_rows():
    store, item, gate = _store_with({"a": _record("running", True)})
    session, screen = _open(store, item)
    try:
        session.run(lambda: screen._render_hierarchy(screen._last_rows, False, initial=True))

        assert screen._active_glyph_ids() == ()
        assert screen._active_glyph_timer is None
    finally:
        session.close()


def test_selecting_a_running_callout_opens_the_gate_detail_on_its_key():
    store, item, gate = _store_with({"a": _record("running", True)})
    session, screen = _open(store, item)
    try:
        calls = _select(session, screen, "callout:%s:a" % gate)

        assert calls == [((gate,), {"initial_tab": "detail", "detail_key": "callout:a"})]
    finally:
        session.close()


def test_selecting_a_failed_callout_lands_on_its_key():
    store, item, gate = _store_with({"a": _record("failed", finished=4)})
    session, screen = _open(store, item)
    try:
        calls = _select(session, screen, "callout:%s:a" % gate)

        assert calls == [((gate,), {"initial_tab": "detail", "detail_key": "callout:a"})]
    finally:
        session.close()


def test_selecting_an_ok_callout_with_artifacts_lands_on_its_first_artifact():
    artifacts = [
        {"label": "One", "kind": "text", "value": "1"},
        {"label": "Two", "kind": "text", "value": "2"},
    ]
    store, item, gate = _store_with({"a": _record("ok", finished=4, artifacts=artifacts)})
    session, screen = _open(store, item)
    try:
        calls = _select(session, screen, "callout:%s:a" % gate)

        assert calls == [((gate,), {"initial_tab": "detail", "detail_key": "callout:a:1"})]
    finally:
        session.close()


def test_selecting_an_ok_callout_with_no_artifacts_opens_the_detail_tab_without_a_key():
    store, item, gate = _store_with({"a": _record("ok", finished=4)})
    session, screen = _open(store, item)
    try:
        calls = _select(session, screen, "callout:%s:a" % gate)

        assert calls == [((gate,), {"initial_tab": "detail", "detail_key": None})]
    finally:
        session.close()


def test_selecting_a_step_row_still_switches_with_no_tab():
    store, item, gate = _store_with({"a": _record("running", True)})
    session, screen = _open(store, item)
    try:
        calls = _select(session, screen, gate)

        assert calls == [((gate,), {})]
    finally:
        session.close()


def _detail_keys(screen):
    return [row.key.value for row in screen.query_one(DetailTable).ordered_rows]


def _cursor_key(screen):
    table = screen.query_one(DetailTable)
    return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value


def test_a_hub_given_a_detail_key_places_the_cursor_on_it():
    store, item, gate = _store_with({"a": _record("running", True), "b": _record("failed", finished=3)})
    session, screen = _open(store, gate, initial_tab="detail", detail_key="callout:b")
    try:
        assert "callout:b" in _detail_keys(screen)
        assert _cursor_key(screen) == "callout:b"
    finally:
        session.close()


def test_an_unknown_detail_key_falls_to_the_first_row():
    store, item, gate = _store_with({"a": _record("running", True)})
    session, screen = _open(store, gate, initial_tab="detail", detail_key="callout:nope")
    try:
        assert _cursor_key(screen) == _detail_keys(screen)[0]
    finally:
        session.close()


def test_the_turns_column_widens_for_a_longer_callout_status():
    store, item, gate = _store_with({"a": _record("running", True)})
    session, screen = _open(store, item)
    try:
        table = screen.query_one(HierarchyPagingTable)
        layout = screen._hierarchy_layout(table, screen._last_rows)

        assert layout.atomic_widths["turns"] >= len("running · holds gate")
    finally:
        session.close()
