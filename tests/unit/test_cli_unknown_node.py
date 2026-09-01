import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from lightcycle import cli
from tests.support.fake_store import FakeStore


class _Cfg:
    def reconcile_config(self):
        pass

    def is_worker(self):
        return False


class _Container:
    def __init__(self):
        self.config = _Cfg()
        self.store = FakeStore()
        self.fs = None
        self.git = None
        self.workflow_source = None


class TestMainRefusesUnknownNodeId(unittest.TestCase):
    def setUp(self):
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))
        self._container = _Container()

    def _run(self, argv):
        err = io.StringIO()
        with mock.patch.object(cli, "Container", lambda: self._container):
            with redirect_stderr(err):
                rc = cli.main(argv)
        return rc, err.getvalue()

    def test_show_unknown_item_id_exits_nonzero_with_no_traceback(self):
        rc, err = self._run(["show", "LC-999"])
        self.assertEqual(rc, 1)
        self.assertEqual(err, "unknown node 'LC-999'\n")

    def test_done_unknown_theme_id_exits_nonzero_with_no_traceback(self):
        rc, err = self._run(["done", "LC-THEME-999", "wontfix"])
        self.assertEqual(rc, 1)
        self.assertEqual(err, "unknown node 'LC-THEME-999'\n")

    def test_message_does_not_say_step_for_show(self):
        _, err = self._run(["show", "LC-999"])
        self.assertNotIn("step not found", err)
        self.assertEqual(err, "unknown node 'LC-999'\n")

    def test_message_does_not_say_step_for_done(self):
        _, err = self._run(["done", "LC-THEME-999", "wontfix"])
        self.assertNotIn("step not found", err)
        self.assertEqual(err, "unknown node 'LC-THEME-999'\n")

    def test_set_state_in_progress_on_unknown_id_exits_cleanly(self):
        rc, err = self._run(["set", "LC-999", "--state", "in_progress"])
        self.assertEqual(rc, 1)
        self.assertEqual(err, "unknown node 'LC-999'\n")

    def test_set_state_active_on_unknown_id_exits_cleanly(self):
        rc, err = self._run(["set", "LC-999", "--state", "active"])
        self.assertEqual(rc, 1)
        self.assertEqual(err, "unknown node 'LC-999'\n")


if __name__ == "__main__":
    unittest.main()
