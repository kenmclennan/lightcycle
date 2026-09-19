import unittest

from lightcycle.adapters.tui.app import GoalsTable, GoalsView, TabStrip
from lightcycle.adapters.tui.goal_hub import (
    GOAL_ITEMS_EMPTY_MESSAGE,
    GOAL_ITEMS_NO_MATCH_MESSAGE,
    GOAL_DESCRIPTION_EMPTY_MESSAGE,
    GOAL_TAB_ORDER,
    GOAL_LOG_NO_MATCH_MESSAGE,
    GOAL_LOG_EMPTY_MESSAGE,
    GoalFilterInput,
    GoalHubScreen,
    GoalItemsFilterInput,
    GoalItemsTable,
    GoalLogFilterInput,
)
from lightcycle.adapters.tui.design_system import (
    GOAL_LOG_SEARCH_SHORTCUTS,
    GOAL_LOG_SHORTCUTS,
    HUB_SHORTCUTS,
)
from lightcycle.adapters.tui.footer import ShortcutBar
from lightcycle.domain.goals import GoalLogEntry
from lightcycle.domain.work import State
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

    def test_goals_list_names_the_project_of_goals_in_different_projects(self):
        store = FakeStore()
        store.create_goal("Alpha goal", "", "alpha")
        store.create_goal("Beta goal", "", "beta")
        session = self._launch(store)
        session.press("[")
        lines = _frame(session).splitlines()

        alpha = next(line for line in lines if "Alpha goal" in line)
        beta = next(line for line in lines if "Beta goal" in line)
        self.assertIn("alpha", alpha)
        self.assertNotIn("beta", alpha)
        self.assertIn("beta", beta)

    def test_goals_table_is_project_and_title_with_no_status_text(self):
        store, _ = _goals_store()
        session = self._launch(store)
        session.press("[")
        table = session.app.query_one(GoalsTable)
        frame = _frame(session)

        self.assertEqual(len(table.columns), 2)
        self.assertIn("lightcycle", frame)
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

    def test_items_show_three_groups_in_order_with_dim_headers(self):
        session, _, _ = self._open()
        for _ in range(2):
            session.press("]")
        frame = _frame(session)
        self.assertLess(frame.index("CURRENT WORK"), frame.index("BACKLOG"))
        self.assertLess(frame.index("BACKLOG"), frame.index("DONE"))
        for glyph in ("●", "◆", "○"):
            self.assertIn(glyph, frame)
        self.assertLess(frame.index("LC-864"), frame.index("LC-858"))
        self.assertLess(frame.index("LC-859"), frame.index("LC-857"))
        for item_id in ("LC-857", "LC-858", "LC-859", "LC-861", "LC-862", "LC-863", "LC-864"):
            self.assertEqual(frame.count(item_id + " "), 1)

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
            "goals#normal", "goals#two-projects", "goals#empty", "goal-hub#overview", "goal-hub#log",
            "goal-hub#log-search", "goal-hub#log-search-none", "goal-hub#log-empty",
            "goal-hub#overview-empty", "goal-hub#items", "goal-hub#items-empty",
            "goal-hub#items-search", "goal-hub#items-search-none",
        ):
            self.assertIn(state, SCREENS)
        for state in ("goal-hub#questions", "goal-hub#questions-empty"):
            self.assertNotIn(state, SCREENS)

    def test_goal_hub_fits_a_narrow_terminal(self):
        frame = render("goal-hub#overview", size=(44, 30))
        self.assertIn("Overview", frame)


