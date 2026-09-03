import unittest

from lightcycle.adapters.tui.app import BacklogTable, PriorityTable
from lightcycle.adapters.tui.hub import ArtifactListTable, NodeHubScreen
from lightcycle.adapters.tui.row_grid import STEP_PHRASE_BUDGET
from tests.support.fake_fs import FakeFs
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
            store.create_item("word " * 30 + str(i), "a description")

        session = self._launch(store)
        session.press("tab")

        screen = session.app.screen
        table = session.app.query_one(BacklogTable)
        self.assertEqual(screen.max_scroll_y, 0)
        self.assertFalse(screen.show_vertical_scrollbar)
        self.assertGreater(table.max_scroll_y, 0)
        self.assertTrue(table.show_vertical_scrollbar)

    def test_screen_does_not_scroll_when_backlog_fits(self):
        store = FakeStore()
        store.create_item("single row", "a description")

        session = self._launch(store)
        session.press("tab")

        screen = session.app.screen
        table = session.app.query_one(BacklogTable)
        self.assertEqual(screen.max_scroll_y, 0)
        self.assertFalse(screen.show_vertical_scrollbar)
        self.assertEqual(table.max_scroll_y, 0)
        self.assertFalse(table.show_vertical_scrollbar)

    def _open_list_artifact(self, store, item_id, size=(80, 24)):
        session = self._launch(store, size=size)
        screen = NodeHubScreen(session.app.container, item_id, session.app._now, initial_tab="artifacts")
        session.run(lambda: session.app.push_screen(screen))
        session.pause()
        session.pause()
        session.press("enter")
        session.pause()
        return session

    def test_screen_does_not_scroll_when_artifact_list_overflows(self):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        store.add_artifact(item, "watched", "\n".join("item %02d" % i for i in range(40)), kind="list")

        session = self._open_list_artifact(store, item)

        screen = session.app.screen
        table = screen.query_one(ArtifactListTable)
        self.assertEqual(screen.max_scroll_y, 0)
        self.assertFalse(screen.show_vertical_scrollbar)
        self.assertGreater(table.max_scroll_y, 0)
        self.assertTrue(table.show_vertical_scrollbar)

    def test_screen_does_not_scroll_when_artifact_list_fits(self):
        store = FakeStore()
        item = store.create_item("Item", "a description")
        store.add_artifact(item, "watched", "single row", kind="list")

        session = self._open_list_artifact(store, item)

        screen = session.app.screen
        table = screen.query_one(ArtifactListTable)
        self.assertEqual(screen.max_scroll_y, 0)
        self.assertFalse(screen.show_vertical_scrollbar)
        self.assertEqual(table.max_scroll_y, 0)
        self.assertFalse(table.show_vertical_scrollbar)


def _rendered_cell_text(table, row_id, column_key):
    strip = table.render_line(table.get_row_index(row_id))
    pad = table.cell_padding
    offset = 0
    for column in table.ordered_columns:
        start = offset + pad
        end = start + column.width
        if column.key.value == column_key:
            return "".join(segment.text for segment in strip.crop(start, end))
        offset = end + pad
    raise AssertionError("column %r not found" % column_key)


class TestPriorityListStepColumnTruncation(unittest.TestCase):
    def test_a_phrase_longer_than_the_budget_is_shown_with_a_trailing_ellipsis(self):
        store = FakeStore()
        step = store.create_step("build it", step="build", role="agent")
        fs = FakeFs(metas={
            "coder": {
                "model": "sonnet", "step": "build",
                "display": "A phrase far longer than the budget allows",
            },
        })

        session = launch(make_test_container(store=store, fs=fs), size=(160, 24))
        self.addCleanup(session.close)

        table = session.app.query_one(PriorityTable)
        text = _rendered_cell_text(table, store.get_step(step).item, "step").strip()
        self.assertTrue(text.endswith("…"))
        self.assertEqual(len(text), STEP_PHRASE_BUDGET)

    def test_a_phrase_within_the_budget_is_shown_in_full(self):
        store = FakeStore()
        step = store.create_step("build it", step="build", role="agent")
        fs = FakeFs(metas={
            "coder": {"model": "sonnet", "step": "build", "display": "Coding"},
        })

        session = launch(make_test_container(store=store, fs=fs), size=(160, 24))
        self.addCleanup(session.close)

        table = session.app.query_one(PriorityTable)
        text = _rendered_cell_text(table, store.get_step(step).item, "step").strip()
        self.assertEqual(text, "Coding")
