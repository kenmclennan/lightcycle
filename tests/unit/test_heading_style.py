import unittest

from rich.color import Color

from lightcycle.adapters.tui.design_system import COLOURS, HEADING_STYLE
from tests.support.screen_render import _goals_store, _launch, _long_description_store, _open_hub


def _painted(session):
    strips = session.run(lambda: session.app.screen._compositor.render_strips())
    return [
        (segment.text, segment.style)
        for strip in strips
        for segment in strip
        if segment.text.strip()
    ]


def _is_heading(style):
    return bool(
        style
        and style.bold
        and style.color is not None
        and style.color.get_truecolor().hex == COLOURS["cyan"]
    )


def _style_of(session, text):
    for painted, style in _painted(session):
        if text in painted:
            return style
    raise AssertionError("%r is not painted" % text)


class _GoalHub(unittest.TestCase):
    def _open(self, presses=(), size=(100, 30)):
        store, gid = _goals_store()
        session = _launch(store, size=size)
        self.addCleanup(session.close)
        for key in ("[", "enter") + tuple(presses):
            session.press(key)
        return session, store, gid


class TestHeadingStyle(unittest.TestCase):
    def test_the_style_is_bold_cyan(self):
        self.assertEqual(HEADING_STYLE, "bold " + COLOURS["cyan"])
        self.assertEqual(Color.parse(COLOURS["cyan"]).get_truecolor().hex, COLOURS["cyan"])


class TestHeadingSurfaces(_GoalHub):
    def test_overview_description_section_is_heading_styled_and_its_body_is_not(self):
        session, _, _ = self._open()
        self.assertTrue(_is_heading(_style_of(session, "Outcome")))
        self.assertFalse(_is_heading(_style_of(session, "The record is written by a person")))

    def test_log_titles_are_heading_styled_and_bodies_are_not(self):
        session, _, _ = self._open(presses=("]",))
        self.assertTrue(_is_heading(_style_of(session, "Per-machine thresholds")))
        self.assertFalse(_is_heading(_style_of(session, "Tried gating on")))

    def test_items_group_headers_are_heading_styled(self):
        session, _, _ = self._open(presses=("]", "]"), size=(100, 60))
        for label in ("CURRENT WORK", "BACKLOG", "DONE"):
            self.assertTrue(_is_heading(_style_of(session, label)), label)
        self.assertFalse(_is_heading(_style_of(session, "Goals slice 1")))

    def test_group_header_colour_survives_the_cursor_moving(self):
        session, _, _ = self._open(presses=("]", "]"))
        before = _style_of(session, "BACKLOG")
        for _ in range(3):
            session.press("down")
        after = _style_of(session, "BACKLOG")
        self.assertTrue(_is_heading(before))
        self.assertTrue(_is_heading(after))
        session.press("up")
        self.assertTrue(_is_heading(_style_of(session, "CURRENT WORK")))

    def test_a_wrapped_log_title_carries_the_heading_style_on_every_line(self):
        store, gid = _goals_store()
        long_title = "Wrapping title alpha beta gamma delta epsilon zeta eta theta"
        store.add_goal_log(gid, long_title, "body")
        session = _launch(store, size=(44, 30))
        self.addCleanup(session.close)
        for key in ("[", "enter", "]"):
            session.press(key)
        first = _style_of(session, "Wrapping title")
        last = _style_of(session, "theta")
        self.assertTrue(_is_heading(first))
        self.assertTrue(_is_heading(last))


class TestReferenceRendering(_GoalHub):
    def test_resolved_and_dead_references_render_in_the_same_pane(self):
        session, _, _ = self._open(size=(140, 40))
        rows = [text for text, _ in _painted(session)]
        joined = " ".join(rows)
        self.assertIn("Goals slice 4: the gate a human clears", joined)
        self.assertIn("(LC-861)", joined)
        self.assertIn("LC-9999", joined)
        self.assertIn("(not found)", joined)
        self.assertNotIn("[[", joined)
        self.assertNotIn("]]", joined)

    def test_the_parenthesised_tail_is_dim_outside_a_heading(self):
        session, _, _ = self._open(size=(140, 40))
        style = _style_of(session, "(not found)")
        self.assertEqual(style.color.get_truecolor().hex, COLOURS["dim"])

    def test_a_rename_repaints_without_the_description_changing(self):
        session, store, _ = self._open(size=(140, 40))
        store.edit_node("LC-861", title="Renamed gate slice")
        session.run(session.app.screen.poll_refresh)
        session.pause()
        self.assertIn("Renamed gate slice", " ".join(t for t, _ in _painted(session)))


class TestItemHubDescription(unittest.TestCase):
    def _open(self):
        store, item = _long_description_store()
        session = _open_hub(_launch(store, size=(140, 40)), item, tab="description")
        self.addCleanup(session.close)
        return session, store

    def test_the_heading_is_heading_styled_and_the_reference_resolves(self):
        session, _ = self._open()
        self.assertTrue(_is_heading(_style_of(session, "Problem")))
        self.assertFalse(_is_heading(_style_of(session, "This item exists to fix")))
        joined = " ".join(text for text, _ in _painted(session))
        self.assertIn("Goals slice 4: the gate a human clears", joined)
        self.assertIn("(LC-861)", joined)
        self.assertNotIn("##", joined)
        self.assertNotIn("[[", joined)

    def test_a_rename_repaints_without_the_description_changing(self):
        session, store = self._open()
        store.edit_node("LC-861", title="Renamed gate slice")
        session.run(session.app.screen.poll_refresh)
        session.pause()
        self.assertIn("Renamed gate slice", " ".join(t for t, _ in _painted(session)))
