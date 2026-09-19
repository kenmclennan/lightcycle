import unittest

from lightcycle.adapters.tui.app import GoalsTable, GoalsView, TabStrip
from lightcycle.adapters.tui.goal_hub import (
    GOAL_ITEMS_EMPTY_MESSAGE,
    GOAL_DESCRIPTION_EMPTY_MESSAGE,
    GOAL_TAB_ORDER,
    GOAL_LOG_NO_MATCH_MESSAGE,
    GOAL_LOG_EMPTY_MESSAGE,
    GoalHubScreen,
    GoalLogFilterInput,
)
from lightcycle.adapters.tui.design_system import (
    GOAL_LOG_SEARCH_SHORTCUTS,
    GOAL_LOG_SHORTCUTS,
    HUB_SHORTCUTS,
)
from lightcycle.adapters.tui.footer import ShortcutBar
from lightcycle.domain.goals import GoalLogEntry
from lightcycle.adapters.tui.hub import HUB_TAB_STRIP_CSS, HubTabStrip, NodeHubScreen
from tests.support.fake_store import FakeStore
from tests.support.screen_render import (
    GOAL_DESCRIPTION,
    SCREENS,
    _goals_store,
    _launch,
    render,
)


def _frame(session):
    from tests.support.screen_render import _plain_row

    strips = session.run(lambda: session.app.screen._compositor.render_strips())
    return "\n".join(_plain_row(strip) for strip in strips)


def _header(session):
    return next(
        line for line in _frame(session).splitlines() if "Ship the goals record" in line
    )


class TestGoalsTab(unittest.TestCase):
    def _launch(self, store):
        session = _launch(store)
        self.addCleanup(session.close)
        return session

    def test_tab_strip_reads_goals_first(self):
        session = self._launch(FakeStore())
        strip = session.app.query_one(TabStrip)
        rendered = "".join(str(child.content) for child in strip.children)
        self.assertEqual(rendered, "Goals · Current work · Backlog · Done · Report")

    def test_landing_view_is_priority_with_an_empty_store_and_with_goals(self):
        for store in (FakeStore(), _goals_store()[0]):
            session = self._launch(store)
            self.assertEqual(session.app._view, "priority")
            self.assertIn("tab-active", session.app.query_one("#tab-current-work").classes)
            self.assertFalse(session.app.query_one(GoalsView).display)

    def test_goals_table_is_one_column_of_titles_with_no_status_text(self):
        store, _ = _goals_store()
        session = self._launch(store)
        session.press("[")
        table = session.app.query_one(GoalsTable)
        frame = _frame(session)

        self.assertEqual(len(table.columns), 1)
        self.assertEqual(table.row_count, 3)
        self.assertIn("Ship the goals record", frame)
        for status in ("not started", "in progress", "done"):
            self.assertNotIn(status, frame)

    def test_selecting_a_goal_pushes_the_goal_hub(self):
        store, gid = _goals_store()
        session = self._launch(store)
        session.press("[")
        session.press("enter")

        self.assertIsInstance(session.app.screen, GoalHubScreen)
        self.assertNotIsInstance(session.app.screen, NodeHubScreen)
        frame = _frame(session)
        self.assertIn("Ship the goals record", frame)
        self.assertNotIn(gid, frame)

    def test_empty_goals_tab_says_so(self):
        session = self._launch(FakeStore())
        session.press("[")
        self.assertIn("No goals yet.", _frame(session))

    def test_goals_view_refreshes_on_poll_only_while_visible(self):
        store, _ = _goals_store()
        session = self._launch(store)
        store.create_goal("A goal that appeared while on another tab")
        session.poll_tick()
        self.assertEqual(session.app.query_one(GoalsTable).row_count, 0)
        session.press("[")
        self.assertEqual(session.app.query_one(GoalsTable).row_count, 4)


