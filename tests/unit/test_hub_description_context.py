import unittest

from lightcycle.adapters.tui.hub import DescriptionPane, NodeHubScreen
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container


def _pane_lines(screen):
    pane = screen.query_one(DescriptionPane)
    lines = ["".join(seg.text for seg in pane.render_line(i)).rstrip() for i in range(pane.size.height)]
    return [line for line in lines if line]


class TestDescriptionContextBlock(unittest.TestCase):
    def _hub(self, store, item):
        session = launch(make_test_container(store=store))
        self.addCleanup(session.close)
        session.run(
            lambda: session.app.push_screen(
                NodeHubScreen(session.app.container, item, session.app._now)
            )
        )
        session.pause()
        session.pause()
        return session.app.screen

    def test_full_context_shows_five_lines_above_the_text(self):
        s = FakeStore()
        backlog = s.create_item("Fix header", "d")
        item = s.create_item("item", "The description text", workflow="o/w@abc")
        s.add_artifact(item, "repo", "kenmclennan/lightcycle")
        s.add_artifact(item, "resolves", backlog, internal=True)
        goal = s.create_goal("Ship the thing")
        s.link_goal_item(goal, item)
        s.complete_node(item, "merged", disposition="completed", note="shipped in #12")
        lines = _pane_lines(self._hub(s, item))
        self.assertEqual(len(lines), 7)
        self.assertEqual(lines[0].split(), ["repo", "kenmclennan/lightcycle"])
        self.assertEqual(lines[1].split(), ["workflow", "o/w@abc"])
        self.assertEqual(lines[2].split(), ["goal", "Ship", "the", "thing", "(%s)" % goal])
        self.assertEqual(lines[3].split(), ["resolves", "Fix", "header", "(%s)" % backlog])
        self.assertEqual(lines[4].split(), ["note", "shipped", "in", "#12"])
        self.assertTrue(set(lines[5]) == {"─"})
        self.assertEqual(lines[6], "The description text")

    def test_item_with_no_context_renders_the_description_alone(self):
        s = FakeStore()
        item = s.create_item("item", "The description text")
        self.assertEqual(_pane_lines(self._hub(s, item)), ["The description text"])

    def test_an_unresolvable_resolves_id_renders_not_found_beside_a_resolving_one(self):
        s = FakeStore()
        backlog = s.create_item("Fix header", "d")
        item = s.create_item("item", "text")
        s.add_artifact(item, "resolves", backlog, internal=True)
        s.add_artifact(item, "resolves", "LC-9999", internal=True)
        lines = _pane_lines(self._hub(s, item))
        self.assertEqual(lines[0].split(), ["resolves", "Fix", "header", "(%s)" % backlog])
        self.assertEqual(lines[1].split(), ["resolves", "LC-9999", "(not", "found)"])

    def test_context_without_a_description_shows_the_block_and_not_the_empty_message(self):
        s = FakeStore()
        item = s.create_item("item", "", workflow="o/w@abc")
        screen = self._hub(s, item)
        self.assertTrue(screen._has_description)
        self.assertEqual(_pane_lines(screen)[0].split(), ["workflow", "o/w@abc"])


if __name__ == "__main__":
    unittest.main()


class TestDescriptionPaintsOnFirstLayout(unittest.TestCase):
    def test_description_is_painted_when_tabbed_into_before_any_poll(self):
        s = FakeStore()
        item = s.create_item("item", "The description text")
        session = launch(make_test_container(store=s))
        self.addCleanup(session.close)
        screen = NodeHubScreen(session.app.container, item, session.app._now, initial_tab="outputs")
        session.run(lambda: session.app.push_screen(screen))
        session.pause()
        session.pause()
        session.run(screen._poll_timer.pause)
        while screen._active_tab != "description":
            session.run(screen.action_next_tab)
        session.pause()
        session.pause()
        self.assertEqual(_pane_lines(screen), ["The description text"])
