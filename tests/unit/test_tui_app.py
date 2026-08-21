import datetime
import time
import unittest
from unittest.mock import patch

from textual.widgets import DataTable, Static

from lightcycle import __version__
from lightcycle.adapters.tui.app import (
    POLL_INTERVAL_SECONDS,
    BacklogTable,
    BacklogView,
    LightcycleApp,
    PickerOption,
    PriorityTable,
    ProjectFilterPicker,
    ShortcutBar,
    StatusBar,
)
from lightcycle.adapters.tui.design_system import (
    BACKLOG_EMPTY_SHORTCUTS,
    BACKLOG_FILTERED_EMPTY_SHORTCUTS,
    BACKLOG_SHORTCUTS,
    COLOURS,
    CURSOR_GLYPH,
    FOOTER_GLYPHS,
    GLOBAL_SHORTCUTS,
    STATE_GLYPHS,
)
from lightcycle.application.setup import UpgradeResponse
from lightcycle.domain.work import State
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import FakeBreakerPort, FakeLock, launch, make_test_container


def _cell_text(value):
    return value.plain if hasattr(value, "plain") else value


def _cell(session, row_id, column):
    table = session.app.query_one(DataTable)
    return _cell_text(table.get_cell(row_id, column))


def _row_order(session):
    table = session.app.query_one(DataTable)
    return [row.key.value for row in table.ordered_rows]


def _rendered_segment(session, widget_id):
    widget = session.app.query_one(widget_id, Static)
    strip = widget.render_line(0)
    text = "".join(segment.text for segment in strip)
    style = None
    for segment in strip:
        if segment.text.strip():
            style = segment.style
            break
    return widget, text, style


def _colour_of(style):
    return style.color.get_truecolor().hex.lower()


def _painted_row(session, y):
    return session.app.screen._compositor.render_strips()[y]


def _painted_spans(strip):
    x = 0
    spans = []
    for segment in strip:
        text = segment.text
        if text.strip():
            style = segment.style
            colour = _colour_of(style) if style is not None and style.color is not None else None
            spans.append((x, x + len(text) - 1, colour))
        x += len(text)
    return spans


class TestPollInterval(unittest.TestCase):
    def test_is_ten_seconds(self):
        self.assertEqual(POLL_INTERVAL_SECONDS, 10)


class TestDashboardScaffold(unittest.TestCase):
    def _launch(self, **kwargs):
        session = launch(make_test_container(**kwargs))
        self.addCleanup(session.close)
        return session

    def test_status_bar_populates_same_frame_as_priority_list(self):
        store = FakeStore()
        store.create_step("queued", step="build", role="coder")

        session = self._launch(store=store)

        table = session.app.query_one(DataTable)
        self.assertGreater(table.row_count, 0)

        session.app.query_one(StatusBar)
        _, version_text, _ = _rendered_segment(session, "#status-version")
        self.assertNotEqual(version_text.strip(), "")

    def test_priority_list_is_not_truncated_to_ten(self):
        store = FakeStore()
        ids = [store.create_step("t%d" % i, step="build", role="coder") for i in range(12)]

        session = self._launch(store=store)

        table = session.app.query_one(DataTable)
        self.assertEqual(table.row_count, 12)
        for tid in ids:
            self.assertIn(tid, table.rows)

    def test_header_row_is_not_shown(self):
        store = FakeStore()
        store.create_step("queued", step="build", role="coder")

        session = self._launch(store=store)

        table = session.app.query_one(DataTable)
        self.assertFalse(table.show_header)

    def test_column_render_widths_account_for_cell_padding_and_fit_the_frame(self):
        store = FakeStore()
        store.create_step("queued", step="build", role="coder")

        session = self._launch(store=store)

        table = session.app.query_one(DataTable)
        total_render_width = sum(
            column.get_render_width(table) for column in table.columns.values()
        )
        self.assertLessEqual(total_render_width, table.size.width)


