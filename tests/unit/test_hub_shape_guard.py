import unittest
from unittest.mock import patch

from lightcycle.adapters.tui.hub import ArtifactsTable, DetailTable, HierarchyPagingTable, NodeHubScreen
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container


def _push_hub(session, node_id, initial_tab):
    session.run(
        lambda: session.app.push_screen(
            NodeHubScreen(session.app.container, node_id, session.app._now, initial_tab=initial_tab)
        )
    )
    session.pause()
    return session.app.screen


class TestHierarchyShapeGuard(unittest.TestCase):
    _ITEM = "LC-1"
    _STEP = "LC-1.1"
    _STACKED_WIDTH = 44
    _FLOOR_WIDTH = 43

    def _store(self):
        store = FakeStore()
        item = store.create_item("Item", "a description", id=self._ITEM)
        store.create_step("s", step="build", role="agent", parent=item, id=self._STEP)
        return store

    def _launch(self, width):
        session = launch(make_test_container(store=self._store()), size=(width, 24))
        self.addCleanup(session.close)
        return session

    def test_hidden_then_polled_with_unchanged_rows_rebuilds_not_updates(self):
        session = self._launch(self._STACKED_WIDTH)
        screen = _push_hub(session, self._STEP, "workflow")
        table = screen.query_one(HierarchyPagingTable)
        self.assertTrue(screen._hierarchy_stacked)

        session.run(screen.action_next_tab)
        session.pause()
        self.assertEqual(table.size.width, 0)

        with patch.object(NodeHubScreen, "_update_hierarchy_cells") as update:
            session.run(screen.poll_refresh)
            session.pause()
            update.assert_not_called()

        session.run(screen.action_prev_tab)
        session.pause()
        session.run(screen.poll_refresh)
        session.pause()
        self.assertGreater(table.row_count, 0)
        self.assertTrue(screen._hierarchy_stacked)

    def test_floor_entered_then_polled_again_stays_at_floor_without_raising(self):
        session = self._launch(self._FLOOR_WIDTH)
        screen = _push_hub(session, self._STEP, "workflow")
        table = screen.query_one(HierarchyPagingTable)

        self.assertTrue(screen._hierarchy_floor)
        self.assertTrue(screen._hierarchy_needs_rebuild)
        self.assertEqual(table.row_count, 0)

        session.run(screen.poll_refresh)
        session.pause()

        self.assertTrue(screen._hierarchy_floor)
        self.assertTrue(screen._hierarchy_needs_rebuild)
        self.assertEqual(table.row_count, 0)

    def test_stacked_mismatch_forces_rebuild_not_cheap_update(self):
        session = self._launch(200)
        screen = _push_hub(session, self._STEP, "workflow")
        self.assertFalse(screen._hierarchy_stacked)

        screen._hierarchy_stacked = True
        with patch.object(NodeHubScreen, "_update_hierarchy_cells") as update:
            session.run(screen.poll_refresh)
            session.pause()
            update.assert_not_called()
        self.assertFalse(screen._hierarchy_stacked)