class TestGoalItemsTab(unittest.TestCase):
    def _open(self, size=None):
        store, gid = _goals_store()
        session = _launch(store) if size is None else _launch(store, size=size)
        self.addCleanup(session.close)
        session.press("[")
        session.press("enter")
        for _ in range(2):
            session.press("]")
        return session, store, gid

    def _type(self, session, text):
        screen = session.app.screen
        session.run(lambda: setattr(screen.query_one(GoalItemsFilterInput), "value", text))
        session.pause()
        session.run(screen.on_items_filter_settled)
        session.pause()

    def _cursor_rows(self, session):
        return [line for line in _rows(session) if "❯" in line]

    def test_step_text_is_right_aligned_on_its_own_line(self):
        session, _, _ = self._open()
        lines = _rows(session)
        index = next(i for i, line in enumerate(lines) if "LC-862" in line)
        step_line = lines[index + 1]
        self.assertTrue(step_line.rstrip().endswith("write-code"))
        self.assertGreater(len(step_line) - len(step_line.lstrip()), 40)

    def test_dependency_blocked_row_shows_the_blocker_in_place_of_the_step(self):
        session, _, _ = self._open()
        frame = _frame(session)
        self.assertIn("○⊣", frame)
        self.assertIn("blocked · LC-862.1", frame)

    def test_backlog_and_done_rows_carry_no_glyph_or_step(self):
        session, _, _ = self._open()
        for line in _rows(session):
            if "LC-858" in line or "LC-859" in line or "LC-857" in line:
                self.assertRegex(line.strip(), r"^(❯\s+)?LC-85\d\s")

    def test_titles_wrap_instead_of_truncating_on_a_narrow_terminal(self):
        session, _, _ = self._open(size=(40, 40))
        frame = _frame(session)
        self.assertNotIn("…", frame)
        for word in ("gate", "human", "clears", "progress", "statement"):
            self.assertIn(word, frame)

    def test_cursor_starts_on_the_first_item_and_never_rests_on_a_header(self):
        session, _, _ = self._open()
        self.assertIn("LC-861", self._cursor_rows(session)[0])
        seen = []
        for _ in range(8):
            session.press("down")
            rows = self._cursor_rows(session)
            self.assertEqual(len(rows), 1)
            seen.append(rows[0])
        for header in ("CURRENT WORK", "BACKLOG", "DONE"):
            self.assertFalse(any(header in row for row in seen))
        self.assertTrue(any("LC-858" in row for row in seen))
        self.assertIn("LC-857", seen[-1])
        for _ in range(8):
            session.press("up")
        self.assertIn("LC-861", self._cursor_rows(session)[0])

    def test_enter_opens_the_step_hub_for_current_work_and_the_item_hub_otherwise(self):
        session, _, _ = self._open()
        session.press("enter")
        screen = session.app.screen
        self.assertIsInstance(screen, NodeHubScreen)
        self.assertEqual(screen._node_id, "LC-861.1")
        session.press("escape")
        self.assertIsInstance(session.app.screen, GoalHubScreen)
        self.assertEqual(session.app.screen._active_tab, "items")
        for _ in range(4):
            session.press("down")
        session.press("enter")
        self.assertEqual(session.app.screen._node_id, "LC-858")

    def test_right_opens_the_item_hub_like_enter(self):
        session, _, _ = self._open()
        for _ in range(4):
            session.press("down")
        session.press("right")
        self.assertIsInstance(session.app.screen, NodeHubScreen)
        self.assertEqual(session.app.screen._node_id, "LC-858")

    def test_slash_focuses_search_and_typing_narrows_all_groups(self):
        session, _, _ = self._open()
        session.press("/")
        self.assertIsInstance(session.app.screen.focused, GoalItemsFilterInput)
        self.assertIn("SEARCH", _frame(session))
        self._type(session, "slice 1")
        frame = _frame(session)
        self.assertIn("LC-858", frame)
        self.assertNotIn("LC-862", frame)
        self.assertNotIn("CURRENT WORK", frame)
        self._type(session, "")
        frame = _frame(session)
        for item_id in ("LC-857", "LC-858", "LC-862"):
            self.assertIn(item_id, frame)

    def test_search_spans_current_work_and_done_by_id(self):
        session, _, _ = self._open()
        session.press("/")
        self._type(session, "lc-86")
        frame = _frame(session)
        self.assertIn("CURRENT WORK", frame)
        self.assertNotIn("BACKLOG", frame)
        self.assertNotIn("DONE", frame)

    def test_no_match_message(self):
        session, _, _ = self._open()
        session.press("/")
        self._type(session, "zzzz-no-such-term")
        frame = _frame(session)
        self.assertIn(GOAL_ITEMS_NO_MATCH_MESSAGE, frame)
        self.assertIn("SEARCH", frame)

    def test_escape_leaves_search_keeping_text(self):
        session, _, _ = self._open()
        session.press("/")
        self._type(session, "slice 1")
        session.press("escape")
        screen = session.app.screen
        self.assertIsInstance(screen, GoalHubScreen)
        self.assertIsInstance(screen.focused, GoalItemsTable)
        self.assertEqual(screen.query_one(GoalItemsFilterInput).value, "slice 1")

    def test_footer_follows_focus_on_the_items_tab(self):
        session, _, _ = self._open()

        def shortcuts():
            return session.run(lambda: session.app.screen.query_one(ShortcutBar).shortcuts)

        self.assertEqual(shortcuts(), GOAL_LOG_SHORTCUTS)
        session.press("/")
        self.assertEqual(shortcuts(), GOAL_LOG_SEARCH_SHORTCUTS)

    def test_search_row_is_absent_when_the_goal_has_no_items(self):
        store, _ = _goals_store(with_content=False)
        session = _launch(store)
        self.addCleanup(session.close)
        session.press("[")
        session.press("enter")
        for _ in range(2):
            session.press("]")
        frame = _frame(session)
        self.assertNotIn("SEARCH", frame)
        self.assertIn(GOAL_ITEMS_EMPTY_MESSAGE, frame)

    def test_a_state_change_repaints_on_the_next_poll(self):
        session, store, _ = self._open()
        store.update_state("LC-862.1", State.QUEUED)
        store.assign("LC-862.1", None)
        session.run(session.app.screen.poll_refresh)
        session.pause()
        lines = _rows(session)
        row = next(line for line in lines if "LC-862" in line)
        self.assertIn("○", row)


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

    def test_slash_is_inert_on_overview(self):
        session, _, _ = self._open()
        session.press("[")
        session.press("/")
        self.assertNotIsInstance(session.app.screen.focused, GoalFilterInput)
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

    def test_the_search_row_is_absent_on_overview(self):
        session, _, _ = self._open()
        session.press("[")
        self.assertNotIn("SEARCH", _frame(session))

    def test_footer_follows_tab_and_focus(self):
        session, _, _ = self._open()
        self.assertEqual(self._shortcuts(session), GOAL_LOG_SHORTCUTS)
        session.press("/")
        self.assertEqual(self._shortcuts(session), GOAL_LOG_SEARCH_SHORTCUTS)
        session.press("escape")
        self.assertEqual(self._shortcuts(session), GOAL_LOG_SHORTCUTS)
        session.press("]")
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