class TestNeedsAttentionGroup(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def test_inbox_and_blocked_rows_render_above_active_and_queued(self):
        store = FakeStore()
        inbox = store.create_step("inbox item", step="triage", role="human")
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step("blocked item", step="build", role="coder", deps=[blocker])
        active = store.create_step("active item", step="build", role="coder")
        store.assign(active, "worker-1")

        session = self._launch(store)

        order = _row_order(session)
        self.assertLess(order.index(inbox), order.index(active))
        self.assertLess(order.index(blocked), order.index(active))

    def test_inbox_row_shows_single_icon_and_current_step_styled_amber(self):
        store = FakeStore()
        inbox = store.create_step("inbox item", step="code-await-merge", role="human")

        session = self._launch(store)

        self.assertEqual(_cell(session, inbox, "step"), "code-await-merge")
        table = session.app.query_one(DataTable)
        icon = table.get_cell(inbox, "icon")
        self.assertEqual(icon.plain, STATE_GLYPHS["needs-attention"].glyph)
        self.assertEqual(icon.style, COLOURS["red"])
        step_cell = table.get_cell(inbox, "step")
        self.assertEqual(step_cell.style, COLOURS["amber"])

    def test_blocked_row_shows_dual_icon_and_blocked_by_id_styled_amber(self):
        store = FakeStore()
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step("blocked item", step="build", role="coder", deps=[blocker])

        session = self._launch(store)

        self.assertEqual(_cell(session, blocked, "step"), "blocked · %s" % blocker)
        table = session.app.query_one(DataTable)
        icon = table.get_cell(blocked, "icon")
        self.assertIn(STATE_GLYPHS["needs-attention"].glyph, icon.plain)
        self.assertIn("⛓", icon.plain)

    def test_needs_attention_row_with_long_title_wraps(self):
        store = FakeStore()
        step = store.create_step("word " * 60, step="triage", role="human")

        session = self._launch(store)

        table = session.app.query_one(DataTable)
        row = next(r for r in table.ordered_rows if r.key.value == step)
        self.assertGreater(row.height, 1)


class TestActiveGroup(unittest.TestCase):
    def _launch(self, store, now=None):
        session = launch(make_test_container(store=store), now=now)
        self.addCleanup(session.close)
        return session

    def test_active_row_shows_step_colour_and_elapsed_time(self):
        claimed_at = datetime.datetime(2026, 1, 1, 12, 0, 0)
        rendered_at = datetime.datetime(2026, 1, 1, 12, 14, 0)
        store = FakeStore(now=lambda: claimed_at.isoformat())
        tid = store.create_step("active item", step="build", role="coder")
        store.assign(tid, "worker-1")
        store.update_state(tid, State.IN_PROGRESS)

        session = self._launch(store, now=lambda: rendered_at)

        self.assertEqual(_cell(session, tid, "step"), "build")
        self.assertEqual(_cell(session, tid, "time"), "14m")
        table = session.app.query_one(DataTable)
        icon = table.get_cell(tid, "icon")
        self.assertEqual(icon.plain, STATE_GLYPHS["active"].glyph)
        self.assertEqual(icon.style, COLOURS["cyan"])

    def test_second_poll_updates_only_time_cell_without_full_rebuild(self):
        clock = {"now": datetime.datetime(2026, 1, 1, 12, 0, 0)}
        store = FakeStore(now=lambda: clock["now"].isoformat())
        tid = store.create_step("active item", step="build", role="coder")
        store.assign(tid, "worker-1")
        store.update_state(tid, State.IN_PROGRESS)

        clock["now"] = datetime.datetime(2026, 1, 1, 12, 1, 0)
        session = self._launch(store, now=lambda: clock["now"])
        table = session.app.query_one(DataTable)
        row_count_before = table.row_count
        order_before = _row_order(session)
        time_before = _cell(session, tid, "time")

        clock["now"] = datetime.datetime(2026, 1, 1, 12, 2, 0)
        session.poll_tick()

        self.assertEqual(table.row_count, row_count_before)
        self.assertEqual(_row_order(session), order_before)
        self.assertNotEqual(_cell(session, tid, "time"), time_before)


class TestQueuedGroup(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def test_queued_row_renders_below_active_with_own_icon_and_next_step(self):
        store = FakeStore()
        active = store.create_step("active item", step="build", role="coder")
        store.assign(active, "worker-1")
        queued = store.create_step("queued item", step="build", role="coder")

        session = self._launch(store)

        order = _row_order(session)
        self.assertLess(order.index(active), order.index(queued))
        self.assertEqual(_cell(session, queued, "step"), "build")
        table = session.app.query_one(DataTable)
        icon = table.get_cell(queued, "icon")
        self.assertEqual(icon.plain, STATE_GLYPHS["queued"].glyph)

    def test_queued_step_transitioning_to_active_moves_group(self):
        store = FakeStore()
        queued = store.create_step("queued item", step="build", role="coder")

        session = self._launch(store)
        table = session.app.query_one(DataTable)
        icon_before = table.get_cell(queued, "icon").plain
        self.assertEqual(icon_before, STATE_GLYPHS["queued"].glyph)

        store.assign(queued, "worker-1")
        store.update_state(queued, State.IN_PROGRESS)
        session.poll_tick()

        icon_after = table.get_cell(queued, "icon").plain
        self.assertEqual(icon_after, STATE_GLYPHS["active"].glyph)

    def test_blocked_step_does_not_appear_in_queued_group(self):
        store = FakeStore()
        blocker = store.create_step("blocker", step="build", role="coder")
        blocked = store.create_step("blocked item", step="build", role="coder", deps=[blocker])

        session = self._launch(store)

        icon = session.app.query_one(DataTable).get_cell(blocked, "icon")
        self.assertIn(STATE_GLYPHS["needs-attention"].glyph, icon.plain)


class TestProjectColumn(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def test_step_with_registered_project_renders_it_in_cyan(self):
        store = FakeStore()
        item = store.create_item("story")
        store.add_artifact(item, "repo", "lightcycle")
        step = store.create_step("build", step="build", role="coder", parent=item)

        session = self._launch(store)

        table = session.app.query_one(DataTable)
        cell = table.get_cell(step, "project")
        self.assertEqual(cell.plain, "lightcycle")
        self.assertEqual(cell.style, COLOURS["cyan"])

    def test_step_with_no_registered_project_renders_blank(self):
        store = FakeStore()
        step = store.create_step("build", step="build", role="coder")

        session = self._launch(store)

        self.assertEqual(_cell(session, step, "project"), "")

    def test_step_with_slash_qualified_repo_renders_the_short_label(self):
        store = FakeStore()
        item = store.create_item("story")
        store.add_artifact(item, "repo", "kenmclennan/lightcycle")
        step = store.create_step("build", step="build", role="coder", parent=item)

        session = self._launch(store)

        table = session.app.query_one(DataTable)
        cell = table.get_cell(step, "project")
        self.assertEqual(cell.plain, "lightcycle")
        self.assertEqual(cell.style, COLOURS["cyan"])


class TestCursorColumn(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def test_selected_row_shows_leading_cursor_glyph(self):
        store = FakeStore()
        first = store.create_step("first", step="build", role="coder")
        store.create_step("second", step="build", role="coder")

        session = self._launch(store)

        table = session.app.query_one(DataTable)
        first_cursor = table.get_cell(first, "cursor")
        self.assertEqual(first_cursor.plain, CURSOR_GLYPH.glyph)
        self.assertEqual(first_cursor.style, COLOURS[CURSOR_GLYPH.colour])

    def test_cursor_glyph_follows_the_selection(self):
        store = FakeStore()
        first = store.create_step("first", step="build", role="coder")
        second = store.create_step("second", step="build", role="coder")

        session = self._launch(store)
        session.press("down")

        table = session.app.query_one(DataTable)
        self.assertEqual(_cell_text(table.get_cell(first, "cursor")), "")
        self.assertEqual(table.get_cell(second, "cursor").plain, CURSOR_GLYPH.glyph)


class TestScroll(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def test_down_moves_cursor_row_by_row(self):
        store = FakeStore()
        for i in range(30):
            store.create_step("q%d" % i, step="build", role="coder")

        session = self._launch(store)
        table = session.app.query_one(DataTable)
        self.assertEqual(table.cursor_row, 0)
        session.press("down")
        self.assertEqual(table.cursor_row, 1)

    def test_up_does_not_wrap_past_first_row(self):
        store = FakeStore()
        for i in range(5):
            store.create_step("q%d" % i, step="build", role="coder")

        session = self._launch(store)
        session.press("up")
        table = session.app.query_one(DataTable)
        self.assertEqual(table.cursor_row, 0)

    def test_ctrl_d_then_ctrl_u_moves_by_page_and_back(self):
        store = FakeStore()
        for i in range(60):
            store.create_step("q%d" % i, step="build", role="coder")

        session = self._launch(store)
        table = session.app.query_one(DataTable)
        session.press("ctrl+d")
        self.assertGreater(table.cursor_row, 0)
        session.press("ctrl+u")
        self.assertEqual(table.cursor_row, 0)

    def test_ctrl_d_moves_the_same_amount_as_page_down(self):
        def build_store():
            store = FakeStore()
            for i in range(60):
                store.create_step("q%d" % i, step="build", role="coder")
            return store

        ctrl_session = launch(make_test_container(store=build_store()))
        self.addCleanup(ctrl_session.close)
        ctrl_session.press("ctrl+d")
        ctrl_row = ctrl_session.app.query_one(DataTable).cursor_row

        page_session = launch(make_test_container(store=build_store()))
        self.addCleanup(page_session.close)
        page_session.press("pagedown")
        page_row = page_session.app.query_one(DataTable).cursor_row

        self.assertEqual(ctrl_row, page_row)
        self.assertGreater(ctrl_row, 0)


class TestSelectionFollow(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def test_selection_follows_item_that_changes_group(self):
        store = FakeStore()
        store.create_step("other", step="build", role="coder")
        target = store.create_step("target", step="build", role="coder")

        session = self._launch(store)
        table = session.app.query_one(DataTable)
        table.move_cursor(row=table.get_row_index(target))
        session.pause()

        store.assign(target, "worker-1")
        store.update_state(target, State.IN_PROGRESS)
        session.poll_tick()

        cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        self.assertEqual(cell_key.row_key.value, target)

    def test_selection_falls_to_a_real_row_when_selected_item_is_removed(self):
        store = FakeStore()
        first = store.create_step("first", step="build", role="coder")
        target = store.create_step("target", step="build", role="coder")
        last = store.create_step("last", step="build", role="coder")

        session = self._launch(store)
        table = session.app.query_one(DataTable)
        table.move_cursor(row=table.get_row_index(target))
        session.pause()

        store.close(target, "done")
        session.poll_tick()

        cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        remaining_id = cell_key.row_key.value
        self.assertIn(remaining_id, (first, last))


class TestEmptyState(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def test_empty_store_shows_calm_message_and_no_rows(self):
        session = self._launch(FakeStore())

        self.assertTrue(session.app.query_one("#empty-state").display)
        table = session.app.query_one(DataTable)
        self.assertFalse(table.display)
        self.assertEqual(table.row_count, 0)

    def test_message_is_replaced_once_a_row_appears(self):
        store = FakeStore()
        session = self._launch(store)

        store.create_step("new", step="build", role="coder")
        session.poll_tick()

        self.assertFalse(session.app.query_one("#empty-state").display)
        table = session.app.query_one(DataTable)
        self.assertTrue(table.display)
        self.assertEqual(table.row_count, 1)


class TestBell(unittest.TestCase):
    def _launch(self, store):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        return session

    def _spy(self, session):
        calls = {"count": 0}
        original = session.app.bell

        def spy():
            calls["count"] += 1
            original()

        session.app.bell = spy
        return calls

    def test_rings_once_on_fresh_transition_into_needs_attention(self):
        store = FakeStore()
        session = self._launch(store)
        calls = self._spy(session)

        blocker = store.create_step("blocker", step="build", role="coder")
        store.create_step("blocked", step="build", role="coder", deps=[blocker])
        session.poll_tick()

        self.assertEqual(calls["count"], 1)

    def test_does_not_refire_while_item_stays_in_needs_attention(self):
        store = FakeStore()
        session = self._launch(store)
        blocker = store.create_step("blocker", step="build", role="coder")
        store.create_step("blocked", step="build", role="coder", deps=[blocker])
        session.poll_tick()
        calls = self._spy(session)

        session.poll_tick()

        self.assertEqual(calls["count"], 0)

    def test_does_not_fire_for_transition_into_active_or_queued(self):
        store = FakeStore()
        session = self._launch(store)
        calls = self._spy(session)

        store.create_step("queued", step="build", role="coder")
        session.poll_tick()

        self.assertEqual(calls["count"], 0)

    def test_does_not_fire_on_initial_render_for_item_already_present(self):
        store = FakeStore()
        blocker = store.create_step("blocker", step="build", role="coder")
        store.create_step("blocked", step="build", role="coder", deps=[blocker])

        calls = {"count": 0}
        original_bell = LightcycleApp.bell

        def spy(self):
            calls["count"] += 1
            original_bell(self)

        with patch.object(LightcycleApp, "bell", spy):
            self._launch(store)

        self.assertEqual(calls["count"], 0)


class TestFooterVersionSegment(unittest.TestCase):
    def _launch(self, **kwargs):
        session = launch(make_test_container(**kwargs))
        self.addCleanup(session.close)
        return session

    def test_always_renders_installed_version_in_dim(self):
        session = self._launch(
            lock=FakeLock(running=True), breaker=FakeBreakerPort(is_open=True, reset_at=500.0)
        )

        _, text, style = _rendered_segment(session, "#status-version")

        self.assertEqual(text, "v%s" % __version__)
        self.assertEqual(_colour_of(style), COLOURS["dim"].lower())


class TestFooterUpgradeSegment(unittest.TestCase):
    def _launch(self, upgrade_check, size=None):
        session = launch(make_test_container(), upgrade_check=upgrade_check, size=size)
        self.addCleanup(session.close)
        return session

    def test_upgrade_segment_is_right_aligned_against_the_frame_edge(self):
        def upgrade_check():
            return UpgradeResponse(current=__version__, remote="9.9.9", available=True, applied=False)

        for width in (80, 120):
            session = self._launch(upgrade_check, size=(width, 24))

            status_bar = session.app.query_one(StatusBar)
            spans = _painted_spans(_painted_row(session, status_bar.region.y))

            border_start, border_end, border_colour = spans[-1]
            self.assertEqual(border_colour, COLOURS["border"].lower())
            self.assertEqual(border_start, width - 1)
            self.assertEqual(border_end, width - 1)

            amber_spans = [span for span in spans if span[2] == COLOURS["amber"].lower()]
            dim_spans = [span for span in spans if span[2] == COLOURS["dim"].lower()]
            self.assertTrue(amber_spans)
            self.assertTrue(dim_spans)

            upgrade_start, upgrade_end, _ = amber_spans[-1]
            version_end = dim_spans[-1][1]

            self.assertEqual(upgrade_end, border_start - 1)
            self.assertLess(version_end, upgrade_start)

    def test_upgrade_available_renders_glyph_and_version(self):
        session = self._launch(
            lambda: UpgradeResponse(current=__version__, remote="9.9.9", available=True, applied=False)
        )

        widget, text, style = _rendered_segment(session, "#status-upgrade")

        self.assertTrue(widget.display)
        self.assertEqual(text, "%s v9.9.9 available" % FOOTER_GLYPHS["upgrade-available"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["amber"].lower())

    def test_no_newer_version_renders_no_upgrade_segment(self):
        session = self._launch(
            lambda: UpgradeResponse(
                current=__version__, remote=__version__, available=False, applied=False
            )
        )

        widget, text, _ = _rendered_segment(session, "#status-upgrade")

        self.assertFalse(widget.display)
        self.assertEqual(text.strip(), "")

    def test_failed_upgrade_check_renders_no_upgrade_segment_and_rest_of_footer_still_renders(self):
        def _raising_check():
            raise RuntimeError("network down")

        session = self._launch(_raising_check)

        widget, text, _ = _rendered_segment(session, "#status-upgrade")
        self.assertFalse(widget.display)
        self.assertEqual(text.strip(), "")

        _, pool_text, _ = _rendered_segment(session, "#status-pool")
        _, claude_text, _ = _rendered_segment(session, "#status-claude")
        _, version_text, _ = _rendered_segment(session, "#status-version")
        self.assertNotEqual(pool_text.strip(), "")
        self.assertNotEqual(claude_text.strip(), "")
        self.assertNotEqual(version_text.strip(), "")


class TestFooterPoolSegment(unittest.TestCase):
    def _launch(self, **kwargs):
        session = launch(make_test_container(**kwargs))
        self.addCleanup(session.close)
        return session

    def test_pool_running_renders_cyan_dot(self):
        session = self._launch(lock=FakeLock(running=True))

        _, text, style = _rendered_segment(session, "#status-pool")

        self.assertEqual(text, "%s pool running" % FOOTER_GLYPHS["pool-running"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["cyan"].lower())

    def test_pool_not_running_renders_dim_circle_never_blank(self):
        session = self._launch()

        _, text, style = _rendered_segment(session, "#status-pool")

        self.assertEqual(text, "%s pool not running" % FOOTER_GLYPHS["pool-stopped"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["dim"].lower())

    def test_pool_state_change_reflects_without_restart(self):
        lock = FakeLock(running=False)
        session = self._launch(lock=lock)

        lock.set_running(True)
        session.poll_tick()

        _, text, _ = _rendered_segment(session, "#status-pool")
        self.assertEqual(text, "%s pool running" % FOOTER_GLYPHS["pool-running"].glyph)


class TestFooterClaudeSegment(unittest.TestCase):
    def _launch(self, **kwargs):
        session = launch(make_test_container(**kwargs))
        self.addCleanup(session.close)
        return session

    def test_closed_breaker_renders_claude_available(self):
        session = self._launch(breaker=FakeBreakerPort(is_open=False))

        _, text, style = _rendered_segment(session, "#status-claude")

        self.assertEqual(text, "%s claude available" % FOOTER_GLYPHS["claude-available"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["cyan"].lower())

    def test_open_breaker_renders_claude_unavailable_with_resume_time(self):
        reset_at = 1234567890.0
        session = self._launch(breaker=FakeBreakerPort(is_open=True, reset_at=reset_at))

        _, text, style = _rendered_segment(session, "#status-claude")

        expected_ts = time.strftime("%H:%M:%S", time.localtime(reset_at))
        self.assertEqual(
            text,
            "%s claude unavailable · resumes %s"
            % (FOOTER_GLYPHS["claude-unavailable"].glyph, expected_ts),
        )
        self.assertEqual(_colour_of(style), COLOURS["red"].lower())

    def test_breaker_closing_returns_to_claude_available_without_restart(self):
        breaker = FakeBreakerPort(is_open=True, reset_at=1234567890.0)
        session = self._launch(breaker=breaker)

        breaker.save({"open": False, "reset_at": None})
        session.poll_tick()

        _, text, style = _rendered_segment(session, "#status-claude")
        self.assertEqual(text, "%s claude available" % FOOTER_GLYPHS["claude-available"].glyph)
        self.assertEqual(_colour_of(style), COLOURS["cyan"].lower())


class TestQuit(unittest.TestCase):
    def _launch(self):
        session = launch(make_test_container())
        self.addCleanup(session.close)
        return session

    def test_q_exits_the_dashboard(self):
        session = self._launch()
        session.press("q")
        self.assertFalse(session.app.is_running)

    def test_ctrl_c_exits_the_dashboard(self):
        session = self._launch()
        session.press("ctrl+c")
        self.assertFalse(session.app.is_running)


def _launch_backlog(store, **kwargs):
    session = launch(make_test_container(store=store, **kwargs))
    session.press("tab")
    return session


def _backlog_cell(session, row_id, column):
    table = session.app.query_one(BacklogTable)
    return _cell_text(table.get_cell(row_id, column))


def _rendered_text(widget):
    strip = widget.render_line(0)
    return "".join(segment.text for segment in strip)


def _picker_option_by_label(screen, label):
    for option in screen.query(PickerOption):
        text = _rendered_text(option.query_one("#picker-option-label", Static))
        if text.replace(CURSOR_GLYPH.glyph, "").strip() == label:
            return option
    raise AssertionError("no picker option labelled %r" % label)


class TestBacklogRows(unittest.TestCase):
    def _launch(self, store):
        session = _launch_backlog(store)
        self.addCleanup(session.close)
        return session

    def test_todo_items_render_as_rows_once_backlog_is_current(self):
        store = FakeStore()
        item = store.create_item("todo item")

        session = self._launch(store)

        table = session.app.query_one(BacklogTable)
        self.assertIn(item, table.rows)
        self.assertEqual(_backlog_cell(session, item, "id"), item)
        self.assertEqual(_backlog_cell(session, item, "title"), "todo item")

    def test_item_activated_disappears_from_backlog_without_restart(self):
        store = FakeStore()
        item = store.create_item("todo item")
        session = self._launch(store)
        self.assertIn(item, session.app.query_one(BacklogTable).rows)

        store.create_step("first step", step="build", role="coder", parent=item)
        session.poll_tick()

        self.assertNotIn(item, session.app.query_one(BacklogTable).rows)

    def test_ctrl_u_and_ctrl_d_page_a_long_backlog(self):
        store = FakeStore()
        for i in range(60):
            store.create_item("todo %d" % i)

        session = self._launch(store)
        table = session.app.query_one(BacklogTable)
        session.press("ctrl+d")
        self.assertGreater(table.cursor_row, 0)
        session.press("ctrl+u")
        self.assertEqual(table.cursor_row, 0)


class TestBacklogTableColumnWidth(unittest.TestCase):
    def _launch(self, store):
        session = _launch_backlog(store)
        self.addCleanup(session.close)
        return session

    def test_title_column_is_not_clamped_to_one_char_right_after_tab(self):
        store = FakeStore()
        store.create_item("a reasonably long backlog title")

        session = self._launch(store)

        table = session.app.query_one(BacklogTable)
        rendered = "".join(segment.text for segment in table.render_line(0))
        self.assertIn("a reasonably long backlog title", rendered)

    def test_title_width_defers_instead_of_clamping_to_one_while_hidden(self):
        store = FakeStore()
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)

        table = session.app.query_one(BacklogTable)

        self.assertEqual(table.size.width, 0)
        self.assertEqual(len(table.columns), 0)


class TestBacklogProjectColumn(unittest.TestCase):
    def _launch(self, store):
        session = _launch_backlog(store)
        self.addCleanup(session.close)
        return session

    def test_unscoped_item_shows_blank_project(self):
        store = FakeStore()
        item = store.create_item("todo item")

        session = self._launch(store)

        self.assertEqual(_backlog_cell(session, item, "project"), "")

    def test_slash_qualified_repo_shows_shortened_label_in_cyan(self):
        store = FakeStore()
        item = store.create_item("todo item")
        store.add_artifact(item, "repo", "kenmclennan/lightcycle")

        session = self._launch(store)

        table = session.app.query_one(BacklogTable)
        cell = table.get_cell(item, "project")
        self.assertEqual(cell.plain, "lightcycle")
        self.assertEqual(cell.style, COLOURS["cyan"])


class TestBacklogTabSwitch(unittest.TestCase):
    def _launch(self, store=None):
        session = launch(make_test_container(store=store or FakeStore()))
        self.addCleanup(session.close)
        return session

    def test_tab_shows_backlog_in_place_of_priority_list(self):
        session = self._launch()

        session.press("tab")

        self.assertTrue(session.app.query_one(BacklogView).display)
        self.assertFalse(session.app.query_one(PriorityTable).display)
        self.assertIn("tab-active", session.app.query_one("#tab-backlog").classes)
        self.assertIn("tab-dim", session.app.query_one("#tab-current-work").classes)

    def test_tab_again_returns_to_priority_list(self):
        session = self._launch()

        session.press("tab")
        session.press("tab")

        self.assertFalse(session.app.query_one(BacklogView).display)
        self.assertIn("tab-active", session.app.query_one("#tab-current-work").classes)
        self.assertIn("tab-dim", session.app.query_one("#tab-backlog").classes)


class TestBacklogPicker(unittest.TestCase):
    def _launch(self, store):
        session = _launch_backlog(store)
        self.addCleanup(session.close)
        return session

    def _store_with_two_projects(self):
        store = FakeStore()
        store.add_project("org-a/proj-a")
        store.add_project("org-b/proj-b")
        a = store.create_item("a item")
        store.add_artifact(a, "repo", "org-a/proj-a")
        b = store.create_item("b item")
        store.add_artifact(b, "repo", "org-b/proj-b")
        return store

    def test_f_opens_a_picker_listing_all_and_every_project_with_its_own_count(self):
        session = self._launch(self._store_with_two_projects())

        session.press("f")

        screen = session.app.screen
        self.assertIsInstance(screen, ProjectFilterPicker)
        head = _rendered_text(screen.query_one("#picker-head", Static)).strip()
        self.assertEqual(head, "Filter by project")
        all_option = _picker_option_by_label(screen, "All")
        self.assertEqual(
            _rendered_text(all_option.query_one(".picker-option-count", Static)).strip(), "2"
        )
        proj_a = _picker_option_by_label(screen, "proj-a")
        self.assertEqual(
            _rendered_text(proj_a.query_one(".picker-option-count", Static)).strip(), "1"
        )

    def test_zero_count_project_is_included(self):
        store = FakeStore()
        store.add_project("org-c/proj-c")

        session = self._launch(store)
        session.press("f")

        option = _picker_option_by_label(session.app.screen, "proj-c")
        self.assertEqual(
            _rendered_text(option.query_one(".picker-option-count", Static)).strip(), "0"
        )

    def test_down_and_up_move_the_highlighted_option(self):
        store = FakeStore()
        store.add_project("org-a/proj-a")

        session = self._launch(store)
        session.press("f")
        session.press("down")

        option = _picker_option_by_label(session.app.screen, "proj-a")
        self.assertIn("picker-option-selected", option.classes)

        session.press("up")

        all_option = _picker_option_by_label(session.app.screen, "All")
        self.assertIn("picker-option-selected", all_option.classes)

    def test_enter_applies_the_highlighted_project_and_closes_the_picker_immediately(self):
        session = self._launch(self._store_with_two_projects())

        session.press("f")
        session.press("down")
        session.press("enter")

        self.assertNotIsInstance(session.app.screen, ProjectFilterPicker)
        _, left, _ = _rendered_segment(session, "#backlog-filter-left")
        self.assertEqual(left, "PROJECT: proj-a")
        self.assertEqual(session.app.query_one(BacklogTable).row_count, 1)

    def test_esc_closes_the_picker_without_changing_the_filter(self):
        store = FakeStore()
        store.add_project("org-a/proj-a")

        session = self._launch(store)
        session.press("f")
        session.press("escape")

        self.assertNotIsInstance(session.app.screen, ProjectFilterPicker)
        _, left, _ = _rendered_segment(session, "#backlog-filter-left")
        self.assertEqual(left, "PROJECT: All")

    def test_filter_bar_shows_only_the_active_filters_own_count(self):
        session = self._launch(self._store_with_two_projects())

        session.press("f")
        session.press("down")
        session.press("enter")

        _, right, _ = _rendered_segment(session, "#backlog-filter-right")
        self.assertEqual(right, "1 items")


class TestBacklogFilterBar(unittest.TestCase):
    def _launch(self, store):
        session = _launch_backlog(store)
        self.addCleanup(session.close)
        return session

    def test_shows_all_and_the_total_count_while_unfiltered(self):
        store = FakeStore()
        for i in range(3):
            store.create_item("todo %d" % i)

        session = self._launch(store)

        _, left, _ = _rendered_segment(session, "#backlog-filter-left")
        _, right, _ = _rendered_segment(session, "#backlog-filter-right")
        self.assertEqual(left, "PROJECT: All")
        self.assertEqual(right, "3 items")

    def test_count_is_plural_even_when_zero(self):
        session = self._launch(FakeStore())

        _, right, _ = _rendered_segment(session, "#backlog-filter-right")
        self.assertEqual(right, "0 items")


class TestBacklogEmptyStates(unittest.TestCase):
    def _launch(self, store):
        session = _launch_backlog(store)
        self.addCleanup(session.close)
        return session

    def _filter_to_lightcycle(self, session):
        session.app._backlog_project_filter = "lightcycle"
        session.run(session.app._refresh)
        session.pause()

    def test_overall_empty_shows_a_calm_message_instead_of_a_blank_area(self):
        session = self._launch(FakeStore())

        table = session.app.query_one(BacklogTable)
        self.assertFalse(table.display)
        widget = session.app.query_one("#backlog-empty-overall", Static)
        self.assertTrue(widget.display)
        self.assertEqual(_rendered_text(widget).strip(), "Nothing in the backlog.")

    def test_filtered_empty_names_the_project_with_a_colour_split_and_a_hint(self):
        store = FakeStore()
        store.add_project("lightcycle")
        other = store.create_item("other project item")
        store.add_artifact(other, "repo", "other")
        session = self._launch(store)

        self._filter_to_lightcycle(session)

        message_widget = session.app.query_one("#backlog-empty-filtered-message", Static)
        self.assertTrue(message_widget.display)
        strip = message_widget.render_line(0)
        rendered = "".join(segment.text for segment in strip)
        self.assertEqual(rendered.strip(), "No backlog items for lightcycle.")
        project_style = next(s.style for s in strip if "lightcycle" in s.text)
        rest_style = next(s.style for s in strip if s.text.strip() and "lightcycle" not in s.text)
        self.assertEqual(_colour_of(project_style), COLOURS["text"].lower())
        self.assertEqual(_colour_of(rest_style), COLOURS["dim"].lower())

        hint_widget = session.app.query_one("#backlog-empty-filtered-hint", Static)
        self.assertTrue(hint_widget.display)
        self.assertEqual(_rendered_text(hint_widget).strip(), "Press f to check All.")

    def test_item_becoming_available_replaces_the_filtered_empty_message_with_the_list(self):
        store = FakeStore()
        store.add_project("lightcycle")
        other = store.create_item("other project item")
        store.add_artifact(other, "repo", "other")
        session = self._launch(store)
        self._filter_to_lightcycle(session)

        new_item = store.create_item("new item")
        store.add_artifact(new_item, "repo", "lightcycle")
        session.poll_tick()

        table = session.app.query_one(BacklogTable)
        self.assertTrue(table.display)
        self.assertIn(new_item, table.rows)
        self.assertFalse(session.app.query_one("#backlog-empty-filtered-message", Static).display)


class TestBacklogFooter(unittest.TestCase):
    def _launch(self, store):
        session = _launch_backlog(store)
        self.addCleanup(session.close)
        return session

    def test_rows_present_shows_the_backlog_shortcuts(self):
        store = FakeStore()
        store.create_item("todo item")

        session = self._launch(store)

        self.assertEqual(session.app.query_one(ShortcutBar).shortcuts, BACKLOG_SHORTCUTS)

    def test_overall_empty_shows_the_trimmed_shortcuts(self):
        session = self._launch(FakeStore())

        self.assertEqual(session.app.query_one(ShortcutBar).shortcuts, BACKLOG_EMPTY_SHORTCUTS)

    def test_filtered_empty_shows_the_filter_reachable_shortcuts(self):
        store = FakeStore()
        store.add_project("lightcycle")
        other = store.create_item("other project item")
        store.add_artifact(other, "repo", "other")
        session = self._launch(store)

        session.app._backlog_project_filter = "lightcycle"
        session.run(session.app._refresh)
        session.pause()

        self.assertEqual(
            session.app.query_one(ShortcutBar).shortcuts, BACKLOG_FILTERED_EMPTY_SHORTCUTS
        )

    def test_returning_to_priority_list_restores_the_global_shortcuts(self):
        store = FakeStore()
        store.create_item("todo item")
        session = self._launch(store)

        session.press("tab")

        self.assertEqual(session.app.query_one(ShortcutBar).shortcuts, GLOBAL_SHORTCUTS)
