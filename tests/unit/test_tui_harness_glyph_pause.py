import time
import unittest

from textual.widgets import DataTable

from lightcycle.adapters.tui.design_system import ACTIVE_GLYPH_TICKS_PER_SECOND
from lightcycle.adapters.tui.hub import HierarchyPagingTable, NodeHubScreen
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

_TICK_INTERVAL = 1 / ACTIVE_GLYPH_TICKS_PER_SECOND


class TestGlyphTimerStaysPausedAcrossAssertions(unittest.TestCase):
    def test_app_level_timer_does_not_tick_between_pause_and_the_next_stimulus(self):
        store = FakeStore()
        tid = store.create_step("active item", step="build", role="agent")
        store.assign(tid, "worker-1")
        store.update_state(tid, State.IN_PROGRESS)

        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        table = session.app.query_one(DataTable)
        baseline = table.get_cell(tid, "icon").plain

        time.sleep(_TICK_INTERVAL * 4)
        session.run(lambda: None)

        self.assertEqual(table.get_cell(tid, "icon").plain, baseline)

    def test_screen_level_timer_does_not_tick_between_pause_and_the_next_stimulus(self):
        store = FakeStore()
        item = store.create_item("Item")
        tid = store.create_step("active item", step="build", role="agent", parent=item)
        store.assign(tid, "worker-1")
        store.update_state(tid, State.IN_PROGRESS)

        session = launch(make_test_container(store=store), size=(120, 24))
        self.addCleanup(session.close)
        session.run(
            lambda: session.app.push_screen(NodeHubScreen(session.app.container, item, session.app._now))
        )
        session.pause()
        screen = session.app.screen
        screen._active_tab = "hierarchy"
        session.run(screen._apply_tab_visibility)
        session.pause()

        table = screen.query_one(HierarchyPagingTable)
        baseline = table.get_cell(tid, "icon").plain

        time.sleep(_TICK_INTERVAL * 4)
        session.run(lambda: None)

        self.assertEqual(table.get_cell(tid, "icon").plain, baseline)
