import unittest

from lightcycle.adapters.tui.hub import NodeHubScreen
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.support.screen_render import NOW, _launch
from tests.support.tui_harness import FakeLauncher


class TestOpeningDetailRows(unittest.TestCase):
    def setUp(self):
        self.launcher = FakeLauncher()
        store = FakeStore()
        item = store.create_item("Item", "a description", id="LC-1")
        step = store.create_step(stage="triage", role="human", item=item, id="LC-1.1")
        self.session = _launch(store, launcher=self.launcher, fs=FakeFs(files={"/tmp/wt": "x"}))
        self.addCleanup(self.session.close)
        self.screen = NodeHubScreen(self.session.app._container, step, lambda: NOW, initial_tab="detail")
        self.session.run(lambda: self.session.app.push_screen(self.screen))
        self.session.pause()
        self.session.pause()

    def _select(self, fields, key):
        self.screen._last_detail_fields = fields
        self.session.run(lambda: self.screen._open_selected_detail_field(key))
        self.session.pause()

    def test_a_url_value_under_any_key_opens_in_the_browser(self):
        self._select([("in:source", "  https://example.test/doc ")], "in:source")

        self.assertEqual(self.launcher.opened_urls, ["https://example.test/doc"])

    def test_a_prose_value_opens_nothing(self):
        self._select([("in:source", "see https://example.test/doc")], "in:source")

        self.assertEqual(self.launcher.opened_urls, [])
        self.assertIsNone(self.launcher.edited_detached)

    def test_the_pr_row_opens_in_the_browser(self):
        self._select([("pr", "https://example.test/pull/1")], "pr")

        self.assertEqual(self.launcher.opened_urls, ["https://example.test/pull/1"])

    def test_the_worktree_row_opens_in_the_editor(self):
        self._select([("worktree", "/tmp/wt")], "worktree")

        self.assertEqual(self.launcher.opened_urls, [])
        self.assertEqual(self.launcher.edited_detached[1], "/tmp/wt")

    def test_the_spec_pr_and_ci_checks_rows_open_in_the_browser(self):
        self._select([("spec-pr", "https://example.test/pull/2")], "spec-pr")
        self._select([("ci-checks", "https://example.test/pull/1/checks?sha=abc")], "ci-checks")

        self.assertEqual(
            self.launcher.opened_urls,
            ["https://example.test/pull/2", "https://example.test/pull/1/checks?sha=abc"])

    def test_the_spec_row_opens_as_a_path(self):
        self._select([("spec", "/tmp/wt")], "spec")

        self.assertEqual(self.launcher.opened_urls, [])
        self.assertEqual(self.launcher.edited_detached[1], "/tmp/wt")

    def test_every_leading_run_row_has_a_label(self):
        from lightcycle.adapters.tui.hub import DETAIL_FIELD_LABELS
        from lightcycle.domain.work.detail import leading_run_names

        for key in leading_run_names(True, True, True):
            self.assertIn(key, DETAIL_FIELD_LABELS)
