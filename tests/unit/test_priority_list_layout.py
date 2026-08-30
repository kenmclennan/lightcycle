import unittest

from lightcycle.adapters.tui.app import BacklogTable, PriorityTable
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container


class TestPriorityListScreenScrolling(unittest.TestCase):
    def _launch(self, store, size=(100, 30)):
        session = launch(make_test_container(store=store), size=size)
        self.addCleanup(session.close)
        return session

    def test_screen_does_not_scroll_when_priority_list_overflows(self):
        store = FakeStore()
        for i in range(14):
            store.create_step("word " * 30 + str(i), step="triage", role="human")

        session = self._launch(store)

        screen = session.app.screen
        table = session.app.query_one(PriorityTable)
        self.assertEqual(screen.max_scroll_y, 0)
        self.assertFalse(screen.show_vertical_scrollbar)
        self.assertGreater(table.max_scroll_y, 0)
        self.assertTrue(table.show_vertical_scrollbar)

    def test_screen_does_not_scroll_when_priority_list_fits(self):
        store = FakeStore()
        store.create_step("single row", step="triage", role="human")

        session = self._launch(store)

        screen = session.app.screen
        table = session.app.query_one(PriorityTable)
        self.assertEqual(screen.max_scroll_y, 0)
        self.assertFalse(screen.show_vertical_scrollbar)
        self.assertEqual(table.max_scroll_y, 0)
        self.assertFalse(table.show_vertical_scrollbar)

    def test_screen_does_not_scroll_when_backlog_overflows(self):
        store = FakeStore()
        for i in range(30):
            store.create_item("word " * 30 + str(i))

        session = self._launch(store)
        session.press("tab")

        screen = session.app.screen
        table = session.app.query_one(BacklogTable)
        self.assertEqual(screen.max_scroll_y, 0)
        self.assertFalse(screen.show_vertical_scrollbar)
        self.assertGreater(table.max_scroll_y, 0)
        self.assertTrue(table.show_vertical_scrollbar)
