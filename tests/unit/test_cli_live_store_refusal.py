import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from lightcycle.adapters.sqlite_store import LiveStoreRefused
from lightcycle.cli import main


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


if __name__ == "__main__":
    unittest.main()
