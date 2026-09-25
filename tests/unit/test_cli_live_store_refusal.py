import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from lightcycle.adapters.sqlite_store import LiveStoreRefused, SchemaVersionRefused
from lightcycle.cli import main
from lightcycle.worker_main import main as worker_main


class TestMainRefusesLiveStoreFromWorktree(unittest.TestCase):
    def test_reports_the_refusal_and_exits_nonzero(self):
        with patch("lightcycle.cli.Container", side_effect=LiveStoreRefused(
            "running from a worktree checkout; refusing the live store. "
            "Branch code verifies via tests against a temp store; set LC_HOME to point elsewhere."
        )):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = main(["status"])
        self.assertEqual(rc, 1)
        self.assertIn("refusing the live store", err.getvalue())


class TestMainRefusesSchemaVersion(unittest.TestCase):
    def test_reports_the_refusal_without_a_traceback_and_exits_nonzero(self):
        with patch("lightcycle.cli.Container", side_effect=SchemaVersionRefused(
            "store schema version 3 is below the floor; refusing to open it"
        )):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = main(["status"])
        self.assertEqual(rc, 1)
        self.assertIn("below the floor", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


class TestWorkerMainRefusesStore(unittest.TestCase):
    def _run(self, exc):
        with patch("lightcycle.worker_main.Container", side_effect=exc):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = worker_main()
        return rc, err.getvalue()

    def test_schema_version_refusal_exits_nonzero_with_the_message(self):
        rc, out = self._run(SchemaVersionRefused("below the floor"))
        self.assertEqual(rc, 1)
        self.assertIn("below the floor", out)
        self.assertNotIn("Traceback", out)

    def test_live_store_refusal_exits_nonzero_with_the_message(self):
        rc, out = self._run(LiveStoreRefused("refusing the live store"))
        self.assertEqual(rc, 1)
        self.assertIn("refusing the live store", out)


if __name__ == "__main__":
    unittest.main()
