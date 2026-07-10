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
            "Set LC_ROOT_OVERRIDE to a throwaway store for branch-code execution."
        )):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = main(["status"])
        self.assertEqual(rc, 1)
        self.assertIn("refusing the live store", err.getvalue())


if __name__ == "__main__":
    unittest.main()