class TestGoalHub(unittest.TestCase):
    def _open(self, populated=True):
        store, gid = _goals_store(with_content=populated)
        session = _launch(store)
        self.addCleanup(session.close)
        session.press("[")
        session.press("enter")
        return session, store, gid

    def test_tabs_are_overview_log_items_and_wrap_both_ways(self):
        session, _, _ = self._open()
        strip = session.app.screen.query_one(HubTabStrip)
        labels = [str(child.content) for child in strip.children]
        self.assertEqual(labels, ["Overview", "Log", "Items"])
        self.assertEqual(GOAL_TAB_ORDER, ("overview", "log", "items"))

        seen = []
        for _ in range(3):
            session.press("]")
            seen.append(session.app.screen._active_tab)
        self.assertEqual(seen, ["log", "items", "overview"])

        session.press("[")
        self.assertEqual(session.app.screen._active_tab, "items")

    def test_escape_and_left_close_the_hub(self):
        for key in ("escape", "left"):
            session, _, _ = self._open()
            session.press(key)
            self.assertNotIsInstance(session.app.screen, GoalHubScreen)

    def test_header_carries_title_status_and_project_but_no_id_or_status_label(self):
        session, _, gid = self._open()
        header = _header(session)
        self.assertIn("Ship the goals record", header)
        self.assertIn("not started", header)
        self.assertIn("lightcycle", header)
        self.assertNotIn(gid, _frame(session))
        self.assertNotIn("status", _frame(session))

    def test_overview_is_one_continuous_document_with_no_labels_or_progress_line(self):
        session, _, _ = self._open()
        frame = _frame(session)
        self.assertIn(GOAL_DESCRIPTION[:40], frame)
        self.assertNotIn(GOAL_DESCRIPTION, frame)
        for text in ("## Outcome", "## Constraints", "## Open questions"):
            self.assertIn(text, frame)
        self.assertNotIn("OUTCOME", frame)
        self.assertNotIn("SCOPE", frame)
        self.assertNotIn("Progress statement", frame)

    def test_a_description_taller_than_the_screen_scrolls(self):
        store, gid = _goals_store()
        store.update_goal(gid, description="\n".join("line %d" % n for n in range(80)))
        session = _launch(store, size=(80, 24))
        self.addCleanup(session.close)
        session.press("[")
        session.press("enter")
        before = _frame(session)
        self.assertIn("line 0", before)
        self.assertNotIn("line 79", before)
        for _ in range(3):
            session.press("pagedown")
        after = _frame(session)
        self.assertNotIn("line 0\n", after)
        self.assertNotEqual(before, after)

    def test_overview_of_a_bare_goal_shows_the_empty_state_not_a_blank_pane(self):
        session, _, _ = self._open(populated=False)
        self.assertIn(GOAL_DESCRIPTION_EMPTY_MESSAGE, _frame(session))

    def test_a_goal_without_a_project_shows_nothing_in_that_position(self):
        store, gid = _goals_store()
        store.update_goal(gid, project="")
        session = _launch(store)
        self.addCleanup(session.close)
        session.press("[")
        session.press("enter")
        self.assertEqual(
            _header(session).strip("│ ").split(),
            ["Ship", "the", "goals", "record", "not", "started"],
        )

    def test_log_is_newest_first(self):
        session, _, _ = self._open()
        session.press("]")
        frame = _frame(session)
        self.assertLess(
            frame.index("Per-machine thresholds ratcheted"),
            frame.index("Suspending cannot relieve"),
        )

    def test_items_show_ids_and_titles_and_no_state(self):
        session, _, _ = self._open()
        for _ in range(2):
            session.press("]")
        frame = _frame(session)
        self.assertIn("LC-858", frame)
        self.assertIn("Goals slice 1: the record and the tab", frame)
        for word in ("todo", "ready", "running", "waiting", "blocked", "active"):
            self.assertNotIn(word, frame)

    def test_items_empty_state(self):
        session, _, _ = self._open(populated=False)
        for _ in range(2):
            session.press("]")
        self.assertIn(GOAL_ITEMS_EMPTY_MESSAGE, _frame(session))

    def test_a_log_entry_written_elsewhere_appears_after_a_poll(self):
        session, store, gid = self._open()
        session.press("]")
        store.add_goal_log(gid, "a title from elsewhere", "a decision made in another terminal")
        session.run(session.app.screen.poll_refresh)
        session.pause()
        self.assertIn("a decision made in another terminal", _frame(session))

    def test_both_hubs_carry_the_shared_tab_strip_rules(self):
        self.assertIn(HUB_TAB_STRIP_CSS, GoalHubScreen.CSS)
        self.assertIn(HUB_TAB_STRIP_CSS, NodeHubScreen.CSS)

    def test_goal_hub_states_are_registered(self):
        for state in (
            "goals#normal", "goals#empty", "goal-hub#overview", "goal-hub#log",
            "goal-hub#log-search", "goal-hub#log-search-none", "goal-hub#log-empty",
            "goal-hub#overview-empty", "goal-hub#items", "goal-hub#items-empty",
        ):
            self.assertIn(state, SCREENS)
        for state in ("goal-hub#questions", "goal-hub#questions-empty"):
            self.assertNotIn(state, SCREENS)

    def test_goal_hub_fits_a_narrow_terminal(self):
        frame = render("goal-hub#overview", size=(44, 30))
        self.assertIn("Overview", frame)


def _rows(session):
    return [line.strip("│") for line in _frame(session).splitlines()]


