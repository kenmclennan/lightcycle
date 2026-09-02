from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container
from lightcycle.adapters.tui.footer import DashboardFooter
from lightcycle.adapters.tui.hub import HierarchyPagingTable, HubHeader, HubTabStrip, NodeHubScreen


def _rendered_row_text(session, widget):
    strip = session.app.screen._compositor.render_strips()[widget.region.y]
    start, end = widget.region.x, widget.region.x + widget.region.width
    return "".join(segment.text for segment in strip.crop(start, end))


def _open_hub():
    store = FakeStore()
    item = store.create_item("Item")
    store.create_step("s", step="build", role="agent", parent=item)
    session = launch(make_test_container(store=store))
    session.press("enter")
    return session


def test_tab_strip_sits_immediately_below_the_header_on_every_tab():
    session = _open_hub()
    try:
        header = session.app.screen.query_one(HubHeader)
        header_bottom = header.region.y + header.region.height
        tab_strip = session.app.screen.query_one(HubTabStrip)
        assert tab_strip.region.y == header_bottom

        session.press("]")
        assert tab_strip.region.y == header_bottom

        session.press("]")
        assert tab_strip.region.y == header_bottom
    finally:
        session.close()


def test_hub_footer_status_and_shortcut_lines_are_painted():
    session = _open_hub()
    try:
        footer = session.app.screen.query_one(DashboardFooter)
        status_bar, shortcut_bar = footer.children
        status_text = _rendered_row_text(session, status_bar)
        shortcut_text = _rendered_row_text(session, shortcut_bar)
        assert "pool" in status_text
        assert "switch tab" in shortcut_text
    finally:
        session.close()


def test_priority_list_footer_status_and_shortcut_lines_are_painted():
    store = FakeStore()
    store.create_step("a", step="build", role="agent")
    session = launch(make_test_container(store=store))
    try:
        footer = session.app.screen.query_one(DashboardFooter)
        status_bar, shortcut_bar = footer.children
        status_text = _rendered_row_text(session, status_bar)
        shortcut_text = _rendered_row_text(session, shortcut_bar)
        assert "pool" in status_text
        assert "quit" in shortcut_text
    finally:
        session.close()


def test_hierarchy_cursor_survives_a_layout_forced_rerender():
    store = FakeStore()
    item = store.create_item("Item")
    done_step = store.create_step("s1", step="build", role="agent", parent=item)
    queued_step = store.create_step("s2", step="write-code", role="agent", parent=item)
    store.close(done_step, "done")
    session = launch(make_test_container(store=store))
    try:
        session.run(
            lambda: session.app.push_screen(NodeHubScreen(session.app.container, item, session.app._now))
        )
        session.pause()
        screen = session.app.screen
        screen._active_tab = "hierarchy"
        session.run(screen._apply_tab_visibility)
        session.pause()

        table = screen.query_one(HierarchyPagingTable)
        row_ids = [row.key.value for row in table.ordered_rows]
        assert row_ids[table.cursor_row] == queued_step

        done_row = row_ids.index(done_step)
        table.move_cursor(row=done_row)
        session.pause()

        session.run(lambda: screen._render_hierarchy(screen._last_rows, initial=True))
        session.pause()

        assert table.cursor_row == done_row
    finally:
        session.close()


def test_backlog_footer_status_and_shortcut_lines_are_painted():
    store = FakeStore()
    store.create_item("todo item")
    session = launch(make_test_container(store=store))
    try:
        session.press("tab")
        footer = session.app.screen.query_one(DashboardFooter)
        status_bar, shortcut_bar = footer.children
        status_text = _rendered_row_text(session, status_bar)
        shortcut_text = _rendered_row_text(session, shortcut_bar)
        assert "pool" in status_text
        assert "filter" in shortcut_text
    finally:
        session.close()
