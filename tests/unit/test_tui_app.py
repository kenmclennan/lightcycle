import datetime
import unittest
from unittest.mock import patch

from textual.widgets import DataTable

from lightcycle.adapters.tui.app import (
    COLOR_AMBER,
    COLOR_CYAN,
    COLOR_DIM,
    COLOR_RED,
    POLL_INTERVAL_SECONDS,
    LightcycleApp,
    StatusBar,
    _title_width,
)
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeBreakerPort, FakeLock, launch, make_test_container


class TestPollInterval(unittest.TestCase):
    def test_is_ten_seconds(self):
        self.assertEqual(POLL_INTERVAL_SECONDS, 10)


class TuiTestCase(unittest.TestCase):
    def _launch(self, now=None, **kwargs):
        session = launch(make_test_container(**kwargs), now=now)
        self.addCleanup(session.close)
        return session


class TestDashboardScaffold(TuiTestCase):

    def test_status_bar_populates_same_frame(self):
        store = FakeStore()
        queued = store.create_step("queued", step="build", role="coder")
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step("blocked", step="build", role="coder", deps=[blocker])
        running = store.create_step("running", step="build", role="coder")
        store.assign(running, "worker-1")

        session = self._launch(store=store)

        table = session.app.query_one(DataTable)
        self.assertIn(queued, table.rows)
        self.assertIn(blocker, table.rows)
        self.assertIn(blocked, table.rows)

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


def _non_gap_row_keys(table):
    return [k.value for k in table.rows if not str(k.value).startswith("__gap")]


class TestNeedsAttentionGroup(TuiTestCase):
    def test_grouped_above_active_and_queued_with_own_icon_and_colour(self):
        store = FakeStore()
        inbox = store.create_step("inbox item", step="code-await-merge", role="human")
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step("blocked item", step="build", role="coder", deps=[blocker])
        active = store.create_step("active item", step="build", role="coder")
        store.assign(active, "worker-1")
        store.update_state(active, State.IN_PROGRESS)
        queued = store.create_step("queued item", step="build", role="coder")

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        order = _non_gap_row_keys(table)
        attention_positions = [order.index(inbox), order.index(blocked)]
        other_positions = [order.index(active), order.index(queued), order.index(blocker)]
        self.assertTrue(max(attention_positions) < min(other_positions))

        for tid in (inbox, blocked):
            icon = table.get_cell(tid, "icon")
            self.assertEqual(icon.plain, "●")
            self.assertEqual(icon.style, COLOR_RED)
            step_cell = table.get_cell(tid, "step")
            self.assertEqual(step_cell.style, COLOR_AMBER)

    def test_needs_attention_step_name_shown(self):
        store = FakeStore()
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step(
            "blocked item", step="code-await-merge", role="coder", deps=[blocker]
        )

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        step_cell = table.get_cell(blocked, "step")
        self.assertEqual(step_cell.plain, "code-await-merge")

    def test_long_title_wraps_instead_of_truncating(self):
        store = FakeStore()
        long_title = "x" * 400
        inbox = store.create_step(long_title, step="build", role="human")

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        self.assertGreater(table.rows[inbox].height, 1)

    def test_title_column_width_recomputed_on_resize(self):
        session = self._launch(store=FakeStore())
        table = session.app.query_one(DataTable)

        session.resize(120, 40)

        self.assertEqual(table.columns["title"].width, _title_width(120))


class TestActiveGroup(TuiTestCase):
    def test_active_row_shows_icon_colour_step_and_elapsed_time(self):
        claimed_at = datetime.datetime(2026, 1, 1, 12, 0, 0)
        store = FakeStore(now=lambda: claimed_at.isoformat())
        tid = store.create_step("active item", step="build", role="coder")
        store.assign(tid, "worker-1")
        store.update_state(tid, State.IN_PROGRESS)

        rendered_at = claimed_at + datetime.timedelta(minutes=14)
        session = self._launch(store=store, now=lambda: rendered_at)
        table = session.app.query_one(DataTable)

        icon = table.get_cell(tid, "icon")
        self.assertEqual(icon.plain, "▸")
        self.assertEqual(icon.style, COLOR_CYAN)
        step_cell = table.get_cell(tid, "step")
        self.assertEqual(step_cell.plain, "build")
        time_cell = table.get_cell(tid, "time")
        self.assertEqual(time_cell.plain, "14m")

    def test_grouped_below_needs_attention_and_above_queued(self):
        store = FakeStore()
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step("blocked item", step="build", role="coder", deps=[blocker])
        active = store.create_step("active item", step="build", role="coder")
        store.assign(active, "worker-1")
        store.update_state(active, State.IN_PROGRESS)
        queued = store.create_step("queued item", step="build", role="coder")

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        order = _non_gap_row_keys(table)
        self.assertLess(order.index(blocked), order.index(active))
        self.assertLess(order.index(active), order.index(queued))

    def test_elapsed_time_updates_across_two_polls_without_full_rebuild(self):
        claimed_at = datetime.datetime(2026, 1, 1, 12, 0, 0)
        store = FakeStore(now=lambda: claimed_at.isoformat())
        tid = store.create_step("active item", step="build", role="coder")
        store.assign(tid, "worker-1")
        store.update_state(tid, State.IN_PROGRESS)

        clock = {"now": claimed_at + datetime.timedelta(minutes=1)}
        session = self._launch(store=store, now=lambda: clock["now"])
        table = session.app.query_one(DataTable)
        first_order = list(table.rows.keys())
        first_row_count = table.row_count

        clock["now"] = claimed_at + datetime.timedelta(minutes=2)
        session.poll_tick()

        self.assertEqual(table.row_count, first_row_count)
        self.assertEqual(list(table.rows.keys()), first_order)
        self.assertEqual(table.get_cell(tid, "time").plain, "2m")