class TestGoalLogLayout(unittest.TestCase):
    def _open(self, populated=True, size=(100, 30)):
        store, gid = _goals_store(with_content=populated)
        session = _launch(store, size=size)
        self.addCleanup(session.close)
        session.press("[")
        session.press("enter")
        session.press("]")
        return session, store, gid

    def _width(self, session):
        return session.run(session.app.screen._log_width)

    def _titled(self, store, gid, title):
        store.add_goal_log(gid, title, "a body")

    def test_header_has_title_left_stamp_right_then_blank_body_blank(self):
        session, _, _ = self._open()
        rows = _rows(session)
        width = self._width(session)
        start = next(i for i, r in enumerate(rows) if "Per-machine thresholds" in r)
        header = rows[start][:width]
        self.assertTrue(header.startswith("Per-machine thresholds ratcheted the pool to zero"))
        self.assertRegex(header, r"\d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(rows[start + 1].strip(), "")
        self.assertTrue(rows[start + 2].startswith("Tried gating on combined_pressure"))
        after_body = next(
            i for i in range(start + 2, len(rows)) if rows[i].strip() == ""
        )
        self.assertTrue(rows[after_body + 1].startswith("Suspending cannot relieve"))

    def test_no_seconds_microseconds_or_offset_are_painted(self):
        session, _, _ = self._open()
        frame = _frame(session)
        self.assertNotRegex(frame, r"\d\d:\d\d:\d\d")
        self.assertNotRegex(frame, r"[+-]\d\d:\d\d\b")

    def test_a_title_that_exactly_fills_the_width_stays_on_one_line(self):
        session, store, gid = self._open()
        width = self._width(session)
        title = "t" * (width - 16 - 2)
        self._titled(store, gid, title)
        session.run(session.app.screen.poll_refresh)
        session.pause()
        row = next(r for r in _rows(session) if r.startswith(title))
        self.assertRegex(row[:width], r"\d{4}-\d\d-\d\d \d\d:\d\d$")

    def test_a_title_one_column_longer_wraps_and_keeps_the_stamp_on_the_first_line(self):
        session, store, gid = self._open()
        width = self._width(session)
        title = " ".join(["word"] * 30)[: width - 16 - 2 + 1]
        self._titled(store, gid, title)
        session.run(session.app.screen.poll_refresh)
        session.pause()
        rows = _rows(session)
        first = next(i for i, r in enumerate(rows) if r.startswith("word word"))
        self.assertRegex(rows[first][:width], r"\d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertNotRegex(rows[first + 1][:width], r"\d{4}-\d\d-\d\d")
        self.assertTrue(rows[first + 1].startswith("word") or rows[first + 1].startswith("d"))

    def test_an_untitled_entry_shows_the_stamp_alone_right_aligned(self):
        session, store, gid = self._open()
        store._goal_log.append(
            GoalLogEntry(99, gid, "", "untitled body", "2026-09-19T09:30:00+01:00")
        )
        session.run(session.app.screen.poll_refresh)
        session.pause()
        width = self._width(session)
        rows = _rows(session)
        row = next(r for r in rows if r[:width].strip() == "2026-09-19 09:30")
        self.assertTrue(row[:width].endswith("2026-09-19 09:30"))
        self.assertTrue(row.startswith(" "))

    def test_log_fits_a_narrow_terminal(self):
        frame = render("goal-hub#log", size=(44, 30))
        self.assertIn("Per-machine thresholds", frame)


class TestGoalLogSearch(unittest.TestCase):
    def _open(self, populated=True):
        store, gid = _goals_store(with_content=populated)
        session = _launch(store)
        self.addCleanup(session.close)
        session.press("[")
        session.press("enter")
        session.press("]")
        return session, store, gid

    def _type(self, session, text):
        screen = session.app.screen
        session.run(lambda: setattr(screen.query_one(GoalLogFilterInput), "value", text))
        session.pause()
        session.run(screen.on_log_filter_settled)
        session.pause()

    def _shortcuts(self, session):
        return session.run(lambda: session.app.screen.query_one(ShortcutBar).shortcuts)

    def test_slash_focuses_the_search_input_on_the_log_tab(self):
        session, _, _ = self._open()
        session.press("/")
        self.assertIsInstance(session.app.screen.focused, GoalLogFilterInput)
        self.assertIn("SEARCH", _frame(session))

    def test_slash_is_inert_on_overview_and_items(self):
        session, _, _ = self._open()
        for _ in range(2):
            session.press("]")
            session.press("/")
            self.assertNotIsInstance(session.app.screen.focused, GoalLogFilterInput)
            self.assertIsInstance(session.app.screen, GoalHubScreen)

    def test_slash_is_bound_on_the_screen(self):
        self.assertIn("/", {b.key for b in GoalHubScreen.BINDINGS})

    def test_typing_narrows_by_title_or_body_and_clearing_restores(self):
        session, _, _ = self._open()
        session.press("/")
        self._type(session, "starves")
        frame = _frame(session)
        self.assertIn("Suspending cannot relieve", frame)
        self.assertNotIn("Per-machine thresholds", frame)
        self._type(session, "PER-MACHINE")
        frame = _frame(session)
        self.assertIn("Per-machine thresholds", frame)
        self.assertNotIn("Suspending cannot relieve", frame)
        self._type(session, "")
        frame = _frame(session)
        self.assertIn("Per-machine thresholds", frame)
        self.assertIn("Suspending cannot relieve", frame)

    def test_escape_returns_to_the_log_keeping_text_and_a_second_escape_closes_the_hub(self):
        session, _, _ = self._open()
        session.press("/")
        self._type(session, "starves")
        session.press("escape")
        screen = session.app.screen
        self.assertIsInstance(screen, GoalHubScreen)
        self.assertNotIsInstance(screen.focused, GoalLogFilterInput)
        self.assertEqual(screen.query_one(GoalLogFilterInput).value, "starves")
        session.press("escape")
        self.assertNotIsInstance(session.app.screen, GoalHubScreen)

    def test_tab_up_down_and_enter_leave_the_field(self):
        for key in ("tab", "up", "down", "enter"):
            session, _, _ = self._open()
            session.press("/")
            session.press(key)
            self.assertNotIsInstance(session.app.screen.focused, GoalLogFilterInput, key)
            self.assertIsInstance(session.app.screen, GoalHubScreen)

    def test_q_typed_in_the_field_is_text_not_quit(self):
        session, _, _ = self._open()
        session.press("/")
        session.press("q")
        self.assertEqual(session.app.screen.query_one(GoalLogFilterInput).value, "q")

    def test_a_poll_that_adds_an_entry_keeps_the_filter_applied(self):
        session, store, gid = self._open()
        session.press("/")
        self._type(session, "starves")
        store.add_goal_log(gid, "Brand new decision", "no matching words here")
        store.add_goal_log(gid, "Another starves entry", "starves again")
        session.run(session.app.screen.poll_refresh)
        session.pause()
        frame = _frame(session)
        self.assertIn("Another starves entry", frame)
        self.assertIn("Suspending cannot relieve", frame)
        self.assertNotIn("Brand new decision", frame)
        self.assertNotIn("Per-machine thresholds", frame)

    def test_no_entries_shows_the_empty_message_and_no_search_row(self):
        session, _, _ = self._open(populated=False)
        frame = _frame(session)
        self.assertIn(GOAL_LOG_EMPTY_MESSAGE, frame)
        self.assertNotIn("SEARCH", frame)
        session.press("/")
        self.assertNotIsInstance(session.app.screen.focused, GoalLogFilterInput)

    def test_entries_without_a_match_show_the_no_match_message_and_keep_the_row(self):
        session, _, _ = self._open()
        session.press("/")
        self._type(session, "zzz-nothing")
        frame = _frame(session)
        self.assertIn(GOAL_LOG_NO_MATCH_MESSAGE, frame)
        self.assertNotIn(GOAL_LOG_EMPTY_MESSAGE, frame)
        self.assertIn("SEARCH", frame)

    def test_the_search_row_is_absent_off_the_log_tab(self):
        session, _, _ = self._open()
        session.press("]")
        self.assertNotIn("SEARCH", _frame(session))

    def test_footer_follows_tab_and_focus(self):
        session, _, _ = self._open()
        self.assertEqual(self._shortcuts(session), GOAL_LOG_SHORTCUTS)
        session.press("/")
        self.assertEqual(self._shortcuts(session), GOAL_LOG_SEARCH_SHORTCUTS)
        session.press("escape")
        self.assertEqual(self._shortcuts(session), GOAL_LOG_SHORTCUTS)
        session.press("]")
        self.assertEqual(self._shortcuts(session), HUB_SHORTCUTS)

    def test_empty_log_keeps_the_plain_hub_footer(self):
        session, _, _ = self._open(populated=False)
        self.assertEqual(self._shortcuts(session), HUB_SHORTCUTS)

    def test_the_settle_timer_is_stopped_when_the_screen_is_suspended(self):
        from unittest.mock import patch

        session, _, _ = self._open()
        session.press("/")
        screen = session.app.screen
        session.run(lambda: setattr(screen.query_one(GoalLogFilterInput), "value", "x"))
        session.pause()
        timer = screen._filter_timer
        with patch.object(timer, "stop", wraps=timer.stop) as stop:
            session.run(screen.on_screen_suspend)
        stop.assert_called_once()
        self.assertIsNone(screen._filter_timer)
