import unittest

from lightcycle.adapters.tui.design_system import HEADING_STYLE
from lightcycle.adapters.tui.hub import (
    ContextTable,
    ListArtifactViewerScreen,
    NodeHubScreen,
    TextArtifactViewerScreen,
)
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.screen_render import NOW, _launch
from tests.support.tui_harness import FakeLauncher


def _store():
    store = FakeStore()
    item = store.create_item("Item", "a description", id="LC-1")
    store.add_artifact(item, "spec-link", "https://example.test/spec", kind="url")
    store.add_artifact(item, "notes-file", "/tmp/notes.md", kind="filepath")
    store.add_artifact(item, "checks", "one\ntwo", kind="list")
    store.add_artifact(item, "summary", "a summary", kind="text")
    step = store.create_step(step="triage", role="human", parent=item, id="LC-1.1")
    store.set_report(step, "ship it")
    return store, step


class TestOpeningContextRows(unittest.TestCase):
    def setUp(self):
        self.launcher = FakeLauncher()
        store, step = _store()
        self.session = _launch(store, launcher=self.launcher, fs=FakeFs(files={"/tmp/notes.md": "notes"}))
        self.addCleanup(self.session.close)
        screen = NodeHubScreen(self.session.app._container, step, lambda: NOW, initial_tab="context")
        self.session.run(lambda: self.session.app.push_screen(screen))
        self.session.pause()
        self.session.pause()
        self.screen = screen

    def _open_row(self, row_key):
        for table in self.screen.query(ContextTable):
            for index, key in enumerate(k.value for k in table.rows):
                if self.screen._last_context_rows[int(key)].key == row_key:
                    self.session.run(lambda: self.screen.set_focus(table))
                    self.session.run(lambda: table.move_cursor(row=index))
                    self.session.press("enter")
                    self.session.pause()
                    return
        raise AssertionError(row_key)

    def test_a_url_row_opens_in_the_browser(self):
        self._open_row("spec-link")

        self.assertEqual(self.launcher.opened_urls, ["https://example.test/spec"])

    def test_a_filepath_row_opens_in_the_editor(self):
        self._open_row("notes-file")

        editor = self.session.app.container.config.editor()
        self.assertEqual(self.launcher.edited_detached, (editor, "/tmp/notes.md"))

    def test_a_text_row_opens_inline(self):
        self._open_row("summary")

        self.assertIsInstance(self.session.app.screen, TextArtifactViewerScreen)

    def test_a_list_row_opens_inline(self):
        self._open_row("checks")

        self.assertIsInstance(self.session.app.screen, ListArtifactViewerScreen)

    def _rendered_rows(self):
        strips = self.session.run(lambda: self.screen._compositor.render_strips())
        return ["".join(seg.text for seg in strip) for strip in strips]

    def _section_tables(self):
        return {t.name: t for t in self.screen.query(ContextTable)}

    def test_no_table_row_is_a_section_heading(self):
        for table in self._section_tables().values():
            for key in table.rows:
                self.assertFalse(key.value.startswith("__"))
                self.assertIn(self.screen._last_context_rows[int(key.value)].section, {table.name})

    def test_the_cursor_moves_from_the_last_inputs_row_to_the_first_outputs_row(self):
        tables = self._section_tables()
        inputs, outputs = tables["inputs"], tables["outputs"]
        self.session.run(lambda: self.screen.set_focus(inputs))
        self.session.run(lambda: inputs.move_cursor(row=inputs.row_count - 1))

        self.session.press("down")
        self.session.pause()

        self.assertIs(self.session.app.screen.focused, outputs)
        self.assertEqual(outputs.cursor_coordinate.row, 0)

    def test_the_cursor_moves_back_from_the_first_outputs_row_to_the_last_inputs_row(self):
        tables = self._section_tables()
        inputs, outputs = tables["inputs"], tables["outputs"]
        self.session.run(lambda: self.screen.set_focus(outputs))
        self.session.run(lambda: outputs.move_cursor(row=0))

        self.session.press("up")
        self.session.pause()

        self.assertIs(self.session.app.screen.focused, inputs)
        self.assertEqual(inputs.cursor_coordinate.row, inputs.row_count - 1)

    def test_a_heading_is_styled_as_a_heading_and_is_not_a_table_row(self):
        for section in ("inputs", "outputs", "records"):
            header = self.screen.query_one("#hub-context-header-%s" % section)
            self.assertTrue(header.content.plain.startswith(section.upper()))
            self.assertEqual(header.content.style, HEADING_STYLE)

    def test_no_source_column_is_rendered(self):
        for table in self._section_tables().values():
            self.assertEqual([c.key.value for c in table.columns.values()], ["key", "pass", "value"])

    def test_an_empty_section_shows_its_heading_and_none_and_neither_is_selectable(self):
        tables = self._section_tables()
        empty = next(name for name, t in tables.items() if not t.row_count)
        none = self.screen.query_one("#hub-context-none-%s" % empty)

        self.assertFalse(none.has_class("hidden"))
        self.assertEqual(str(none.content), "none")
        self.assertTrue(tables[empty].has_class("hidden"))
        self.assertTrue(self.screen.query_one("#hub-context-header-%s" % empty).display)
        self.assertFalse(none.can_focus)


if __name__ == "__main__":
    unittest.main()
