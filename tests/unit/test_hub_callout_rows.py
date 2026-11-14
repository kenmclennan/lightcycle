from lightcycle.adapters.tui.hub import HierarchyPagingTable, NodeHubScreen
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


def test_the_turns_column_widens_for_a_longer_callout_status():
    store, item, gate = _store_with({"a": _record("running", True)})
    session, screen = _open(store, item)
    try:
        table = screen.query_one(HierarchyPagingTable)
        layout = screen._hierarchy_layout(table, screen._last_rows)

        assert layout.atomic_widths["turns"] >= len("running · holds gate")
    finally:
        session.close()