class TestGoalStateOfPlayOverview(unittest.TestCase):
    def _open(self, description, state_of_play):
        store, gid = _goals_store(with_content=False)
        store.update_goal(gid, description=description)
        if state_of_play:
            store.finish_goal_state_of_play(gid, state_of_play)
        session = _launch(store)
        self.addCleanup(session.close)
        session.press("[")
        session.press("enter")
        return session

    def test_description_then_header_then_text_in_that_order(self):
        frame = _frame(self._open("the described problem", "do the first thing next"))

        marks = ["the described problem", "State of play", "do the first thing next"]
        positions = [frame.index(m) for m in marks]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn(GOAL_DESCRIPTION_EMPTY_MESSAGE, frame)

    def test_a_goal_without_one_shows_no_header(self):
        frame = _frame(self._open("the described problem", ""))

        self.assertIn("the described problem", frame)
        self.assertNotIn("State of play", frame)

    def test_state_of_play_alone_replaces_the_empty_message_and_takes_focus(self):
        session = self._open("", "only the generated text")
        frame = _frame(session)

        self.assertIn("only the generated text", frame)
        self.assertNotIn(GOAL_DESCRIPTION_EMPTY_MESSAGE, frame)
        self.assertEqual(session.app.screen.focused.id, "goal-description-view")

    def test_neither_shows_the_empty_message(self):
        self.assertIn(GOAL_DESCRIPTION_EMPTY_MESSAGE, _frame(self._open("", "")))