class TestQueuedGroup(TuiTestCase):
    def test_queued_row_at_bottom_with_icon_colour_and_next_step(self):
        store = FakeStore()
        active = store.create_step("active item", step="build", role="coder")
        store.assign(active, "worker-1")
        store.update_state(active, State.IN_PROGRESS)
        queued = store.create_step("queued item", step="build", role="coder")

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        order = _non_gap_row_keys(table)
        self.assertLess(order.index(active), order.index(queued))

        icon = table.get_cell(queued, "icon")
        self.assertEqual(icon.plain, "○")
        self.assertEqual(icon.style, COLOR_DIM)
        step_cell = table.get_cell(queued, "step")
        self.assertEqual(step_cell.plain, "build")

    def test_queued_item_moves_to_active_group_on_claim(self):
        store = FakeStore()
        tid = store.create_step("queued item", step="build", role="coder")

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)
        self.assertEqual(table.get_cell(tid, "icon").style, COLOR_DIM)

        store.assign(tid, "worker-1")
        store.update_state(tid, State.IN_PROGRESS)
        session.poll_tick()

        self.assertEqual(table.get_cell(tid, "icon").style, COLOR_CYAN)

    def test_blocked_step_does_not_appear_in_queued_group(self):
        store = FakeStore()
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step("blocked item", step="build", role="coder", deps=[blocker])
        queued = store.create_step("queued item", step="build", role="coder")

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        self.assertEqual(table.get_cell(blocked, "icon").style, COLOR_RED)
        order = _non_gap_row_keys(table)
        self.assertLess(order.index(blocked), order.index(queued))


class TestProjectColumn(TuiTestCase):
    def test_shows_repo_artifact_value_styled_cyan(self):
        store = FakeStore()
        item = store.create_item("item")
        store.add_artifact(item, "repo", "lightcycle")
        tid = store.create_step("step", step="build", role="coder", parent=item)

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        project_cell = table.get_cell(tid, "project")
        self.assertEqual(project_cell.plain, "lightcycle")
        self.assertEqual(project_cell.style, COLOR_CYAN)

    def test_blank_when_no_repo_artifact(self):
        store = FakeStore()
        item = store.create_item("item")
        tid = store.create_step("step", step="build", role="coder", parent=item)

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        project_cell = table.get_cell(tid, "project")
        self.assertEqual(project_cell, "")

    def test_matches_project_of_derivation(self):
        from lightcycle.application.work.project_of import project_of
        from lightcycle.domain.work import Item

        store = FakeStore()
        item = store.create_item("item")
        store.add_artifact(item, "repo", "lightcycle")
        tid = store.create_step("step", step="build", role="coder", parent=item)

        session = self._launch(store=store)
        table = session.app.query_one(DataTable)

        expected = project_of(store, Item(item)) or ""
        self.assertEqual(table.get_cell(tid, "project").plain, expected)


class TestNeedsAttentionBell(TuiTestCase):
    def test_bell_fires_once_on_transition_into_needs_attention(self):
        store = FakeStore()
        session = self._launch(store=store)

        with patch.object(type(session.app), "bell") as mock_bell:
            blocker = store.create_step("blocker", step="build", role="coder")
            store.create_step("blocked item", step="build", role="coder", deps=[blocker])
            session.poll_tick()

            self.assertEqual(mock_bell.call_count, 1)

    def test_bell_does_not_fire_again_while_item_stays_in_needs_attention(self):
        store = FakeStore()
        session = self._launch(store=store)

        blocker = store.create_step("blocker", step="build", role="coder")
        store.create_step("blocked item", step="build", role="coder", deps=[blocker])
        session.poll_tick()

        with patch.object(type(session.app), "bell") as mock_bell:
            session.poll_tick()
            self.assertEqual(mock_bell.call_count, 0)

    def test_bell_does_not_fire_for_active_or_queued_transition(self):
        store = FakeStore()
        session = self._launch(store=store)

        with patch.object(type(session.app), "bell") as mock_bell:
            store.create_step("new queued item", step="build", role="coder")
            session.poll_tick()

            self.assertEqual(mock_bell.call_count, 0)

    def test_bell_does_not_fire_on_initial_render(self):
        store = FakeStore()
        blocker = store.create_step("blocker", step="build", role="coder")
        store.create_step("blocked item", step="build", role="coder", deps=[blocker])

        with patch.object(LightcycleApp, "bell") as mock_bell:
            self._launch(store=store)
            self.assertEqual(mock_bell.call_count, 0)
