import unittest

from textual.widgets import DataTable

from lightcycle.adapters.tui.app import POLL_INTERVAL_SECONDS, StatusBar
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeBreakerPort, FakeLock, launch, make_test_container


class TestPollInterval(unittest.TestCase):
    def test_is_ten_seconds(self):
        self.assertEqual(POLL_INTERVAL_SECONDS, 10)


class TestDashboardScaffold(unittest.TestCase):
    def _launch(self, **kwargs):
        session = launch(make_test_container(**kwargs))
        self.addCleanup(session.close)
        return session

    def test_priority_list_excludes_in_progress_and_status_bar_populates_same_frame(self):
        store = FakeStore()
        queued = store.create_step("queued", step="build", role="coder")
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step("blocked", step="build", role="coder", deps=[blocker])
        running = store.create_step("running", step="build", role="coder")
        store.assign(running, "worker-1")

        session = self._launch(store=store)

        table = session.app.query_one(DataTable)
        self.assertEqual(table.row_count, 3)
        self.assertIn(queued, table.rows)
        self.assertIn(blocker, table.rows)
        self.assertIn(blocked, table.rows)
        self.assertNotIn(running, table.rows)

        status_bar = session.app.query_one(StatusBar)
        self.assertNotEqual(status_bar.status_text, "")

    def test_priority_list_is_not_truncated_to_ten(self):
        store = FakeStore()
        ids = [store.create_step("t%d" % i, step="build", role="coder") for i in range(12)]

        session = self._launch(store=store)

        table = session.app.query_one(DataTable)
        self.assertEqual(table.row_count, 12)
        for tid in ids:
            self.assertIn(tid, table.rows)

    def test_status_bar_reflects_running_pool_and_open_breaker(self):
        session = self._launch(
            lock=FakeLock(running=True), breaker=FakeBreakerPort(is_open=True, reset_at=500.0)
        )

        status_bar = session.app.query_one(StatusBar)
        self.assertIn("pool: running", status_bar.status_text)
        self.assertIn("breaker: open", status_bar.status_text)
        self.assertIn("500.0", status_bar.status_text)
