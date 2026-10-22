import unittest

from rich.color import Color

from lightcycle.adapters.tui.design_system import COLOURS, HEADING_STYLE
from tests.support.screen_render import _launch, _long_description_store, _open_hub


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


class TestHeadingStyle(unittest.TestCase):
    def test_the_style_is_bold_cyan(self):
        self.assertEqual(HEADING_STYLE, "bold " + COLOURS["cyan"])
        self.assertEqual(Color.parse(COLOURS["cyan"]).get_truecolor().hex, COLOURS["cyan"])


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
