import unittest

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
        table = self.screen.query_one(ContextTable)
        keys = [k.value for k in table.rows]
        index = next(
            i for i, key in enumerate(keys)
            if key not in ("__section:inputs__",) and self._key_of(key) == row_key
        )
        self.session.run(lambda: table.move_cursor(row=index))
        self.session.press("enter")
        self.session.pause()

    def _key_of(self, row_key):
        if row_key.startswith("__"):
            return row_key
        return self.screen._last_context_rows[int(row_key)].key

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

    def test_a_section_header_opens_nothing(self):
        self._open_row("__section:outputs__")

        self.assertIsInstance(self.session.app.screen, NodeHubScreen)
        self.assertEqual(self.launcher.opened_urls, [])
        self.assertIsNone(self.launcher.edited)
        self.assertIsNone(self.launcher.edited_detached)


if __name__ == "__main__":
    unittest.main()
