import pytest

from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container
from lightcycle.adapters.tui.footer import DashboardFooter
from lightcycle.adapters.tui.hub import (
    ArtifactsTable,
    CostPane,
    DescriptionPane,
    DetailTable,
    HierarchyPagingTable,
    HubHeader,
    HubTabStrip,
    LogPane,
    NodeHubScreen,
)
from tests.support.step_factory import create_owned_step


def _rendered_row_text(session, widget):
    strip = session.app.screen._compositor.render_strips()[widget.region.y]
    start, end = widget.region.x, widget.region.x + widget.region.width
    return "".join(segment.text for segment in strip.crop(start, end))


def _open_hub():
    store = FakeStore()
    item = store.create_item("Item", "a description")
    store.create_step(step="build", role="agent", parent=item)
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
    create_owned_step(store, "a", step="build", role="agent")
    session = launch(make_test_container(store=store), size=(100, 24))
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
    item = store.create_item("Item", "a description")
    done_step = store.create_step(step="build", role="agent", parent=item)
    queued_step = store.create_step(step="write-code", role="agent", parent=item)
    store.complete_node(done_step, "done")
    session = launch(make_test_container(store=store))
    try:
        session.run(
            lambda: session.app.push_screen(NodeHubScreen(session.app.container, item, session.app._now))
        )
        session.pause()
        screen = session.app.screen
        screen._active_tab = "workflow"
        session.run(screen._apply_tab_visibility)
        session.pause()

        table = screen.query_one(HierarchyPagingTable)
        row_ids = [row.key.value for row in table.ordered_rows]
        assert row_ids[table.cursor_row] == queued_step

        done_row = row_ids.index(done_step)
        table.move_cursor(row=done_row)
        session.pause()

        session.run(
            lambda: screen._render_hierarchy(screen._last_rows, screen._last_multi_pass, initial=True)
        )
        session.pause()

        assert table.cursor_row == done_row
    finally:
        session.close()


def test_backlog_footer_status_and_shortcut_lines_are_painted():
    store = FakeStore()
    store.create_item("todo item", "a description")
    session = launch(make_test_container(store=store))
    try:
        session.press("]")
        footer = session.app.screen.query_one(DashboardFooter)
        status_bar, shortcut_bar = footer.children
        status_text = _rendered_row_text(session, status_bar)
        shortcut_text = _rendered_row_text(session, shortcut_bar)
        assert "pool" in status_text
        assert "filter" in shortcut_text
    finally:
        session.close()


_PANE_WIDGET_BY_TAB = {
    "workflow": HierarchyPagingTable,
    "log": LogPane,
    "artifacts": ArtifactsTable,
    "detail": DetailTable,
    "description": DescriptionPane,
    "cost": CostPane,
}

_EMPTY_MESSAGE_IDS = ("#hub-log-empty", "#hub-artifacts-empty", "#hub-description-empty", "#hub-cost-empty")


@pytest.mark.parametrize("tab", ["workflow", "log", "artifacts", "detail", "description", "cost"])
def test_pre_refresh_frame_shows_only_the_active_tabs_pane_and_no_empty_message(tab):
    store = FakeStore()
    if tab in ("log", "detail"):
        item = store.create_item("Item", "a description")
        node_id = store.create_step(step="build", role="agent", parent=item)
    else:
        node_id = store.create_item("Item", "a description")
    session = launch(make_test_container(store=store))
    try:
        screen = NodeHubScreen(session.app.container, node_id, session.app._now, initial_tab=tab)
        session.run(lambda: session.app.push_screen(screen))

        for candidate_tab, widget_cls in _PANE_WIDGET_BY_TAB.items():
            widget = screen.query_one(widget_cls)
            assert widget.display == (candidate_tab == tab)

        for empty_message_id in _EMPTY_MESSAGE_IDS:
            assert screen.query_one(empty_message_id).display is False
    finally:
        session.close()


@pytest.mark.parametrize("tab", ["workflow", "log", "artifacts", "detail", "description", "cost"])
def test_hub_tab_strip_composes_with_only_the_active_tab_marked(tab):
    tabs = list(_PANE_WIDGET_BY_TAB)
    strip = HubTabStrip(tabs, tab)

    labels = {widget.id: widget for widget in strip.compose()}

    for candidate_tab in tabs:
        label = labels["hub-tab-%s" % candidate_tab]
        assert label.has_class("tab-active") == (candidate_tab == tab)
        assert label.has_class("tab-dim") == (candidate_tab != tab)
