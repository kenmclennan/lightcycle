import datetime
import unittest

from lightcycle.adapters.tui.app import BacklogTable, PriorityTable
from lightcycle.adapters.tui.hub import ArtifactsTable, HierarchyPagingTable, NodeHubScreen
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

_NOW = datetime.datetime(2026, 1, 1, 14, 16, 0)
_SIZE = (100, 30)
_SHORT_COUNT = 1
_LONG_COUNT = 60


def _at(minutes_ago):
    return (_NOW - datetime.timedelta(minutes=minutes_ago)).isoformat()


def _frame_text(session):
    strips = session.run(lambda: session.app.screen._compositor.render_strips())
    return "\n".join("".join(segment.text for segment in strip) for strip in strips)


def _priority_active_store(count):
    store = FakeStore(now=lambda: _at(14))
    for i in range(count):
        step = store.create_step(
            "row %d" % i, step="write-code", role="write-code", id="LC-%d.1" % (1000 + i),
        )
        store.assign(step, "worker-%d" % i)
        store.update_state(step, State.IN_PROGRESS)
    return store


def _backlog_item_store(count, title):
    store = FakeStore()
    for i in range(count):
        store.create_item(title, id="LC-%d" % (2000 + i))
    return store


def _hierarchy_step_store(count, role):
    store = FakeStore()
    item = store.create_item("Item", id="LC-3000")
    for i in range(count):
        store.create_step("step %d" % i, step="build", role=role, parent=item, id="LC-3000.%d" % (i + 1))
    return store, item


def _artifacts_item_store(count, value):
    store = FakeStore()
    item = store.create_item("Item", id="LC-4000")
    for i in range(count):
        store.add_artifact(item, "type%d" % i, value)
    return store, item


def _open_hub(session, node_id, tab):
    screen = NodeHubScreen(session.app.container, node_id, session.app._now, initial_tab=tab)
    session.run(lambda: session.app.push_screen(screen))
    session.pause()
    session.pause()
    return session


class TestPriorityTableScrollbarDoesNotClipTime(unittest.TestCase):
    def _launch(self, count):
        store = _priority_active_store(count)
        session = launch(make_test_container(store=store), now=lambda: _NOW, size=_SIZE)
        self.addCleanup(session.close)
        return session

    def test_short_list_shows_full_time_value_with_no_scrollbars(self):
        session = self._launch(_SHORT_COUNT)
        table = session.app.query_one(PriorityTable)
        self.assertFalse(table.show_vertical_scrollbar)
        self.assertFalse(table.show_horizontal_scrollbar)
        self.assertIn("14m", _frame_text(session))

    def test_long_list_still_shows_full_time_value_and_no_horizontal_scrollbar(self):
        session = self._launch(_LONG_COUNT)
        table = session.app.query_one(PriorityTable)
        self.assertTrue(table.show_vertical_scrollbar)
        self.assertFalse(table.show_horizontal_scrollbar)
        self.assertIn("14m", _frame_text(session))


class TestBacklogTableScrollbarDoesNotClipTitle(unittest.TestCase):
    _TITLE = "Widget"

    def _launch(self, count):
        store = _backlog_item_store(count, self._TITLE)
        session = launch(make_test_container(store=store), size=_SIZE)
        session.press("tab")
        self.addCleanup(session.close)
        return session

    def test_short_list_shows_full_title_value_with_no_scrollbars(self):
        session = self._launch(_SHORT_COUNT)
        table = session.app.query_one(BacklogTable)
        self.assertFalse(table.show_vertical_scrollbar)
        self.assertFalse(table.show_horizontal_scrollbar)
        self.assertIn(self._TITLE, _frame_text(session))

    def test_long_list_still_shows_full_title_value_and_no_horizontal_scrollbar(self):
        session = self._launch(_LONG_COUNT)
        table = session.app.query_one(BacklogTable)
        self.assertTrue(table.show_vertical_scrollbar)
        self.assertFalse(table.show_horizontal_scrollbar)
        self.assertIn(self._TITLE, _frame_text(session))


class TestHierarchyTableScrollbarDoesNotClipRole(unittest.TestCase):
    _ROLE = "coder"

    def _launch(self, count):
        store, item = _hierarchy_step_store(count, self._ROLE)
        session = launch(make_test_container(store=store), size=_SIZE)
        self.addCleanup(session.close)
        return _open_hub(session, item, "hierarchy")

    def test_short_list_shows_full_role_value_with_no_scrollbars(self):
        session = self._launch(_SHORT_COUNT)
        table = session.app.screen.query_one(HierarchyPagingTable)
        self.assertFalse(table.show_vertical_scrollbar)
        self.assertFalse(table.show_horizontal_scrollbar)
        self.assertIn(self._ROLE, _frame_text(session))

    def test_long_list_still_shows_full_role_value_and_no_horizontal_scrollbar(self):
        session = self._launch(_LONG_COUNT)
        table = session.app.screen.query_one(HierarchyPagingTable)
        self.assertTrue(table.show_vertical_scrollbar)
        self.assertFalse(table.show_horizontal_scrollbar)
        self.assertIn(self._ROLE, _frame_text(session))


class TestArtifactsTableScrollbarDoesNotClipValue(unittest.TestCase):
    _VALUE = "shortval"

    def _launch(self, count):
        store, item = _artifacts_item_store(count, self._VALUE)
        session = launch(make_test_container(store=store), size=_SIZE)
        self.addCleanup(session.close)
        return _open_hub(session, item, "artifacts")

    def test_short_list_shows_full_value_with_no_scrollbars(self):
        session = self._launch(_SHORT_COUNT)
        table = session.app.screen.query_one(ArtifactsTable)
        self.assertFalse(table.show_vertical_scrollbar)
        self.assertFalse(table.show_horizontal_scrollbar)
        self.assertIn(self._VALUE, _frame_text(session))

    def test_long_list_still_shows_full_value_and_no_horizontal_scrollbar(self):
        session = self._launch(_LONG_COUNT)
        table = session.app.screen.query_one(ArtifactsTable)
        self.assertTrue(table.show_vertical_scrollbar)
        self.assertFalse(table.show_horizontal_scrollbar)
        self.assertIn(self._VALUE, _frame_text(session))