class TestArtifactsShapeGuard(unittest.TestCase):
    _ITEM = "LC-1"
    _STACKED_WIDTH = 34
    _FLOOR_WIDTH = 33

    def _store(self):
        store = FakeStore()
        item = store.create_item("Item", "a description", id=self._ITEM)
        store.add_artifact(item, "spec", "x")
        return store

    def _launch(self, width):
        session = launch(make_test_container(store=self._store()), size=(width, 24))
        self.addCleanup(session.close)
        return session

    def test_hidden_then_polled_with_unchanged_rows_rebuilds_not_updates(self):
        session = self._launch(self._STACKED_WIDTH)
        screen = _push_hub(session, self._ITEM, "artifacts")
        table = screen.query_one(ArtifactsTable)
        self.assertTrue(screen._artifacts_stacked)

        session.run(screen.action_next_tab)
        session.pause()
        self.assertEqual(table.size.width, 0)

        with patch.object(NodeHubScreen, "_update_artifact_cells") as update:
            session.run(screen.poll_refresh)
            session.pause()
            update.assert_not_called()

        session.run(screen.action_prev_tab)
        session.pause()
        session.run(screen.poll_refresh)
        session.pause()
        self.assertGreater(table.row_count, 0)
        self.assertTrue(screen._artifacts_stacked)

    def test_floor_entered_then_polled_again_stays_at_floor_without_raising(self):
        session = self._launch(self._FLOOR_WIDTH)
        screen = _push_hub(session, self._ITEM, "artifacts")
        table = screen.query_one(ArtifactsTable)

        self.assertTrue(screen._artifacts_floor)
        self.assertTrue(screen._artifacts_needs_rebuild)
        self.assertEqual(table.row_count, 0)

        session.run(screen.poll_refresh)
        session.pause()

        self.assertTrue(screen._artifacts_floor)
        self.assertTrue(screen._artifacts_needs_rebuild)
        self.assertEqual(table.row_count, 0)

    def test_stacked_mismatch_forces_rebuild_not_cheap_update(self):
        session = self._launch(200)
        screen = _push_hub(session, self._ITEM, "artifacts")
        self.assertFalse(screen._artifacts_stacked)

        screen._artifacts_stacked = True
        with patch.object(NodeHubScreen, "_update_artifact_cells") as update:
            session.run(screen.poll_refresh)
            session.pause()
            update.assert_not_called()
        self.assertFalse(screen._artifacts_stacked)


class TestDetailShapeGuard(unittest.TestCase):
    _ITEM = "LC-1"
    _STEP = "LC-1.1"
    _STACKED_WIDTH = 34
    _FLOOR_WIDTH = 33

    def _store(self):
        store = FakeStore()
        item = store.create_item("Item", "a description", id=self._ITEM)
        store.create_step("s", step="build", role="agent", parent=item, id=self._STEP)
        return store

    def _launch(self, width):
        session = launch(make_test_container(store=self._store()), size=(width, 24))
        self.addCleanup(session.close)
        return session

    def test_hidden_then_polled_with_unchanged_rows_rebuilds_not_updates(self):
        session = self._launch(self._STACKED_WIDTH)
        screen = _push_hub(session, self._STEP, "detail")
        table = screen.query_one(DetailTable)
        self.assertTrue(screen._detail_stacked)

        session.run(screen.action_next_tab)
        session.pause()
        self.assertEqual(table.size.width, 0)

        with patch.object(NodeHubScreen, "_update_detail_cells") as update:
            session.run(screen.poll_refresh)
            session.pause()
            update.assert_not_called()

        session.run(screen.action_prev_tab)
        session.pause()
        session.run(screen.poll_refresh)
        session.pause()
        self.assertGreater(table.row_count, 0)
        self.assertTrue(screen._detail_stacked)

    def test_floor_entered_then_polled_again_stays_at_floor_without_raising(self):
        session = self._launch(self._FLOOR_WIDTH)
        screen = _push_hub(session, self._STEP, "detail")
        table = screen.query_one(DetailTable)

        self.assertTrue(screen._detail_floor)
        self.assertTrue(screen._detail_needs_rebuild)
        self.assertEqual(table.row_count, 0)

        session.run(screen.poll_refresh)
        session.pause()

        self.assertTrue(screen._detail_floor)
        self.assertTrue(screen._detail_needs_rebuild)
        self.assertEqual(table.row_count, 0)

    def test_stacked_mismatch_forces_rebuild_not_cheap_update(self):
        session = self._launch(200)
        screen = _push_hub(session, self._STEP, "detail")
        self.assertFalse(screen._detail_stacked)

        screen._detail_stacked = True
        with patch.object(NodeHubScreen, "_update_detail_cells") as update:
            session.run(screen.poll_refresh)
            session.pause()
            update.assert_not_called()
        self.assertFalse(screen._detail_stacked)


if __name__ == "__main__":
    unittest.main()
