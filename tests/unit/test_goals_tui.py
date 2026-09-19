import unittest

from lightcycle.adapters.tui.app import GoalsTable, GoalsView, TabStrip
from lightcycle.adapters.tui.goal_hub import (
    GOAL_ITEMS_EMPTY_MESSAGE,
    GOAL_DESCRIPTION_EMPTY_MESSAGE,
    GOAL_TAB_ORDER,
    GoalHubScreen,
)
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
            frame.index("Status is three hand-set values"),
            frame.index("Goals are not nodes"),
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
            "goal-hub#overview-empty", "goal-hub#items", "goal-hub#items-empty",
        ):
            self.assertIn(state, SCREENS)
        for state in ("goal-hub#questions", "goal-hub#questions-empty"):
            self.assertNotIn(state, SCREENS)

    def test_goal_hub_fits_a_narrow_terminal(self):
        frame = render("goal-hub#overview", size=(44, 30))
        self.assertIn("Overview", frame)
