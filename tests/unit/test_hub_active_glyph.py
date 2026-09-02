from textual.widgets import Static

from lightcycle.adapters.tui.design_system import ACTIVE_GLYPH_REST_INDEX
from lightcycle.adapters.tui.hub import HierarchyPagingTable, NodeHubScreen
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container


def _rendered_text(widget):
    strip = widget.render_line(0)
    return "".join(segment.text for segment in strip)


def _open_hub_on_active_step():
    store = FakeStore()
    item = store.create_item("Item")
    store.create_step("s", step="build", role="agent", parent=item)
    store.claim_ready("agent")
    session = launch(make_test_container(store=store))
    session.run(
        lambda: session.app.push_screen(NodeHubScreen(session.app.container, item, session.app._now))
    )
    session.pause()
    screen = session.app.screen
    screen._active_tab = "hierarchy"
    session.run(screen._apply_tab_visibility)
    session.pause()
    return session, screen


def test_active_glyph_animation_does_not_run_at_the_floor():
    session, screen = _open_hub_on_active_step()
    try:
        assert screen._active_glyph_timer is not None

        screen._hierarchy_floor = True
        session.run(screen._sync_active_glyph_animation)

        assert screen._active_glyph_timer is None
    finally:
        session.close()


def test_active_glyph_animation_restarts_after_floor_recovers_on_width_refresh():
    session, screen = _open_hub_on_active_step()
    try:
        assert screen._active_glyph_timer is not None

        screen._hierarchy_floor = True
        screen._active_glyph_timer.stop()
        screen._active_glyph_timer = None

        session.run(lambda: screen._render_hierarchy(screen._last_rows, initial=True))
        session.run(screen._apply_tab_visibility)
        session.pause()

        assert screen._active_glyph_timer is not None
    finally:
        session.close()


def test_pinned_ancestor_banner_pulses_when_its_own_row_is_active():
    store = FakeStore()
    item = store.create_item("Item")
    for i in range(39):
        store.create_step("s%d" % i, step="build", role="agent", parent=item)
    active_step = store.create_step("active", step="build", role="agent", parent=item)
    store.assign(active_step, "worker-1")
    store.update_state(active_step, State.IN_PROGRESS)

    session = launch(make_test_container(store=store))
    try:
        session.run(
            lambda: session.app.push_screen(
                NodeHubScreen(session.app.container, item, session.app._now)
            )
        )
        session.pause()
        screen = session.app.screen
        screen._active_tab = "hierarchy"
        session.run(screen._apply_tab_visibility)
        if screen._active_glyph_timer is not None:
            screen._active_glyph_timer.stop()
            screen._active_glyph_timer = None
        screen._active_glyph_frame = ACTIVE_GLYPH_REST_INDEX
        session.pause()
        table = screen.query_one(HierarchyPagingTable)
        table.move_cursor(row=table.row_count - 1)
        session.pause()

        banner = screen.query_one("#pinned-ancestor", Static)
        assert banner.display
        assert "◆" in _rendered_text(banner)

        session.run(screen._tick_active_glyph)

        assert "◈" in _rendered_text(banner)
    finally:
        session.close()
