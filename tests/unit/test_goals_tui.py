import unittest

from lightcycle.adapters.tui.app import GoalsTable, GoalsView, TabStrip
from lightcycle.adapters.tui.goal_hub import (
    GOAL_ITEMS_EMPTY_MESSAGE,
    GOAL_PROGRESS_NOT_BUILT_MESSAGE,
    GOAL_QUESTIONS_EMPTY_MESSAGE,
    GOAL_TAB_ORDER,
    GoalHubScreen,
)
from lightcycle.adapters.tui.hub import HUB_TAB_STRIP_CSS, HubTabStrip, NodeHubScreen
from tests.support.fake_store import FakeStore
from tests.support.screen_render import (
    GOAL_OUTCOME,
    SCREENS,
    _goals_store,
    _launch,
    render,
)


def _frame(session):
    from tests.support.screen_render import _plain_row

    strips = session.run(lambda: session.app.screen._compositor.render_strips())
    return "\n".join(_plain_row(strip) for strip in strips)


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
        self.assertIn("%s  Ship the goals record" % gid, _frame(session))

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

    def test_tabs_are_overview_log_questions_items_and_wrap_both_ways(self):
        session, _, _ = self._open()
        strip = session.app.screen.query_one(HubTabStrip)
        labels = [str(child.content) for child in strip.children]
        self.assertEqual(labels, ["Overview", "Log", "Open questions", "Items"])
        self.assertEqual(GOAL_TAB_ORDER, ("overview", "log", "questions", "items"))

        seen = []
        for _ in range(4):
            session.press("]")
            seen.append(session.app.screen._active_tab)
        self.assertEqual(seen, ["log", "questions", "items", "overview"])

        session.press("[")
        self.assertEqual(session.app.screen._active_tab, "items")

    def test_escape_and_left_close_the_hub(self):
        for key in ("escape", "left"):
            session, _, _ = self._open()
            session.press(key)
            self.assertNotIsInstance(session.app.screen, GoalHubScreen)

    def test_overview_wraps_long_prose_and_says_progress_is_not_built(self):
        session, _, _ = self._open()
        frame = _frame(session)
        first_line = GOAL_OUTCOME[:40]
        self.assertIn(first_line, frame)
        self.assertNotIn(GOAL_OUTCOME, frame)
        self.assertIn(GOAL_PROGRESS_NOT_BUILT_MESSAGE, frame)
        self.assertIn("not started", frame)

    def test_overview_of_a_bare_goal_shows_empty_states_not_blank_panes(self):
        session, _, _ = self._open(populated=False)
        frame = _frame(session)
        self.assertIn("No outcome written yet.", frame)
        self.assertIn("No scope written yet.", frame)

    def test_log_is_newest_first(self):
        session, _, _ = self._open()
        session.press("]")
        frame = _frame(session)
        self.assertLess(
            frame.index("Status is three hand-set values"),
            frame.index("Goals are not nodes"),
        )

    def test_questions_lists_only_open_ones_newest_first(self):
        session, store, gid = self._open()
        store.resolve_goal_question(2, "the driver")
        session.press("]")
        session.press("]")
        session.run(session.app.screen.poll_refresh)
        session.pause()
        frame = _frame(session)
        self.assertIn("Should a goal ever close itself", frame)
        self.assertNotIn("Who owns the progress statement", frame)

    def test_questions_empty_state(self):
        session, _, _ = self._open(populated=False)
        session.press("]")
        session.press("]")
        self.assertIn(GOAL_QUESTIONS_EMPTY_MESSAGE, _frame(session))

    def test_items_show_ids_and_titles_and_no_state(self):
        session, _, _ = self._open()
        for _ in range(3):
            session.press("]")
        frame = _frame(session)
        self.assertIn("LC-858", frame)
        self.assertIn("Goals slice 1: the record and the tab", frame)
        for word in ("todo", "ready", "running", "waiting", "blocked", "active"):
            self.assertNotIn(word, frame)

    def test_items_empty_state(self):
        session, _, _ = self._open(populated=False)
        for _ in range(3):
            session.press("]")
        self.assertIn(GOAL_ITEMS_EMPTY_MESSAGE, _frame(session))

    def test_a_log_entry_written_elsewhere_appears_after_a_poll(self):
        session, store, gid = self._open()
        session.press("]")
        store.add_goal_log(gid, "a decision made in another terminal")
        session.run(session.app.screen.poll_refresh)
        session.pause()
        self.assertIn("a decision made in another terminal", _frame(session))

    def test_both_hubs_carry_the_shared_tab_strip_rules(self):
        self.assertIn(HUB_TAB_STRIP_CSS, GoalHubScreen.CSS)
        self.assertIn(HUB_TAB_STRIP_CSS, NodeHubScreen.CSS)

    def test_goal_hub_states_are_registered(self):
        for state in (
            "goals#normal", "goals#empty", "goal-hub#overview", "goal-hub#log",
            "goal-hub#questions", "goal-hub#questions-empty", "goal-hub#items",
            "goal-hub#items-empty",
        ):
            self.assertIn(state, SCREENS)

    def test_goal_hub_fits_a_narrow_terminal(self):
        frame = render("goal-hub#overview", size=(44, 30))
        self.assertIn("Overview", frame)
